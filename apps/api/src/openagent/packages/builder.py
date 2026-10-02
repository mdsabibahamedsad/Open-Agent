"""MP22: programmatic package builders (Python SDK surface).

Complements the TypeScript SDK (``@openagent/sdk`` ``packages`` namespace)
for server-side / CLI package authoring::

    from openagent.packages.builder import (
        PackageDefinition, SkillDefinition, PresetDefinition,
        TemplateDefinition, Dependency,
    )

    pkg = (
        PackageDefinition(id="acme.research", name="Research", version="1.0.0")
        .describe("Manager-led research team")
        .licensed("Apache-2.0")
        .depends_on(Dependency(type="tool", package="browser-search", version="^1.0.0"))
        .skill(SkillDefinition(slug="web-research", name="Web Research",
                               instructions="Cross-check two sources."))
        .agent("research-manager", "Research Manager",
               system_prompt="Coordinate research workers.")
        .configure({"topic": {"type": "text", "required": True}})
        .require_approval("publish_content")
    )
    manifest = pkg.build()          # validated manifest dict
    files = pkg.export_files()      # portable bundle file map
    report = pkg.validate()         # validation report
"""

from __future__ import annotations

from typing import Any


class Dependency:
    def __init__(self, type: str, package: str, version: str = "*",
                 optional: bool = False, peer: bool = False):
        self.type = type
        self.package = package
        self.version = version
        self.optional = optional
        self.peer = peer

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "package": self.package,
                "version": self.version, "optional": self.optional,
                "peer": self.peer}


class SkillDefinition:
    def __init__(self, slug: str, name: str, instructions: str = "",
                 description: str = ""):
        self.slug = slug
        self.name = name
        self.instructions = instructions
        self.description = description
        self.input_schema: dict[str, Any] = {"type": "object"}
        self.output_schema: dict[str, Any] = {"type": "object"}
        self.required_tools: list[str] = []
        self.required_connectors: list[str] = []
        self.evaluation_criteria: list[str] = []

    def to_resource(self) -> dict[str, Any]:
        return {
            "kind": "SKILL", "slug": self.slug, "name": self.name,
            "payload": {
                "description": self.description,
                "instructions": self.instructions,
                "input_schema": self.input_schema,
                "output_schema": self.output_schema,
                "required_tools": self.required_tools,
                "required_connectors": self.required_connectors,
                "evaluation_criteria": self.evaluation_criteria,
            },
        }


class PresetDefinition:
    def __init__(self, kind: str, slug: str, name: str,
                 payload: dict[str, Any] | None = None):
        self.kind = kind
        self.slug = slug
        self.name = name
        self.payload = payload or {}

    def to_resource(self) -> dict[str, Any]:
        return {"kind": self.kind, "slug": self.slug, "name": self.name,
                "payload": self.payload}


class TemplateDefinition:
    """Thin alias for composing nested templates (workforce of agents)."""

    def __init__(self, kind: str, slug: str, name: str,
                 payload: dict[str, Any] | None = None):
        self.kind = kind
        self.slug = slug
        self.name = name
        self.payload = payload or {}

    def to_resource(self) -> dict[str, Any]:
        return {"kind": self.kind, "slug": self.slug, "name": self.name,
                "payload": self.payload}


class PackageDefinition:
    """Fluent builder producing validated manifest dicts."""

    def __init__(self, id: str, name: str, version: str = "1.0.0",
                 type: str = "TEMPLATE_PACKAGE"):
        self._id = id
        self._name = name
        self._version = version
        self._type = type
        self._description = ""
        self._license = "Apache-2.0"
        self._visibility = "ORGANIZATION"
        self._categories: list[str] = []
        self._tags: list[str] = []
        self._dependencies: list[Dependency] = []
        self._resources: list[dict[str, Any]] = []
        self._inputs: dict[str, Any] = {}
        self._approvals: list[str] = []
        self._evaluation: dict[str, Any] = {}
        self._author = {"name": "unknown", "email": "", "url": ""}
        self._compatibility: dict[str, Any] = {"openagent_version": ">=0.1.0",
                                               "api_version": "v1"}
        self._changelog = ""

    def describe(self, description: str) -> "PackageDefinition":
        self._description = description
        return self

    def licensed(self, license: str) -> "PackageDefinition":
        self._license = license
        return self

    def authored_by(self, name: str, email: str = "", url: str = "") -> "PackageDefinition":
        self._author = {"name": name, "email": email, "url": url}
        return self

    def categorized(self, *categories: str) -> "PackageDefinition":
        self._categories.extend(categories)
        return self

    def tagged(self, *tags: str) -> "PackageDefinition":
        self._tags.extend(tags)
        return self

    def depends_on(self, dep: Dependency) -> "PackageDefinition":
        self._dependencies.append(dep)
        return self

    def skill(self, skill: SkillDefinition) -> "PackageDefinition":
        self._resources.append(skill.to_resource())
        return self

    def preset(self, preset: PresetDefinition) -> "PackageDefinition":
        self._resources.append(preset.to_resource())
        return self

    def agent(self, slug: str, name: str, system_prompt: str = "",
              **payload: Any) -> "PackageDefinition":
        self._resources.append({
            "kind": "AGENT", "slug": slug, "name": name,
            "payload": {"system_prompt": system_prompt, **payload},
        })
        return self

    def workflow(self, slug: str, name: str, **payload: Any) -> "PackageDefinition":
        self._resources.append({
            "kind": "WORKFLOW", "slug": slug, "name": name, "payload": payload,
        })
        return self

    def template(self, template: TemplateDefinition) -> "PackageDefinition":
        self._resources.append(template.to_resource())
        return self

    def configure(self, inputs: dict[str, Any]) -> "PackageDefinition":
        self._inputs.update(inputs)
        return self

    def require_approval(self, *actions: str) -> "PackageDefinition":
        self._approvals.extend(actions)
        return self

    def evaluate_with(self, criteria: dict[str, Any]) -> "PackageDefinition":
        self._evaluation.update(criteria)
        return self

    def changelog(self, text: str) -> "PackageDefinition":
        self._changelog = text
        return self

    def build(self) -> dict[str, Any]:
        """Return the manifest dict (structurally validated)."""
        from openagent.packages.manifest import parse_manifest

        manifest = {
            "format": "openagent-package",
            "format_version": "1",
            "package": {"id": self._id, "name": self._name,
                        "version": self._version, "type": self._type},
            "author": self._author,
            "license": self._license,
            "visibility": self._visibility,
            "description": self._description,
            "categories": self._categories,
            "tags": self._tags,
            "dependencies": [d.to_dict() for d in self._dependencies],
            "resources": self._resources,
            "configuration": {"inputs": self._inputs},
            "security": {"required_approvals": self._approvals,
                         "network": "restricted"},
            "compatibility": self._compatibility,
            "evaluation": self._evaluation,
            "changelog": self._changelog,
        }
        parse_manifest(manifest)  # raise on structural errors
        return manifest

    def validate(self) -> dict[str, Any]:
        from openagent.packages import validation as validation_module

        return validation_module.validate_package(self.build())

    def export_files(self) -> dict[str, str]:
        from openagent.packages import packaging as packaging_module

        return packaging_module.build_export_files(self.build())

    # Backwards-compatible alias for the MP22 SDK sketch.
    def export(self) -> dict[str, str]:
        return self.export_files()


class PackageVersion:
    """Value object pairing a built manifest with its content hash."""

    def __init__(self, manifest: dict[str, Any]):
        from openagent.packages.signing import content_hash

        self.manifest = manifest
        self.content_hash = content_hash(manifest)

    @property
    def version(self) -> str:
        return str(self.manifest["package"]["version"])

    def verify(self) -> bool:
        from openagent.packages.signing import verify_content_hash

        return verify_content_hash(self.manifest, self.content_hash)


class PackageValidator:
    """Programmatic validation entry-point (mirrors the API behavior)."""

    def validate(self, manifest: dict[str, Any]) -> dict[str, Any]:
        from openagent.packages import validation as validation_module

        return validation_module.validate_package(manifest)


class PackageExporter:
    def export(self, manifest: dict[str, Any]) -> dict[str, str]:
        from openagent.packages import packaging as packaging_module

        return packaging_module.build_export_files(manifest)


class PackageImporter:
    def parse(self, files: dict[str, str]) -> dict[str, Any]:
        from openagent.packages import packaging as packaging_module

        return packaging_module.parse_import_files(files)

    def preview(self, files: dict[str, str]) -> dict[str, Any]:
        from openagent.packages import packaging as packaging_module

        return packaging_module.import_preview(files)


class PackageInstaller:
    """Thin async facade over the installer service (needs a session)."""

    def __init__(self, db):
        self._db = db

    async def preview(self, **kwargs: Any) -> dict[str, Any]:
        from openagent.packages import installer as installer_module

        return await installer_module.preview_install(self._db, **kwargs)

    async def install(self, **kwargs: Any) -> Any:
        from openagent.packages import installer as installer_module

        return await installer_module.install(self._db, **kwargs)

    async def plan_update(self, **kwargs: Any) -> Any:
        from openagent.packages import installer as installer_module

        return await installer_module.plan_update(self._db, **kwargs)

    async def apply_update(self, **kwargs: Any) -> Any:
        from openagent.packages import installer as installer_module

        return await installer_module.apply_update(self._db, **kwargs)

    async def rollback(self, **kwargs: Any) -> Any:
        from openagent.packages import installer as installer_module

        return await installer_module.rollback(self._db, **kwargs)
