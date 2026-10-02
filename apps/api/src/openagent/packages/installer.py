"""MP22: installation service — preview / install / update / rollback.

Lifecycle::

    REQUESTED -> RESOLVING -> VALIDATING -> AWAITING_CONFIGURATION
      -> INSTALLING -> VERIFYING -> INSTALLED   (FAILED on any error)

Installation materializes package resources into real tenant-scoped rows
using the *existing* tables (agents, workflows, skills, presets) and
records every created node in ``installation_resources`` for audit,
update and rollback. Nothing executes here; execution stays in the
Agent Runtime / Workflow Engine / Tool Runtime behind their own policies.

Concurrency safety: installs carry an ``idempotency_key`` with a DB unique
constraint per organization; updates lock the installation row with
``SELECT ... FOR UPDATE`` (Postgres) and re-check status inside the
transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.db.models.package import PackageInstallStatus
from openagent.packages import config_schema, dependencies as dep_module
from openagent.packages import graph as graph_module
from openagent.packages import security as security_module
from openagent.packages import telemetry
from openagent.packages import validation as validation_module
from openagent.packages.manifest import parse_manifest
from openagent.packages.types import PackageStatus


class InstallationError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Registry snapshot (dependency availability from live DB state)
# ---------------------------------------------------------------------------

_RUNTIME_REQUIREMENT_TYPES = frozenset({"tool", "model", "memory", "mcp"})


async def _available_versions(
    db: AsyncSession, organization_id: UUID, dep_type: str, slug: str
) -> list[str]:
    """Published/accessible versions of a dependency target."""
    from openagent.db.models.package import (
        PackageVersion,
        PackageVersionStatus,
        Preset,
        PresetVersion,
        ReusablePackage,
        Skill,
        SkillVersion,
    )

    dtype = dep_type.lower()
    if dtype == "skill":
        rows = (
            await db.execute(
                select(SkillVersion.version)
                .join(Skill, Skill.id == SkillVersion.skill_id)
                .where(
                    Skill.slug == slug,
                    Skill.deleted_at.is_(None),
                    SkillVersion.status == PackageVersionStatus.PUBLISHED,
                )
            )
        ).scalars().all()
        return list(rows)
    if dtype == "package":
        rows = (
            await db.execute(
                select(PackageVersion.version)
                .join(ReusablePackage, ReusablePackage.id == PackageVersion.package_id)
                .where(
                    ReusablePackage.slug == slug,
                    ReusablePackage.deleted_at.is_(None),
                    PackageVersion.status == PackageVersionStatus.PUBLISHED,
                )
            )
        ).scalars().all()
        return list(rows)
    if dtype == "preset":
        rows = (
            await db.execute(
                select(PresetVersion.version)
                .join(Preset, Preset.id == PresetVersion.preset_id)
                .where(
                    Preset.slug == slug,
                    Preset.deleted_at.is_(None),
                    PresetVersion.status == PackageVersionStatus.PUBLISHED,
                )
            )
        ).scalars().all()
        return list(rows)
    if dtype == "connector":
        try:
            from openagent.db.models.connector import Connector, ConnectorVersion

            rows = (
                await db.execute(
                    select(ConnectorVersion.version)
                    .join(Connector, Connector.id == ConnectorVersion.connector_id)
                    .where(Connector.slug == slug, ConnectorVersion.is_active.is_(True))
                )
            ).scalars().all()
            return list(rows)
        except Exception:
            return []
    # Tools / models / memory / MCP are runtime requirements surfaced in the
    # preview; they must not hard-fail resolution (see _resolve()).
    return []


async def _child_dependencies(
    db: AsyncSession, organization_id: UUID, dtype: str, slug: str, version: str
) -> list[dep_module.DeclaredDependency]:
    from openagent.db.models.package import (
        PackageDependency,
        PackageVersion,
        PackageVersionStatus,
        ReusablePackage,
    )

    dtype = dtype.lower()
    if dtype == "skill":
        return []
    if dtype == "package":
        row = (
            await db.execute(
                select(PackageVersion)
                .join(ReusablePackage, ReusablePackage.id == PackageVersion.package_id)
                .where(
                    ReusablePackage.slug == slug,
                    PackageVersion.version == version,
                    PackageVersion.status == PackageVersionStatus.PUBLISHED,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return []
        deps = (
            await db.execute(
                select(PackageDependency).where(PackageDependency.version_id == row.id)
            )
        ).scalars().all()
        return [
            dep_module.DeclaredDependency(
                type=d.dep_type, package=d.package, version=d.constraint,
                optional=d.optional, peer=d.peer,
            )
            for d in deps
        ]
    return []


def _policy_allows(dtype: str, package: str) -> tuple[bool, str]:
    # Org-specific denials are applied in preview_install() against live
    # ToolPolicy rows; the resolver-level gate stays permissive so previews
    # can explain conflicts instead of failing opaquely.
    _ = (dtype, package)
    return True, ""


def _is_revoked(status: str) -> bool:
    return status == PackageStatus.REVOKED.value


async def _resolve(
    db: AsyncSession,
    organization_id: UUID,
    declared: list[dep_module.DeclaredDependency],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Resolve deps; runtime-requirement misses become warnings, not errors."""

    async def available(dtype: str, slug: str) -> list[str]:
        return await _available_versions(db, organization_id, dtype, slug)

    # The resolver is sync; bridge with a cached snapshot.
    snapshot: dict[tuple[str, str], list[str]] = {}
    children_snapshot: dict[tuple[str, str, str], list[dep_module.DeclaredDependency]] = {}

    async def fill(items: list[dep_module.DeclaredDependency]) -> None:
        for item in items:
            key = (item.type, item.package)
            if key not in snapshot:
                snapshot[key] = await available(item.type, item.package)
                for version in snapshot[key]:
                    ckey = (item.type, item.package, version)
                    if ckey not in children_snapshot:
                        children_snapshot[ckey] = await _child_dependencies(
                            db, organization_id, item.type, item.package, version
                        )
                await fill([c for versions in children_snapshot.values() for c in versions])

    await fill(declared)
    result = dep_module.resolve_dependencies(
        declared,
        available=lambda dtype, slug: snapshot.get((dtype, slug), []),
        children=lambda dtype, slug, version: children_snapshot.get((dtype, slug, version), []),
        policy_allows=_policy_allows,
    )
    resolved = [
        {"type": r.type, "package": r.package, "constraint": r.constraint,
         "resolved_version": r.resolved_version, "optional": r.optional}
        for r in result.resolved
    ]
    failures = [
        {"code": f.code, "package": f.package, "message": f.message,
         "constraint": f.constraint, "path": f.path}
        for f in result.failures
    ]
    # Downgrade runtime-requirement misses to warnings (surfaced as
    # required_tools / required_models in the preview).
    kept_failures: list[dict[str, Any]] = []
    runtime_warnings: list[str] = list(result.warnings)
    for failure in failures:
        dtype = ""
        for part in failure.get("path", []):
            if ":" in part:
                dtype = part.split(":")[0].lower()
        if dtype in _RUNTIME_REQUIREMENT_TYPES and failure["code"] in (
            "MISSING_DEPENDENCY", "UNSATISFIABLE_CONSTRAINT",
        ):
            runtime_warnings.append(failure["message"])
        else:
            kept_failures.append(failure)
    return resolved, kept_failures, runtime_warnings


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

async def preview_install(
    db: AsyncSession,
    *,
    organization_id: UUID,
    version_id: UUID,
    values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the installation preview (no writes)."""
    from openagent.db.models.package import (
        PackageDependency,
        PackageResource,
        PackageVersion,
        PackageVersionStatus,
    )
    from openagent.db.models.tool import ToolPolicy

    version = await db.get(PackageVersion, version_id)
    if version is None:
        raise InstallationError("VERSION_NOT_FOUND", "package version not found")
    if version.status == PackageVersionStatus.REVOKED:
        raise InstallationError("REVOKED", "this package version was revoked and cannot install")
    manifest_dict = dict(version.manifest or {})
    manifest = parse_manifest(manifest_dict)

    deps = (
        await db.execute(select(PackageDependency).where(PackageDependency.version_id == version.id))
    ).scalars().all()
    declared = [
        dep_module.DeclaredDependency(
            type=d.dep_type, package=d.package, version=d.constraint,
            optional=d.optional, peer=d.peer,
        )
        for d in deps
    ]
    resolved, failures, warnings = await _resolve(db, organization_id, declared)

    resources = (
        await db.execute(select(PackageResource).where(PackageResource.version_id == version.id))
    ).scalars().all()
    resources_to_create = [
        {"kind": r.kind, "slug": r.slug, "name": r.name} for r in resources
    ]

    required_tools: set[str] = set()
    required_connectors: set[str] = set()
    required_skills: set[str] = set()
    required_models: set[str] = set()
    required_permissions: set[str] = set()
    for resource in resources:
        payload = resource.payload or {}
        for tool in payload.get("required_tools", []) or payload.get("tools", []) or []:
            if isinstance(tool, str):
                required_tools.add(tool)
        for connector in payload.get("required_connectors", []) or payload.get("connectors", []) or []:
            if isinstance(connector, str):
                required_connectors.add(connector)
        for skill in payload.get("skills", []) or []:
            if isinstance(skill, str):
                required_skills.add(skill)
        model_preset = payload.get("model_preset")
        if isinstance(model_preset, str) and model_preset:
            required_models.add(model_preset)
        for capability in payload.get("capabilities", []) or []:
            required_permissions.add(str(capability))
    for item in resolved:
        if item["type"] == "tool":
            required_tools.add(item["package"])
        elif item["type"] == "connector":
            required_connectors.add(item["package"])
        elif item["type"] == "skill":
            required_skills.add(item["package"])

    # Policy conflicts: most-restrictive-wins against ToolPolicy denials.
    policy_conflicts: list[str] = []
    try:
        policies = (await db.execute(select(ToolPolicy))).scalars().all()
        for policy in policies:
            blocked = set(getattr(policy, "blocked_tools", []) or [])
            blocked_cats = set(getattr(policy, "blocked_categories", []) or [])
            for tool in sorted(required_tools):
                if tool in blocked:
                    policy_conflicts.append(f"tool {tool!r} is blocked by policy {policy.name!r}")
            for resource in resources:
                category = str((resource.payload or {}).get("category", ""))
                if category in blocked_cats:
                    policy_conflicts.append(
                        f"resource {resource.slug!r} category {category!r} blocked by {policy.name!r}"
                    )
    except Exception:
        pass

    schema = manifest.configuration or {}
    configuration_required = config_schema.required_references(schema)
    resolved_values, config_errors = config_schema.validate_configuration(schema, values or {})

    security_findings = security_module.scan_manifest_dict(manifest_dict)
    risk = security_module.risk_level(security_findings)

    graph = graph_module.build_graph(
        [{"kind": r.kind, "slug": r.slug, "name": r.name, "payload": r.payload} for r in resources],
        [d.model_dump() for d in manifest.dependencies],
    )
    return {
        "package": {"id": manifest.package.id, "name": manifest.package.name,
                    "type": manifest.package.type},
        "version": manifest.package.version,
        "version_id": str(version.id),
        "resources_to_create": resources_to_create,
        "dependencies": resolved,
        "dependency_failures": failures,
        "dependency_warnings": warnings,
        "required_credentials": configuration_required,
        "required_connectors": sorted(required_connectors),
        "required_tools": sorted(required_tools),
        "required_skills": sorted(required_skills),
        "required_models": sorted(required_models),
        "required_permissions": sorted(required_permissions),
        "security_warnings": security_findings,
        "risk": risk,
        "policy_conflicts": policy_conflicts,
        "configuration_required": configuration_required,
        "configuration_fields": config_schema.ui_fields(schema),
        "configuration_errors": config_errors,
        "configuration_valid": not config_errors,
        "estimated_changes": {
            "resources": len(resources_to_create),
            "dependencies": len(resolved),
            "configuration_inputs": len(schema.get("inputs", {})) if isinstance(schema, dict) else 0,
        },
        "graph": graph,
        "can_install": not failures and not policy_conflicts and not config_errors,
    }


# ---------------------------------------------------------------------------
# Materialization helpers
# ---------------------------------------------------------------------------

async def _unique_slug(db: AsyncSession, model: Any, organization_id: UUID, base: str) -> str:
    slug = base[:100]
    candidate = slug
    suffix = 2
    while True:
        exists = (
            await db.execute(
                select(func.count()).where(
                    model.organization_id == organization_id, model.slug == candidate
                )
            )
        ).scalar_one()
        if not exists:
            return candidate
        candidate = f"{slug[:90]}-{suffix}"
        suffix += 1


async def _upsert_agent_version(db: AsyncSession, *, agent_id: UUID,
                                version: str, name: str,
                                instructions: Any, configuration: dict[str, Any],
                                created_by: Any) -> None:
    """Insert or refresh a local AgentVersion (rollback/update idempotency)."""
    from openagent.db.models.agent import AgentVersion

    existing = (await db.execute(select(AgentVersion).where(
        AgentVersion.agent_id == agent_id,
        AgentVersion.version == version))).scalar_one_or_none()
    if existing is None:
        db.add(AgentVersion(agent_id=agent_id, version=version, name=name,
                            instructions=instructions, configuration=configuration,
                            status="draft", created_by=created_by))
    else:
        existing.name = name
        existing.instructions = instructions
        existing.configuration = configuration
        existing.status = "draft"
    await db.flush()


async def _upsert_workflow_version(db: AsyncSession, *, workflow_id: UUID,
                                   version: str, definition: dict[str, Any],
                                   created_by: Any) -> None:
    from openagent.db.models.workflow import WorkflowVersion

    existing = (await db.execute(select(WorkflowVersion).where(
        WorkflowVersion.workflow_id == workflow_id,
        WorkflowVersion.version == version))).scalar_one_or_none()
    if existing is None:
        db.add(WorkflowVersion(workflow_id=workflow_id, version=version,
                               definition=definition, status="draft",
                               created_by=created_by))
    else:
        existing.definition = definition
        existing.status = "draft"
    await db.flush()


async def _upsert_skill_version(db: AsyncSession, *, skill_id: UUID,
                                version: str, payload: dict[str, Any],
                                created_by: Any) -> None:
    from openagent.db.models.package import SkillVersion

    existing = (await db.execute(select(SkillVersion).where(
        SkillVersion.skill_id == skill_id,
        SkillVersion.version == version))).scalar_one_or_none()
    fields = {
        "instructions": str(payload.get("instructions", "")),
        "input_schema": payload.get("input_schema", {}),
        "output_schema": payload.get("output_schema", {}),
        "required_tools": payload.get("required_tools", []),
        "required_connectors": payload.get("required_connectors", []),
    }
    if existing is None:
        db.add(SkillVersion(skill_id=skill_id, version=version, **fields,
                            created_by=created_by))
    else:
        for key, value in fields.items():
            setattr(existing, key, value)
    await db.flush()


async def _materialize(
    db: AsyncSession,
    *,
    organization_id: UUID,
    installation_id: UUID,
    package_version: str,
    resources: list,
    installed_by,
) -> list[dict[str, str]]:
    """Create real tenant rows for resources; return ref records."""
    from openagent.db.models.agent import Agent, AgentType, AgentVersion, AgentStatus
    from openagent.db.models.package import (
        InstallationResource,
        Preset,
        PresetVersion,
        Skill,
        SkillVersion,
    )
    from openagent.db.models.workflow import Workflow, WorkflowStatus, WorkflowVersion

    created: list[dict[str, str]] = []
    for resource in resources:
        kind = str(resource.kind).upper()
        payload = dict(resource.payload or {})
        ref_type, ref_id = "", ""
        if kind == "AGENT":
            slug = await _unique_slug(db, Agent, organization_id, resource.slug)
            agent = Agent(
                organization_id=organization_id,
                name=resource.name or resource.slug,
                slug=slug,
                description=str(payload.get("description", "")) or None,
                status=AgentStatus.DRAFT,
                agent_type=AgentType.ASSISTANT,
                metadata={"installed_from": str(installation_id),
                          "package_version": package_version},
            )
            db.add(agent)
            await db.flush()
            db.add(
                AgentVersion(
                    agent_id=agent.id,
                    version=package_version,
                    name=resource.name or resource.slug,
                    instructions=str(payload.get("system_prompt", "")) or None,
                    configuration={
                        "model_preset": payload.get("model_preset", ""),
                        "skills": payload.get("skills", []),
                        "tools": payload.get("tools", payload.get("required_tools", [])),
                        "memory": payload.get("memory", {}),
                        "guardrails": payload.get("guardrails", {}),
                    },
                    status="draft",
                    created_by=installed_by,
                )
            )
            ref_type, ref_id = "agent", str(agent.id)
        elif kind == "WORKFLOW":
            slug = await _unique_slug(db, Workflow, organization_id, resource.slug)
            workflow = Workflow(
                organization_id=organization_id,
                name=resource.name or resource.slug,
                slug=slug,
                description=str(payload.get("description", "")) or None,
                status=WorkflowStatus.DRAFT,
                metadata={"installed_from": str(installation_id),
                          "package_version": package_version},
            )
            db.add(workflow)
            await db.flush()
            db.add(
                WorkflowVersion(
                    workflow_id=workflow.id,
                    version=package_version,
                    definition=payload,
                    status="draft",
                    created_by=installed_by,
                )
            )
            ref_type, ref_id = "workflow", str(workflow.id)
        elif kind == "SKILL":
            slug = await _unique_slug(db, Skill, organization_id, resource.slug)
            skill = Skill(
                organization_id=organization_id,
                slug=slug,
                name=resource.name or resource.slug,
                description=str(payload.get("description", "")),
            )
            db.add(skill)
            await db.flush()
            db.add(
                SkillVersion(
                    skill_id=skill.id,
                    version=package_version,
                    instructions=str(payload.get("instructions", "")),
                    input_schema=payload.get("input_schema", {}),
                    output_schema=payload.get("output_schema", {}),
                    required_tools=payload.get("required_tools", []),
                    required_connectors=payload.get("required_connectors", []),
                    model_requirements=payload.get("model_requirements", {}),
                    memory_requirements=payload.get("memory_requirements", {}),
                    security_requirements=payload.get("security_requirements", {}),
                    evaluation_criteria=payload.get("evaluation_criteria", []),
                    created_by=installed_by,
                )
            )
            ref_type, ref_id = "skill", str(skill.id)
        elif kind in ("MODEL_PRESET", "AGENT_PRESET", "WORKFLOW_PRESET", "MEMORY_PRESET"):
            slug = await _unique_slug(db, Preset, organization_id, resource.slug)
            preset = Preset(
                organization_id=organization_id,
                slug=slug,
                name=resource.name or resource.slug,
                kind=kind,  # type: ignore[arg-type]
                description=str(payload.get("description", "")),
            )
            db.add(preset)
            await db.flush()
            db.add(
                PresetVersion(
                    preset_id=preset.id,
                    version=package_version,
                    payload=payload,
                    created_by=installed_by,
                )
            )
            ref_type, ref_id = "preset", str(preset.id)
        else:
            # PROMPT / TOOL_BUNDLE / CONNECTOR_BUNDLE / AGENT_TEAM /
            # WORKFORCE / AUTOMATION_RECIPE: recorded graph nodes; runtime
            # use resolves through the member agents/workflows/skills above.
            ref_type, ref_id = kind.lower(), ""
        db.add(
            InstallationResource(
                installation_id=installation_id,
                kind=kind,
                slug=resource.slug,
                name=resource.name,
                local_ref_type=ref_type,
                local_ref_id=ref_id,
                snapshot={"payload": payload, "package_version": package_version},
            )
        )
        created.append({"kind": kind, "slug": resource.slug,
                        "local_ref_type": ref_type, "local_ref_id": ref_id})
        await db.flush()
    return created


# ---------------------------------------------------------------------------
# Install / update / rollback
# ---------------------------------------------------------------------------

async def install(
    db: AsyncSession,
    *,
    organization_id: UUID,
    version_id: UUID,
    installed_by=None,
    values: dict[str, Any] | None = None,
    idempotency_key: str = "",
) -> Any:
    """Run the full installation lifecycle synchronously (worker-safe)."""
    from openagent.db.models.package import (
        InstallationResource,
        PackageInstallation,
        PackageResource,
        PackageVersion,
        PackageVersionStatus,
    )

    # Idempotent re-entry: same key returns the existing installation.
    if idempotency_key:
        existing = (
            await db.execute(
                select(PackageInstallation).where(
                    PackageInstallation.organization_id == organization_id,
                    PackageInstallation.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing

    version = await db.get(PackageVersion, version_id)
    if version is None:
        raise InstallationError("VERSION_NOT_FOUND", "package version not found")
    if version.status == PackageVersionStatus.REVOKED:
        raise InstallationError("REVOKED", "package version was revoked")
    if version.status != PackageVersionStatus.PUBLISHED:
        raise InstallationError("NOT_PUBLISHED", "only published versions can be installed")

    installation = PackageInstallation(
        organization_id=organization_id,
        package_id=version.package_id,
        version_id=version.id,
        status=PackageInstallStatus.REQUESTED,
        idempotency_key=idempotency_key or f"install-{uuid.uuid4().hex[:16]}",
        installed_by=installed_by,
    )
    db.add(installation)
    await db.flush()

    try:
        installation.status = PackageInstallStatus.RESOLVING
        await db.flush()
        preview = await preview_install(
            db, organization_id=organization_id, version_id=version.id, values=values or {}
        )
        if preview["dependency_failures"]:
            raise InstallationError(
                "DEPENDENCY_FAILED",
                "; ".join(f["message"] for f in preview["dependency_failures"][:3]),
            )
        if preview["policy_conflicts"]:
            raise InstallationError(
                "POLICY_CONFLICT", "; ".join(preview["policy_conflicts"][:3])
            )
        installation.status = PackageInstallStatus.VALIDATING
        await db.flush()
        report = validation_module.validate_package(dict(version.manifest or {}))
        if not report["passed"]:
            raise InstallationError("VALIDATION_FAILED", "package failed validation")

        schema = (parse_manifest(dict(version.manifest or {})).configuration) or {}
        resolved_values, config_errors = config_schema.validate_configuration(
            schema, values or {}
        )
        if config_errors:
            installation.status = PackageInstallStatus.AWAITING_CONFIGURATION
            installation.error = "; ".join(config_errors[:5])
            await db.flush()
            await telemetry.audit(
                db, organization_id=organization_id, actor_user_id=installed_by,
                action="package.install.awaiting_configuration",
                resource_id=installation.id)
            await db.commit()
            return installation

        installation.status = PackageInstallStatus.INSTALLING
        installation.configuration = resolved_values
        installation.resolved_dependencies = preview["dependencies"]
        await db.flush()
        resources = (
            await db.execute(
                select(PackageResource).where(PackageResource.version_id == version.id)
            )
        ).scalars().all()
        await _materialize(
            db, organization_id=organization_id, installation_id=installation.id,
            package_version=version.version, resources=list(resources),
            installed_by=installed_by,
        )
        installation.status = PackageInstallStatus.VERIFYING
        await db.flush()
        count = (
            await db.execute(
                select(func.count()).where(
                    InstallationResource.installation_id == installation.id
                )
            )
        ).scalar_one()
        if count != len(resources):
            raise InstallationError("VERIFY_FAILED", "installed resource count mismatch")
        installation.status = PackageInstallStatus.INSTALLED
        installation.installed_at = datetime.now(timezone.utc)
        installation.error = ""
        await db.flush()
        telemetry.inc("package_install_total")
        await telemetry.audit(
            db, organization_id=organization_id, actor_user_id=installed_by,
            action="package.install", resource_id=installation.id,
            metadata={"version_id": str(version.id), "configuration": resolved_values})
        await telemetry.emit(
            db, event_type="PACKAGE_INSTALLED", aggregate_id=version.package_id,
            organization_id=organization_id, user_id=installed_by,
            payload={"installation_id": str(installation.id),
                     "version": version.version})
        await db.commit()
    except InstallationError as exc:
        installation.status = PackageInstallStatus.FAILED
        installation.error = str(exc)
        telemetry.inc("package_install_failed_total")
        if exc.code == "DEPENDENCY_FAILED":
            await telemetry.emit(
                db, event_type="DEPENDENCY_RESOLUTION_FAILED",
                aggregate_id=installation.package_id,
                organization_id=organization_id, user_id=installed_by,
                payload={"installation_id": str(installation.id),
                         "error": str(exc)})
        await db.commit()
        raise
    await db.refresh(installation)
    return installation


async def _locked_installation(db: AsyncSession, installation_id: UUID,
                               organization_id: UUID) -> Any:
    """Fetch the installation row with a write lock on Postgres.

    Serializes concurrent update/rollback attempts; on other backends the
    status re-check inside the transaction plus idempotency keys provide
    the safety net.
    """
    from openagent.db.models.package import PackageInstallation

    query = select(PackageInstallation).where(
        PackageInstallation.id == installation_id)
    try:
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            query = query.with_for_update()
    except Exception:
        pass
    installation = (await db.execute(query)).scalar_one_or_none()
    if installation is None or installation.organization_id != organization_id:
        raise InstallationError("NOT_FOUND", "installation not found")
    return installation


async def plan_update(
    db: AsyncSession,
    *,
    installation_id: UUID,
    to_version_id: UUID,
    organization_id: UUID,
) -> Any:
    """Compare versions, build an approved-before-apply update plan."""
    from openagent.db.models.package import (
        InstallationResource,
        PackageInstallation,
        PackageUpdatePlan,
        PackageVersion,
        PackageVersionStatus,
    )
    from openagent.packages.versioning import is_breaking_change

    installation = await db.get(PackageInstallation, installation_id)
    if installation is None or installation.organization_id != organization_id:
        raise InstallationError("NOT_FOUND", "installation not found")
    if installation.status != PackageInstallStatus.INSTALLED:
        raise InstallationError("BAD_STATE", "only installed packages can be updated")
    old = await db.get(PackageVersion, installation.version_id)
    new = await db.get(PackageVersion, to_version_id)
    if new is None or old is None:
        raise InstallationError("VERSION_NOT_FOUND", "version not found")
    if new.package_id != installation.package_id:
        raise InstallationError("MISMATCH", "version belongs to a different package")
    if new.status == PackageVersionStatus.REVOKED:
        raise InstallationError("REVOKED", "target version was revoked")

    dependents = (
        await db.execute(
            select(InstallationResource).where(
                InstallationResource.installation_id == installation.id
            )
        )
    ).scalars().all()
    impact = graph_module.analyze_impact(
        dict(old.manifest or {}),
        dict(new.manifest or {}),
        dependents=[{"kind": r.kind, "slug": r.slug,
                     "local_ref": f"{r.local_ref_type}:{r.local_ref_id}"} for r in dependents],
    )
    breaking = bool(is_breaking_change(old.version, new.version) or impact["breaking"])
    plan = PackageUpdatePlan(
        installation_id=installation.id,
        from_version_id=old.id,
        to_version_id=new.id,
        breaking=breaking,
        impact=impact,
        migration_steps=[
            f"verify {len(dependents)} installed resource(s)",
            "apply new resource snapshots",
            "re-run validation + security scan",
            "keep previous snapshots for rollback",
        ],
        status="PENDING",
    )
    db.add(plan)
    installation.update_available = new.version
    await db.commit()
    await db.refresh(plan)
    return plan


async def apply_update(
    db: AsyncSession,
    *,
    installation_id: UUID,
    organization_id: UUID,
    approved_by=None,
) -> Any:
    """Apply a pending update plan (version snapshots swapped, old kept)."""
    from openagent.db.models.package import (
        InstallationResource,
        PackageInstallation,
        PackageResource,
        PackageUpdatePlan,
        PackageVersion,
        PackageVersionStatus,
    )

    installation = await _locked_installation(db, installation_id, organization_id)
    if installation.status != PackageInstallStatus.INSTALLED:
        raise InstallationError(
            "BAD_STATE", "only installed packages can be updated")
    plan = (
        await db.execute(
            select(PackageUpdatePlan)
            .where(PackageUpdatePlan.installation_id == installation.id,
                   PackageUpdatePlan.status == "PENDING")
            .order_by(PackageUpdatePlan.created_at.desc())
        )
    ).scalars().first()
    if plan is None:
        raise InstallationError("NO_PLAN", "no pending update plan")
    new = await db.get(PackageVersion, plan.to_version_id)
    if new is None or new.status == PackageVersionStatus.REVOKED:
        raise InstallationError("REVOKED", "target version unavailable")

    installation.status = PackageInstallStatus.UPDATING
    await db.flush()
    try:
        new_resources = {
            (r.kind.upper(), r.slug): r
            for r in (
                await db.execute(
                    select(PackageResource).where(PackageResource.version_id == new.id)
                )
            ).scalars().all()
        }
        current = (
            await db.execute(
                select(InstallationResource).where(
                    InstallationResource.installation_id == installation.id
                )
            )
        ).scalars().all()
        for record in current:
            match = new_resources.get((record.kind, record.slug))
            payload = dict(match.payload or {}) if match is not None else None
            previous = dict(record.snapshot or {})
            if payload is None:
                record.snapshot = {**previous, "removed_in": new.version}
                continue
            # Swap the live local version row; previous snapshot retained.
            if record.local_ref_type == "agent" and record.local_ref_id:
                await _upsert_agent_version(
                    db, agent_id=UUID(record.local_ref_id), version=new.version,
                    name=record.name,
                    instructions=str(payload.get("system_prompt", "")) or None,
                    configuration={"model_preset": payload.get("model_preset", ""),
                                   "skills": payload.get("skills", [])},
                    created_by=approved_by)
            elif record.local_ref_type == "workflow" and record.local_ref_id:
                await _upsert_workflow_version(
                    db, workflow_id=UUID(record.local_ref_id), version=new.version,
                    definition=payload, created_by=approved_by)
            elif record.local_ref_type == "skill" and record.local_ref_id:
                await _upsert_skill_version(
                    db, skill_id=UUID(record.local_ref_id), version=new.version,
                    payload=payload, created_by=approved_by)
            record.snapshot = {"payload": payload, "package_version": new.version,
                               "previous": previous}
        installation.previous_version_id = installation.version_id
        installation.version_id = new.id
        installation.status = PackageInstallStatus.INSTALLED
        installation.update_available = ""
        plan.status = "APPLIED"
        plan.approved_by = approved_by
        await db.flush()
        telemetry.inc("package_update_total")
        await telemetry.audit(
            db, organization_id=organization_id, actor_user_id=approved_by,
            action="package.update", resource_id=installation.id,
            metadata={"from": str(plan.from_version_id), "to": str(plan.to_version_id)})
        await telemetry.emit(
            db, event_type="PACKAGE_UPDATED", aggregate_id=installation.package_id,
            organization_id=organization_id, user_id=approved_by,
            payload={"installation_id": str(installation.id)})
        await db.commit()
    except Exception as exc:
        await db.rollback()
        installation = await db.get(PackageInstallation, installation_id)
        if installation is not None:
            installation.status = PackageInstallStatus.FAILED
            installation.error = f"update failed: {exc}"
            await db.commit()
        raise InstallationError("UPDATE_FAILED", f"update failed: {exc}") from exc
    await db.refresh(installation)
    return installation


async def rollback(
    db: AsyncSession,
    *,
    installation_id: UUID,
    organization_id: UUID,
    actor=None,
) -> Any:
    """Restore the previous valid version using retained snapshots."""
    from openagent.db.models.package import (
        InstallationResource,
        PackageInstallation,
        PackageVersion,
    )

    installation = await _locked_installation(db, installation_id, organization_id)
    if not installation.previous_version_id:
        raise InstallationError("NO_ROLLBACK", "no previous version retained")
    previous = await db.get(PackageVersion, installation.previous_version_id)
    if previous is None:
        raise InstallationError("VERSION_NOT_FOUND", "previous version no longer exists")

    installation.status = PackageInstallStatus.ROLLING_BACK
    await db.flush()
    try:
        current = (
            await db.execute(
                select(InstallationResource).where(
                    InstallationResource.installation_id == installation.id
                )
            )
        ).scalars().all()
        for record in current:
            snapshot = dict(record.snapshot or {})
            prior = snapshot.get("previous")
            if not isinstance(prior, dict) or "payload" not in prior:
                continue
            payload = prior["payload"]
            if record.local_ref_type == "agent" and record.local_ref_id:
                await _upsert_agent_version(
                    db, agent_id=UUID(record.local_ref_id),
                    version=previous.version, name=record.name,
                    instructions=str(payload.get("system_prompt", "")) or None,
                    configuration={"model_preset": payload.get("model_preset", ""),
                                   "skills": payload.get("skills", [])},
                    created_by=actor)
            elif record.local_ref_type == "workflow" and record.local_ref_id:
                await _upsert_workflow_version(
                    db, workflow_id=UUID(record.local_ref_id),
                    version=previous.version, definition=payload,
                    created_by=actor)
            elif record.local_ref_type == "skill" and record.local_ref_id:
                await _upsert_skill_version(
                    db, skill_id=UUID(record.local_ref_id),
                    version=previous.version, payload=payload,
                    created_by=actor)
            record.snapshot = prior
        installation.version_id = previous.id
        installation.previous_version_id = None
        installation.update_available = ""
        installation.status = PackageInstallStatus.ROLLED_BACK
        await db.flush()
        # ROLLED_BACK is terminal-for-rollback but the install is usable;
        # mark INSTALLED so further updates remain possible.
        installation.status = PackageInstallStatus.INSTALLED
        telemetry.inc("package_rollback_total")
        await telemetry.audit(
            db, organization_id=organization_id, actor_user_id=actor,
            action="package.rollback", resource_id=installation.id,
            metadata={"restored_version": previous.version})
        await telemetry.emit(
            db, event_type="PACKAGE_ROLLED_BACK", aggregate_id=installation.package_id,
            organization_id=organization_id, user_id=actor,
            payload={"installation_id": str(installation.id),
                     "restored_version": previous.version})
        await db.commit()
    except Exception as exc:
        await db.rollback()
        installation = await db.get(PackageInstallation, installation_id)
        if installation is not None:
            installation.status = PackageInstallStatus.FAILED
            installation.error = f"rollback failed: {exc}"
            await db.commit()
        raise InstallationError("ROLLBACK_FAILED", f"rollback failed: {exc}") from exc
    await db.refresh(installation)
    return installation
