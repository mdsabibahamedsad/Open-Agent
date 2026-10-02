"""Code domain service: repositories, workspaces, tasks, intelligence, patches.

Persistence is database-backed (PostgreSQL via SQLAlchemy). Git transport goes
through the confined ``GitRunner``; arbitrary repo code executes only through
the ``CodeExecutionProvider`` boundary (profile-allowlisted today, MP18
sandbox transport tomorrow). This service owns tenancy, policy, risk, audit,
and the task state machine.
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import secrets
import shlex
import stat
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openagent.code import intelligence as intel
from openagent.code.git import GitRunner, GitSecurityError
from openagent.code.patches import (
    ChangeRecord,
    PatchError,
    apply_patch,
    generate_diff,
    parse_unified_diff,
    validate_patch,
)
from openagent.code.providers import (
    GitAuth,
    RepositoryInfo,
    create_provider,
)
from openagent.code.review import ReviewResult, gate_summary, review_diff, review_text
from openagent.code.security import (
    EXECUTION_PROFILES,
    command_allowed_by_profile,
    detect_repo_injection,
    filter_repo_instructions,
    is_protected_branch,
    is_retry_safe_tool,
    is_sensitive_filename,
    label_untrusted_code,
    redact_dict,
    redact_text,
    resolve_profile,
    scan_text_for_secrets,
    task_branch_name,
    tool_requires_approval,
    validate_workspace_path,
)
from openagent.db.models.audit_log import AuditLog
from openagent.db.models.code import (
    CodeChunk,
    CodeCommit,
    CodeDependency,
    CodeEmbedding,
    CodeEvent,
    CodeExecutionRun,
    CodeFileIndex,
    CodeIndexJob,
    CodePatch,
    CodePullRequest,
    CodeReference,
    CodeReview,
    CodeReviewFinding,
    CodeSymbol,
    CodeTaskStep,
    CodeTestResult,
    CodeWorkspace,
    CodingTask,
    CodingTaskStatus,
    ExecutionStatus,
    PatchStatus,
    PRStatus,
    Repository,
    ReviewSeverity,
    ReviewStatus,
    TaskRiskLevel,
    WorkspaceStatus,
)

logger = structlog.get_logger("code.service")


# Code.* event type -> Prometheus-style metric counters (§82 observability).
# Recorded on top of the persisted CodeEvent; metrics failures never break
# the task flow.
_CODE_EVENT_METRICS: dict[str, str] = {
    "code.task.started": "code_tasks_total",
    "code.task.planning": "code_tasks_total",
    "code.task.completed": "code_tasks_success",
    "code.search.completed": "code_search_total",
    "code.patch.proposed": "code_patches_total",
    "code.patch.applied": "code_patches_applied",
    "code.test.started": "code_test_runs_total",
    "code.test.completed": "code_test_runs_total",
    "code.review.started": "code_reviews_total",
    "code.review.completed": "code_reviews_total",
    "code.commit.created": "commit_count",
    "code.pr.created": "pr_count",
    "repository.connected": "repository_connections_total",
    "workspace.created": "code_workspaces_total",
}


def _record_code_metric(etype: str, payload: Optional[dict] = None) -> None:
    """Best-effort counter for §82 observability (never raises).

    The shared collector is imported lazily: ``openagent.core.metrics``
    pulls optional heavy deps, so metrics must never break task flow.
    """
    try:
        from openagent.core.metrics import metrics as _metrics
    except Exception:
        return
    try:
        name = _CODE_EVENT_METRICS.get(etype)
        if name is None:
            return
        labels: dict[str, str] = {}
        status = (payload or {}).get("status")
        if isinstance(status, str) and status:
            labels["status"] = status
        _metrics.counter(name, 1.0, labels or None,
                         help_text=f"OpenAgent code agent metric {name}")
        if etype in ("code.task.completed",) and status == "FAILED":
            _metrics.counter("code_tasks_failed", 1.0, None,
                             help_text="OpenAgent code agent metric code_tasks_failed")
    except Exception:
        logger.warning("code_metrics_skipped", event=etype)


class CodeSecurityError(Exception):
    pass


class CodePolicyDenied(CodeSecurityError):
    pass


class CodeNotFound(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _eid(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}_{uuid.uuid4().hex[:8]}"


def workspace_root() -> Path:
    root = Path(os.environ.get("OPENAGENT_WORKSPACE_ROOT", "./workspaces")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


# --------------------------------------------------------------------------
# Execution boundary (pre-sandbox confined runner; MP18 swaps the transport)
# --------------------------------------------------------------------------

class ExecutionOutcome:
    def __init__(self, exit_code: int, stdout: str, stderr: str,
                 duration_ms: int, timed_out: bool = False):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.duration_ms = duration_ms
        self.timed_out = timed_out


class CodeExecutionProvider:
    """Boundary for running repo commands. Agent code never touches subprocess."""

    async def execute(self, *, command: str, cwd: str, profile: str,
                      timeout_seconds: Optional[int] = None) -> ExecutionOutcome:
        raise NotImplementedError


class LocalConfinedExecutionProvider(CodeExecutionProvider):
    """Profile-allowlisted local execution with jail, timeout, output caps.

    This is the pre-sandbox implementation: no shell, argv-only, workspace
    jail, sanitized env, network/repo code treated as hostile. MP18 replaces
    this class with the container sandbox behind the same interface.
    """

    def __init__(self, root: str, max_output_bytes: int = 1_000_000):
        self.root = Path(root).resolve()
        self.max_output = max_output_bytes

    async def execute(self, *, command: str, cwd: str, profile: str,
                      timeout_seconds: Optional[int] = None) -> ExecutionOutcome:
        from openagent.code.security import EXECUTION_PROFILES  # noqa: F401 (re-export anchor)
        prof = resolve_profile(profile)
        if not command_allowed_by_profile(command, prof):
            raise CodePolicyDenied(
                f"Command not allowed by execution profile '{prof.name}': "
                f"{redact_text(command)[:200]}")
        target = (Path(cwd)).resolve()
        try:
            target.relative_to(self.root)
        except ValueError:
            raise CodeSecurityError("Execution cwd escapes the workspace root")
        if any(tok in command for tok in (";", "&&", "||", "`", "$(", "|", ">", "<", "\n")):
            raise CodePolicyDenied("Shell operators are not allowed (argv commands only)")
        try:
            argv = shlex.split(command, posix=True)
        except ValueError as e:
            raise CodePolicyDenied(f"Cannot parse command: {e}")
        if not argv:
            raise CodePolicyDenied("Empty command")
        env = {"PATH": os.environ.get("PATH", ""),
               "HOME": os.environ.get("HOME", ""),
               "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
               "LC_ALL": "C", "CI": "true", "TERM": "dumb",
               "GIT_TERMINAL_PROMPT": "0"}
        timeout = timeout_seconds or prof.timeout_seconds
        started = _now()
        try:
            proc = await asyncio.create_subprocess_exec(
                argv[0], *argv[1:], cwd=str(target), env=env,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError:
            raise CodeSecurityError(f"Executable not found: {argv[0]}")
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            timed_out = False
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            out, err = await proc.communicate()
            timed_out = True
        duration_ms = int((_now() - started).total_seconds() * 1000)
        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        if len(stdout) > self.max_output:
            stdout = stdout[:self.max_output] + "\n... [truncated]"
        if len(stderr) > self.max_output:
            stderr = stderr[:self.max_output] + "\n... [truncated]"
        return ExecutionOutcome(exit_code=-1 if timed_out else (proc.returncode or 0),
                                stdout=stdout, stderr=stderr,
                                duration_ms=duration_ms, timed_out=timed_out)


# --------------------------------------------------------------------------
# Test output parsing (best-effort, multi-runner)
# --------------------------------------------------------------------------

def parse_test_output(command: str, exit_code: int, tail: str) -> dict[str, Any]:
    """Extract {passed, failed, skipped, failures[]} from common runners."""
    import re
    passed = failed = skipped = 0
    failures: list[dict[str, Any]] = []
    m = re.search(r"(\d+)\s+failed,\s*(\d+)\s+passed", tail)
    if m:
        failed, passed = int(m.group(1)), int(m.group(2))
        ms = re.search(r"(\d+)\s+skipped", tail)
        if ms:
            skipped = int(ms.group(1))
    elif (m := re.search(r"(\d+)\s+passed(?:,\s*(\d+)\s+skipped)?", tail)):
        passed = int(m.group(1))
        skipped = int(m.group(2)) if m.group(2) else 0
        if exit_code != 0 and failed == 0:
            failed = 1
    elif "OK" in tail and re.search(r"Ran \d+ tests?", tail):
        m2 = re.search(r"Ran (\d+) tests?", tail)
        passed = int(m2.group(1)) if m2 else 0
        if exit_code != 0:
            failed, passed = passed, 0
    elif (m := re.search(r"test result:\s*ok\.\s*(\d+)\s+passed", tail)):
        passed = int(m.group(1))
    elif (m := re.search(r"test result:\s*FAILED\.\s*(\d+)\s+passed.\s*(\d+)\s+failed", tail)):
        passed, failed = int(m.group(1)), int(m.group(2))
    for line in tail.splitlines():
        mm = re.match(r"FAILED\s+(\S+)\s*-?\s*(.*)", line)
        if mm and len(failures) < 200:
            failures.append({"name": mm.group(1), "message": mm.group(2)[:500]})
        elif (mm := re.match(r"--- FAIL:\s+(\S+)", line)) and len(failures) < 200:
            failures.append({"name": mm.group(1), "message": ""})
    if exit_code != 0 and passed == 0 and failed == 0:
        failed = 1
    return {"passed": passed, "failed": failed, "skipped": skipped,
            "failures": failures}


# --------------------------------------------------------------------------
# Dependency manifest parsing
# --------------------------------------------------------------------------

def parse_dependencies(repo_root: Path, rel: str, content: str) -> list[dict[str, Any]]:
    """Extract dependency edges from common manifests (best-effort)."""
    import json
    import re
    deps: list[dict[str, Any]] = []
    base = rel.split("/")[-1].lower()
    try:
        if base == "package.json":
            data = json.loads(content)
            for scope in ("dependencies", "devDependencies", "peerDependencies"):
                for name, spec in (data.get(scope) or {}).items():
                    deps.append({"file": rel, "manager": "npm", "name": name,
                                 "version_spec": str(spec),
                                 "scope": "dev" if scope == "devDependencies" else "runtime"})
        elif base in ("requirements.txt", "requirements-dev.txt", "requirements.lock"):
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-")):
                    continue
                m = re.match(r"^([A-Za-z0-9_.\-]+)\s*([=<>!~]+.*)?$", line)
                if m:
                    deps.append({"file": rel, "manager": "pip", "name": m.group(1),
                                 "version_spec": (m.group(2) or "").strip(),
                                 "scope": "dev" if "dev" in base else "runtime"})
        elif base == "pyproject.toml":
            in_deps = False
            for line in content.splitlines():
                if re.match(r"^\s*dependencies\s*=", line):
                    in_deps = True
                    m = re.search(r"\[(.*)\]", line)
                    items = m.group(1) if m else ""
                    for item in re.findall(r"['\"]([^'\"]+)['\"]", items):
                        mm = re.match(r"^([A-Za-z0-9_.\-]+)\s*(.*)$", item.strip())
                        if mm:
                            deps.append({"file": rel, "manager": "pip", "name": mm.group(1),
                                         "version_spec": mm.group(2).strip(), "scope": "runtime"})
                    in_deps = False
        elif base == "go.mod":
            in_req = False
            for line in content.splitlines():
                s = line.strip()
                if s.startswith("require ("):
                    in_req = True
                    continue
                if in_req and s == ")":
                    in_req = False
                    continue
                m = re.match(r"^require\s+(\S+)\s+(\S+)", s)
                if m:
                    deps.append({"file": rel, "manager": "go", "name": m.group(1),
                                 "version_spec": m.group(2), "scope": "runtime"})
                    continue
                if in_req:
                    m = re.match(r"^(\S+)\s+(\S+)", s)
                    if m:
                        deps.append({"file": rel, "manager": "go", "name": m.group(1),
                                     "version_spec": m.group(2), "scope": "runtime"})
        elif base == "cargo.toml":
            section = ""
            for line in content.splitlines():
                s = line.strip()
                if s.startswith("["):
                    section = s
                    continue
                if "dependencies" in section:
                    m = re.match(r"^([A-Za-z0-9_\-]+)\s*=\s*(.+)$", s)
                    if m:
                        deps.append({"file": rel, "manager": "cargo", "name": m.group(1),
                                     "version_spec": m.group(2).strip().strip('"'),
                                     "scope": "dev" if "dev-dependencies" in section else "runtime"})
        elif base.endswith(".csproj"):
            for m in re.finditer(r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"',
                                 content):
                deps.append({"file": rel, "manager": "dotnet", "name": m.group(1),
                             "version_spec": m.group(2), "scope": "runtime"})
    except (ValueError, AttributeError):
        pass
    return deps


MANIFEST_BASENAMES = {"package.json", "requirements.txt", "requirements-dev.txt",
                      "requirements.lock", "pyproject.toml", "go.mod", "cargo.toml",
                      "go.sum", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
                      "poetry.lock", "pdm.lock"}


def discover_test_commands(repo_root: Path) -> list[dict[str, str]]:
    """Heuristic test/lint/typecheck/build command discovery from repo config."""
    found: list[dict[str, str]] = []
    pkg = repo_root / "package.json"
    if pkg.is_file():
        try:
            import json
            scripts = json.loads(pkg.read_text(
                encoding="utf-8", errors="replace")).get("scripts", {})
            for name, profile in (("test", "TEST"), ("lint", "LINT"),
                                  ("typecheck", "TYPECHECK"), ("build", "BUILD")):
                if name in scripts:
                    mgr = "pnpm" if (repo_root / "pnpm-lock.yaml").exists() \
                        else ("yarn" if (repo_root / "yarn.lock").exists() else "npm")
                    found.append({"profile": profile, "command": f"{mgr} run {name}",
                                  "source": "package.json"})
        except (OSError, ValueError):
            pass
    if (repo_root / "pyproject.toml").is_file() or (repo_root / "pytest.ini").is_file() \
            or (repo_root / "tox.ini").is_file() or (repo_root / "setup.cfg").is_file():
        found.append({"profile": "TEST", "command": "pytest -q", "source": "python-config"})
    if (repo_root / "pyproject.toml").is_file():
        found.append({"profile": "LINT", "command": "ruff check .", "source": "pyproject.toml"})
    if (repo_root / "go.mod").is_file():
        found.append({"profile": "TEST", "command": "go test ./...", "source": "go.mod"})
    if (repo_root / "Cargo.toml").is_file():
        found.append({"profile": "TEST", "command": "cargo test", "source": "Cargo.toml"})
    if (repo_root / "Makefile").is_file():
        try:
            text = (repo_root / "Makefile").read_text(encoding="utf-8", errors="replace")
            import re
            for target in re.findall(r"^([a-z][a-z0-9_-]*)\s*:", text, re.M):
                if target in ("test", "lint", "build", "check", "vet"):
                    prof = {"test": "TEST", "lint": "LINT", "build": "BUILD"}.get(
                        target, "TEST")
                    found.append({"profile": prof, "command": f"make {target}",
                                  "source": "Makefile"})
        except OSError:
            pass
    seen: set[tuple[str, str]] = set()
    unique = []
    for f in found:
        key = (f["profile"], f["command"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class CodeSecurityError(Exception):
    pass


class CodePolicyDenied(CodeSecurityError):
    pass


class CodeNotFound(Exception):
    pass


def _target(fp: Any) -> str:
    if fp.is_delete:
        return fp.old_path
    return fp.new_path


TASK_TRANSITIONS: dict[CodingTaskStatus, set[CodingTaskStatus]] = {
    CodingTaskStatus.QUEUED: {CodingTaskStatus.INITIALIZING, CodingTaskStatus.CANCELLED},
    CodingTaskStatus.INITIALIZING: {CodingTaskStatus.ANALYZING, CodingTaskStatus.FAILED,
                                    CodingTaskStatus.CANCELLED},
    CodingTaskStatus.ANALYZING: {CodingTaskStatus.PLANNING, CodingTaskStatus.FAILED,
                                 CodingTaskStatus.CANCELLED},
    CodingTaskStatus.PLANNING: {CodingTaskStatus.EDITING, CodingTaskStatus.FAILED,
                                CodingTaskStatus.CANCELLED},
    CodingTaskStatus.EDITING: {CodingTaskStatus.VALIDATING, CodingTaskStatus.FAILED,
                               CodingTaskStatus.CANCELLED, CodingTaskStatus.TIMED_OUT},
    CodingTaskStatus.VALIDATING: {CodingTaskStatus.TESTING, CodingTaskStatus.EDITING,
                                  CodingTaskStatus.FAILED, CodingTaskStatus.CANCELLED},
    CodingTaskStatus.TESTING: {CodingTaskStatus.REVIEWING, CodingTaskStatus.EDITING,
                               CodingTaskStatus.FAILED, CodingTaskStatus.CANCELLED,
                               CodingTaskStatus.TIMED_OUT},
    CodingTaskStatus.REVIEWING: {CodingTaskStatus.WAITING_FOR_APPROVAL,
                                 CodingTaskStatus.COMMITTING, CodingTaskStatus.EDITING,
                                 CodingTaskStatus.FAILED, CodingTaskStatus.CANCELLED},
    CodingTaskStatus.WAITING_FOR_APPROVAL: {CodingTaskStatus.COMMITTING,
                                            CodingTaskStatus.EDITING,
                                            CodingTaskStatus.CANCELLED},
    CodingTaskStatus.COMMITTING: {CodingTaskStatus.READY_FOR_PR, CodingTaskStatus.FAILED,
                                  CodingTaskStatus.CANCELLED},
    CodingTaskStatus.READY_FOR_PR: {CodingTaskStatus.SUCCEEDED, CodingTaskStatus.FAILED,
                                    CodingTaskStatus.CANCELLED},
    CodingTaskStatus.SUCCEEDED: set(),
    CodingTaskStatus.FAILED: set(),
    CodingTaskStatus.CANCELLED: set(),
    CodingTaskStatus.TIMED_OUT: set(),
}


class CodeService:
    """Tenant-scoped code orchestration. All methods enforce organization_id."""

    def __init__(self, db: AsyncSession,
                 credential_resolver: Any = None,
                 semantic_provider: Any = None,
                 execution_provider: Optional[CodeExecutionProvider] = None,
                 storage: Any = None):
        self.db = db
        self._credential_resolver = credential_resolver
        self._semantic = semantic_provider
        self._exec = execution_provider
        self._storage = storage
        self._root = workspace_root()
        self._runner = GitRunner(str(self._root))

    # -- internal helpers -------------------------------------------------
    def _execution_provider(self, organization_id=None, task_id=None,
                            actor=None) -> CodeExecutionProvider:
        """Resolve the execution transport (MP18: sandbox-backed by default).

        Production executes repository commands ONLY inside the Sandbox
        (Docker provider). The legacy host-confined runner survives solely as
        an explicit dev-only fallback (``SANDBOX_PROVIDER=local`` +
        non-production + ``SANDBOX_ALLOW_LOCAL_FALLBACK=true``); anything
        else fails closed. Adapters are cached per organization so task
        sandboxes are reused across a task's run/test/review loop.
        """
        if self._exec is not None:
            return self._exec
        from openagent.sandbox.config import is_production, load_settings
        try:
            settings = load_settings()
        except ValueError as e:
            raise CodePolicyDenied(
                f"Sandbox configuration invalid; execution refused: {e}")
        if settings.provider == "local":
            if is_production() or not settings.allow_local_fallback:
                raise CodePolicyDenied(
                    "Local execution fallback is not permitted here "
                    "(production or SANDBOX_ALLOW_LOCAL_FALLBACK=false)")
            logger.warning("code_local_exec_fallback",
                           detail="NOT a security boundary; dev-only")
            self._exec = LocalConfinedExecutionProvider(str(self._root))
            return self._exec
        if organization_id is None:
            raise CodePolicyDenied("Sandbox execution requires organization context")
        if not hasattr(self, "_sandbox_adapters"):
            self._sandbox_adapters: dict[Any, Any] = {}
        key = (str(organization_id), str(task_id) if task_id else "")
        adapter = self._sandbox_adapters.get(key)
        if adapter is None:
            from openagent.sandbox.code_adapter import SandboxCodeExecutionProvider

            def _manager_factory(db=self.db,
                                 resolver=self._credential_resolver):
                from openagent.sandbox.service import SandboxManager
                return SandboxManager(db, credential_resolver=resolver)

            adapter = SandboxCodeExecutionProvider(
                _manager_factory, organization_id,
                task_id=task_id, actor=actor)
            self._sandbox_adapters[key] = adapter
        return adapter

    def _semantic_provider(self) -> Any:
        from openagent.code.intelligence import NoopSemanticProvider
        return self._semantic or NoopSemanticProvider()

    async def _emit(self, organization_id: UUID, etype: str, *,
                    task_id: Optional[UUID] = None,
                    workspace_id: Optional[UUID] = None,
                    payload: Optional[dict] = None) -> CodeEvent:
        ev = CodeEvent(
            event_id=_eid("evt"), type=etype, organization_id=organization_id,
            task_id=task_id, workspace_id=workspace_id,
            payload=redact_dict(payload or {}), meta={}, timestamp=_now())
        self.db.add(ev)
        await self.db.flush()
        _record_code_metric(etype, ev.payload)
        return ev

    async def _audit(self, organization_id: UUID, actor: Optional[UUID], action: str,
                     resource: str, resource_id: Optional[UUID],
                     meta: Optional[dict] = None) -> None:
        self.db.add(AuditLog(
            organization_id=organization_id, actor_user_id=actor, action=action,
            resource_type=resource, resource_id=resource_id,
            metadata=redact_dict(meta or {})))
        await self.db.flush()

    async def _step(self, task: CodingTask, kind: str, status: str,
                    input_summary: Optional[dict] = None,
                    output_summary: Optional[dict] = None) -> CodeTaskStep:
        existing = await self.db.scalar(
            select(func.count()).select_from(CodeTaskStep).where(
                CodeTaskStep.task_id == task.id))
        step = CodeTaskStep(
            task_id=task.id, step_no=(existing or 0) + 1, kind=kind, status=status,
            input_summary=redact_dict(input_summary or {}),
            output_summary=redact_dict(output_summary or {}),
            started_at=_now(), completed_at=_now(), created_at=_now())
        self.db.add(step)
        task.current_step = step.step_no
        await self.db.flush()
        return step

    def _check_budgets(self, task: CodingTask) -> None:
        budgets = task.budgets or {}
        max_steps = int(budgets.get("max_steps", task.max_steps or 50))
        if task.current_step >= max_steps:
            task.status = CodingTaskStatus.TIMED_OUT
            raise CodePolicyDenied(f"Task step budget exhausted ({max_steps})")
        max_calls = int(budgets.get("max_tool_calls", 500))
        if task.current_step >= max_calls:
            task.status = CodingTaskStatus.TIMED_OUT
            raise CodePolicyDenied(f"Task tool-call budget exhausted ({max_calls})")
        started = task.created_at
        max_dur = int(budgets.get("max_duration_seconds", task.max_duration_seconds or 3600))
        try:
            elapsed = (_now() - started).total_seconds() if started else 0
        except TypeError:
            elapsed = 0
        if elapsed > max_dur:
            task.status = CodingTaskStatus.TIMED_OUT
            raise CodePolicyDenied(f"Task duration budget exhausted ({max_dur}s)")

    async def _get_repo(self, repo_id: UUID, organization_id: UUID) -> Repository:
        res = await self.db.execute(select(Repository).where(
            Repository.id == repo_id, Repository.organization_id == organization_id,
            Repository.deleted_at.is_(None)))
        repo = res.scalars().first()
        if not repo:
            raise CodeNotFound("Repository not found")
        return repo

    async def _get_task(self, task_id: UUID, organization_id: UUID) -> CodingTask:
        res = await self.db.execute(select(CodingTask).where(
            CodingTask.id == task_id, CodingTask.organization_id == organization_id))
        task = res.scalars().first()
        if not task:
            # also accept the public task_id string
            res = await self.db.execute(select(CodingTask).where(
                CodingTask.task_id == str(task_id),
                CodingTask.organization_id == organization_id))
            task = res.scalars().first()
        if not task:
            raise CodeNotFound("Coding task not found")
        return task

    async def _get_workspace(self, ws_id: UUID, organization_id: UUID) -> CodeWorkspace:
        res = await self.db.execute(select(CodeWorkspace).where(
            CodeWorkspace.id == ws_id, CodeWorkspace.organization_id == organization_id))
        ws = res.scalars().first()
        if not ws:
            res = await self.db.execute(select(CodeWorkspace).where(
                CodeWorkspace.workspace_id == str(ws_id),
                CodeWorkspace.organization_id == organization_id))
            ws = res.scalars().first()
        if not ws:
            raise CodeNotFound("Workspace not found")
        return ws

    def _workspace_path(self, ws: CodeWorkspace) -> Path:
        # filesystem_root is server-side only; resolve + re-jail defensively.
        root = Path(ws.filesystem_root).resolve()
        try:
            root.relative_to(self._root)
        except ValueError:
            raise CodeSecurityError("Workspace path escapes the workspace root")
        if ws.status == WorkspaceStatus.DELETED:
            raise CodeSecurityError("Workspace is deleted")
        return root

    def _provider_for(self, repo: Repository):
        return create_provider(repo.provider.value
                               if hasattr(repo.provider, "value") else str(repo.provider),
                               self._runner)

    def _repo_info(self, repo: Repository) -> RepositoryInfo:
        return RepositoryInfo(
            external_id=repo.external_id or str(repo.id), name=repo.name,
            full_name=repo.full_name, clone_url=repo.clone_url,
            default_branch=repo.default_branch, visibility=repo.visibility,
            provider=repo.provider.value if hasattr(repo.provider, "value")
            else str(repo.provider))

    async def _auth_for(self, repo: Repository) -> GitAuth:
        from openagent.code.providers import GitAuth as _GA
        if not repo.credential_ref:
            return _GA(kind="none")
        if self._credential_resolver is not None:
            auth = await self._credential_resolver(repo.credential_ref,
                                                   repo.organization_id)
            if isinstance(auth, _GA):
                return auth
            raise CodeSecurityError("Credential resolver returned an invalid auth object")
        return await self._default_credential_auth(repo)

    async def _default_credential_auth(self, repo: Repository) -> GitAuth:
        """Resolve credential_ref against the credential store (server-side only).

        Production deployments plug their KMS/decryptor here; this default
        reads a documented ``git`` section from credential metadata and never
        logs or returns raw material to callers.
        """
        from openagent.code.providers import GitAuth as _GA
        from openagent.db.models.credential import Credential, CredentialStatus
        ref = (repo.credential_ref or "").strip()
        if not ref:
            return _GA(kind="none")
        res = await self.db.execute(select(Credential).where(
            Credential.organization_id == repo.organization_id,
            Credential.status == CredentialStatus.ACTIVE))
        cred = None
        for c in res.scalars().all():
            if str(c.id) == ref or (c.name or "") == ref:
                cred = c
                break
        if cred is None:
            raise CodePolicyDenied("Git credential reference is invalid or revoked")
        # Credential model stores JSON in `metadata`; accept either mapping.
        raw_meta = getattr(cred, "metadata", None) or getattr(cred, "meta", None) or {}
        git = (raw_meta.get("git") or {}) if isinstance(raw_meta, dict) else {}
        kind = str(git.get("kind", "none"))
        if kind == "https_token" and git.get("token"):
            return _GA(kind="https_token", token=str(git["token"]))
        if kind == "basic" and git.get("username") and git.get("password"):
            return _GA(kind="basic", username=str(git["username"]),
                       password=str(git["password"]))
        if kind == "ssh_key" and git.get("private_key"):
            keydir = self._root / ".keys"
            keydir.mkdir(parents=True, exist_ok=True)
            keyfile = keydir / f"{uuid.uuid4().hex}.key"
            keyfile.write_text(str(git["private_key"]), encoding="utf-8")
            try:
                os.chmod(keyfile, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            return _GA(kind="ssh_key", ssh_key_path=str(keyfile))
        raise CodePolicyDenied(
            "Credential has no usable git material (expected metadata.git with "
            "kind https_token|basic|ssh_key)")

    # -- repositories -------------------------------------------------------
    async def create_repository(self, *, organization_id: UUID, provider: str,
                                name: str, full_name: str, clone_url: str,
                                default_branch: str = "main", visibility: str = "private",
                                credential_ref: Optional[str] = None,
                                provider_config: Optional[dict] = None,
                                external_id: Optional[str] = None,
                                actor: Optional[UUID] = None) -> Repository:
        if provider not in ("local", "generic", "github", "gitlab", "bitbucket"):
            raise CodeSecurityError(f"Unknown repository provider: {provider}")
        scheme = clone_url.split("://")[0] if "://" in clone_url else "local"
        if scheme not in ("https", "http", "ssh", "git", "file", "local", "") \
                and not clone_url.startswith("git@"):
            raise CodeSecurityError(f"Clone URL scheme not allowed: {scheme}")
        if provider == "local":
            p = Path(clone_url.replace("file://", "")).resolve()
            if not p.is_dir():
                raise CodeNotFound("Local repository path does not exist")
        repo = Repository(
            organization_id=organization_id, provider=provider, external_id=external_id,
            name=name[:255], full_name=full_name[:500], clone_url=clone_url,
            default_branch=default_branch[:255], visibility=visibility,
            status="connected", credential_ref=credential_ref,
            provider_config=redact_dict(provider_config or {}), meta={})
        # SQLAlchemy enum assignment accepts raw values for str-enums.
        self.db.add(repo)
        await self.db.flush()
        await self._emit(organization_id, "repository.connected", payload={
            "repository_id": str(repo.id), "provider": provider,
            "full_name": full_name})
        await self._audit(organization_id, actor, "repository.connected",
                          "repository", repo.id, {"provider": provider})
        await self.db.commit()
        await self.db.refresh(repo)
        return repo

    async def list_repositories(self, organization_id: UUID) -> list[Repository]:
        res = await self.db.execute(select(Repository).where(
            Repository.organization_id == organization_id,
            Repository.deleted_at.is_(None)).order_by(Repository.created_at.desc()))
        return list(res.scalars().all())

    async def get_repository(self, repo_id: UUID, organization_id: UUID) -> Repository:
        return await self._get_repo(repo_id, organization_id)

    async def connect_repository(self, repo_id: UUID, organization_id: UUID) -> dict[str, Any]:
        """Validate reachability/credentials (ls-remote); marks status."""
        repo = await self._get_repo(repo_id, organization_id)
        provider = self._provider_for(repo)
        auth = await self._auth_for(repo)
        try:
            info = await provider.connect(self._repo_info(repo), auth)
            repo.status = "connected"
            await self._emit(organization_id, "repository.accessed", payload={
                "repository_id": str(repo.id), "refs": info.get("refs", 0)})
        except Exception as e:
            repo.status = "error"
            await self.db.commit()
            raise CodePolicyDenied(f"Repository unreachable: {redact_text(str(e))[:300]}")
        await self.db.commit()
        await self.db.refresh(repo)
        return {"ok": True, "status": str(repo.status)}

    async def sync_repository(self, repo_id: UUID, organization_id: UUID) -> dict[str, Any]:
        """Fetch latest index snapshot (re-index on next workspace creation)."""
        from datetime import timezone as _tz
        repo = await self._get_repo(repo_id, organization_id)
        repo.status = "syncing"
        await self.db.flush()
        job = await self.index_repository(repo_id, organization_id)
        repo.status = "connected"
        repo.last_synced_at = datetime.now(_tz.utc)
        await self.db.commit()
        return {"ok": True, "job_id": str(job.id),
                "files": job.files_indexed, "symbols": job.symbols_indexed}

    async def delete_repository(self, repo_id: UUID, organization_id: UUID,
                                actor: Optional[UUID] = None) -> None:
        repo = await self._get_repo(repo_id, organization_id)
        # Refuse while live workspaces exist.
        live = await self.db.scalar(select(func.count()).select_from(CodeWorkspace).where(
            CodeWorkspace.repository_id == repo.id,
            CodeWorkspace.status.notin_([WorkspaceStatus.DELETED])))
        if live:
            raise CodePolicyDenied("Repository has live workspaces; delete them first")
        from datetime import timezone as _tz
        repo.deleted_at = datetime.now(_tz.utc)
        await self._audit(organization_id, actor, "repository.deleted",
                          "repository", repo.id, {})
        await self.db.commit()

    async def list_remote_repositories(self, organization_id: UUID, provider: str,
                                       credential_ref: str) -> list[dict[str, Any]]:
        """Enumerate provider-side repos (forge REST, token server-side only)."""
        tmp = Repository(organization_id=organization_id, provider=provider, name="tmp",
                         full_name="tmp", clone_url="", credential_ref=credential_ref)
        auth = await self._auth_for(tmp)
        prov = create_provider(provider, self._runner)
        infos = await prov.list_repositories(auth)
        await self._audit(organization_id, None, "repository.accessed",
                          "repository", None, {"provider": provider, "listed": len(infos)})
        return [{"external_id": i.external_id, "name": i.name, "full_name": i.full_name,
                 "default_branch": i.default_branch, "visibility": i.visibility,
                 "web_url": i.web_url} for i in infos]

    # -- workspaces -----------------------------------------------------------
    async def create_workspace(self, *, organization_id: UUID, repository_id: UUID,
                               task_id: Optional[UUID] = None,
                               branch: Optional[str] = None,
                               actor: Optional[UUID] = None) -> CodeWorkspace:
        repo = await self._get_repo(repository_id, organization_id)
        if str(repo.status) not in ("connected", "RepositoryStatus.CONNECTED"):
            raise CodePolicyDenied("Repository is not connected")
        ws_id = _eid("ws")
        dest = self._root / ws_id
        provider = self._provider_for(repo)
        auth = await self._auth_for(repo)
        ws = CodeWorkspace(
            workspace_id=ws_id, organization_id=organization_id,
            repository_id=repo.id, task_id=task_id,
            branch=branch or task_branch_name(task_id and str(task_id) or ws_id),
            status="CREATING", filesystem_root=str(dest),
            user_changes_snapshot=[], meta={})
        self.db.add(ws)
        await self.db.flush()
        try:
            info = self._repo_info(repo)
            res = await provider.clone(info, auth, str(dest))
            runner_cwd = str(dest.relative_to(self._root))
            base_sha = res.head_sha
            # Isolated task branch (never the default branch by default).
            await self._runner.check(["checkout", "-b", ws.branch], cwd=runner_cwd)
            try:
                status = await self._runner.check(["status", "--porcelain"], cwd=runner_cwd)
            except GitSecurityError:
                status = ""
            ws.base_revision = base_sha
            ws.current_revision = base_sha
            ws.user_changes_snapshot = [l for l in status.splitlines() if l.strip()]
            ws.status = "READY"
            if ws.user_changes_snapshot:
                ws.status = "DIRTY"
        except Exception as e:
            ws.status = "ERROR"
            await self.db.commit()
            raise CodeSecurityError(f"Workspace creation failed: {redact_text(str(e))[:300]}")
        await self._emit(organization_id, "workspace.created", workspace_id=ws.id,
                         payload={"repository_id": str(repo.id), "branch": ws.branch,
                                  "base_revision": ws.base_revision})
        await self._audit(organization_id, actor, "workspace.created",
                          "code_workspace", ws.id, {"branch": ws.branch})
        await self.db.commit()
        await self.db.refresh(ws)
        return ws

    async def list_workspaces(self, organization_id: UUID,
                              status: Optional[str] = None) -> list[CodeWorkspace]:
        q = select(CodeWorkspace).where(CodeWorkspace.organization_id == organization_id)
        if status:
            q = q.where(CodeWorkspace.status == status)
        q = q.order_by(CodeWorkspace.created_at.desc())
        return list((await self.db.execute(q)).scalars().all())

    async def get_workspace(self, ws_id: UUID, organization_id: UUID) -> CodeWorkspace:
        return await self._get_workspace(ws_id, organization_id)

    async def workspace_status(self, ws_id: UUID,
                               organization_id: UUID) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        path = self._workspace_path(ws)
        rel = str(path.relative_to(self._root))
        try:
            porcelain = await self._runner.check(["status", "--porcelain"], cwd=rel)
            branch = (await self._runner.check(
                ["rev-parse", "--abbrev-ref", "HEAD"], cwd=rel)).strip()
            sha = (await self._runner.check(["rev-parse", "HEAD"], cwd=rel)).strip()
        except GitSecurityError as e:
            raise CodeSecurityError(str(e))
        changes = [l for l in porcelain.splitlines() if l.strip()]
        return {"workspace_id": ws.workspace_id, "status": str(ws.status),
                "branch": branch, "head": sha, "base_revision": ws.base_revision,
                "dirty": bool(changes), "changes": changes[:100],
                "user_changes": ws.user_changes_snapshot or []}

    async def delete_workspace(self, ws_id: UUID, organization_id: UUID,
                               force: bool = False,
                               actor: Optional[UUID] = None) -> None:
        import shutil
        ws = await self._get_workspace(ws_id, organization_id)
        if ws.status == WorkspaceStatus.DELETED:
            return
        st = await self.workspace_status(ws_id, organization_id)
        user_files = {l[3:].strip() for l in (ws.user_changes_snapshot or []) if len(l) > 3}
        current = {l[3:].strip() for l in st["changes"] if len(l) > 3}
        # Never delete uncommitted USER work without explicit force.
        if user_files & current and not force:
            raise CodePolicyDenied(
                "Workspace contains uncommitted user changes; pass force=true "
                "with approval to delete")
        ws.status = "CLEANING"
        await self.db.flush()
        try:
            shutil.rmtree(self._workspace_path(ws), ignore_errors=True)
        except (OSError, CodeSecurityError):
            pass
        ws.status = "DELETED"
        await self._emit(organization_id, "workspace.deleted", workspace_id=ws.id,
                         payload={"forced": force})
        await self._audit(organization_id, actor, "workspace.deleted",
                          "code_workspace", ws.id, {"forced": force})
        await self.db.commit()

    # -- files ------------------------------------------------------------------
    async def list_files(self, ws_id: UUID, organization_id: UUID,
                         prefix: str = "") -> list[dict[str, Any]]:
        ws = await self._get_workspace(ws_id, organization_id)
        root = self._workspace_path(ws)
        files = intel.discover_files(root)
        if prefix:
            files = [f for f in files if f.startswith(prefix)]
        out = []
        for rel in files[:2000]:
            p = root / rel
            try:
                size = p.stat().st_size
            except OSError:
                continue
            out.append({"path": rel, "language": intel.detect_language(rel), "size": size})
        await self._emit(organization_id, "code.file.read", workspace_id=ws.id,
                         payload={"op": "list", "count": len(out)})
        return out

    def _read_file_text(self, ws: CodeWorkspace, rel_path: str,
                        max_bytes: int = 500_000) -> str:
        v = validate_workspace_path(str(self._workspace_path(ws)), rel_path)
        if not v.valid:
            raise CodePolicyDenied(v.reason)
        p = Path(v.resolved or "")
        if not p.is_file():
            raise CodeNotFound(f"File not found: {rel_path}")
        if intel.is_binary_path(rel_path):
            raise CodePolicyDenied("Binary files cannot be read as text")
        try:
            data = p.read_bytes()
        except OSError:
            raise CodeNotFound(f"File not readable: {rel_path}")
        if len(data) > max_bytes:
            raise CodePolicyDenied("File exceeds read size limit")
        return data.decode("utf-8", "replace")

    async def read_file(self, ws_id: UUID, organization_id: UUID,
                        path: str) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        content = self._read_file_text(ws, path)
        hits = detect_repo_injection(content)
        await self._emit(organization_id, "code.file.read", workspace_id=ws.id,
                         payload={"op": "read", "path": path,
                                  "injection_signals": len(hits)})
        if hits:
            content = label_untrusted_code(content)
        return {"path": path, "content": content,
                "language": intel.detect_language(path),
                "untrusted": True, "injection_signals": hits[:5]}

    async def read_range(self, ws_id: UUID, organization_id: UUID, path: str,
                         start: int, end: int) -> dict[str, Any]:
        if start < 1 or end < start or end - start > 2000:
            raise CodePolicyDenied("Invalid line range")
        doc = await self.read_file(ws_id, organization_id, path)
        lines = doc["content"].splitlines()
        doc["content"] = "\n".join(lines[start - 1:end])
        doc["range"] = [start, end]
        return doc

    async def _is_dirty(self, ws_rel: str, target: str) -> bool:
        """True when a workspace file has uncommitted changes."""
        try:
            out = await self._runner.check(
                ["status", "--porcelain", "--", target], cwd=ws_rel)
        except GitSecurityError:
            return False
        return bool(out.strip())

    # -- search -------------------------------------------------------------------
    async def search_text(self, ws_id: UUID, organization_id: UUID, query: str,
                          max_hits: int = 100) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        hits = intel.search_text(self._workspace_path(ws), query, max_hits=max_hits)
        await self._emit(organization_id, "code.search.completed", workspace_id=ws.id,
                         payload={"mode": "text", "query": query[:200], "hits": len(hits)})
        return {"hits": [h.__dict__ for h in hits], "untrusted": True}

    async def search_regex(self, ws_id: UUID, organization_id: UUID, pattern: str,
                           max_hits: int = 100) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        try:
            hits = intel.search_regex(self._workspace_path(ws), pattern, max_hits=max_hits)
        except ValueError as e:
            raise CodePolicyDenied(str(e))
        await self._emit(organization_id, "code.search.completed", workspace_id=ws.id,
                         payload={"mode": "regex", "hits": len(hits)})
        return {"hits": [h.__dict__ for h in hits], "untrusted": True}

    async def find_symbol(self, ws_id: UUID, organization_id: UUID, name: str,
                          kind: Optional[str] = None) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        q = select(CodeSymbol).where(
            CodeSymbol.repository_id == ws.repository_id,
            CodeSymbol.name == name)
        if kind:
            q = q.where(CodeSymbol.kind == kind)
        rows = list((await self.db.execute(q.limit(50))).scalars().all())
        # Fall back to a live workspace scan when the index is stale/empty.
        live: list[dict[str, Any]] = []
        if not rows:
            root = self._workspace_path(ws)
            for rel in intel.discover_files(root)[:2000]:
                try:
                    text = (root / rel).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for sym, _refs in [intel.extract_symbols(
                        text, rel, intel.detect_language(rel))]:
                    if sym.name == name and (not kind or sym.kind == kind):
                        live.append({"name": sym.name, "kind": sym.kind, "file": rel,
                                     "line_start": sym.line_start, "line_end": sym.line_end,
                                     "signature": sym.signature})
                    if len(live) >= 50:
                        break
        await self._emit(organization_id, "code.search.completed", workspace_id=ws.id,
                         payload={"mode": "symbol", "name": name,
                                  "hits": len(rows) + len(live)})
        return {"symbols": [
            {"name": s.name, "kind": s.kind, "file": s.file,
             "line_start": s.line_start, "line_end": s.line_end,
             "signature": s.signature} for s in rows] + live,
            "untrusted": True}

    async def find_references(self, ws_id: UUID, organization_id: UUID,
                              symbol: str) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        q = select(CodeReference).where(
            CodeReference.repository_id == ws.repository_id,
            CodeReference.to_name == symbol).limit(100)
        rows = list((await self.db.execute(q)).scalars().all())
        live = intel.find_usages(self._workspace_path(ws), symbol)
        await self._emit(organization_id, "code.search.completed", workspace_id=ws.id,
                         payload={"mode": "references", "symbol": symbol})
        return {"references": [
            {"from_file": r.from_file, "from_symbol": r.from_symbol,
             "kind": r.kind, "line": r.line} for r in rows] +
            [{"from_file": h.file, "from_symbol": "", "kind": "usage",
              "line": h.line, "excerpt": h.excerpt} for h in live],
            "untrusted": True}

    async def semantic_search(self, ws_id: UUID, organization_id: UUID,
                              query: str, top_k: int = 20) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        results = await self._semantic_provider().search(query, top_k=top_k)
        await self._emit(organization_id, "code.search.completed", workspace_id=ws.id,
                         payload={"mode": "semantic", "hits": len(results)})
        return {"hits": results, "untrusted": True,
                "note": "Semantic index unavailable" if not results else ""}

    # -- indexing -------------------------------------------------------------------
    async def index_repository(self, repo_id: UUID,
                               organization_id: UUID) -> CodeIndexJob:
        """Full index pipeline: discover -> parse -> symbols/refs/deps/chunks."""
        from datetime import timezone as _tz
        repo = await self._get_repo(repo_id, organization_id)
        job = CodeIndexJob(repository_id=repo.id, status="RUNNING",
                           started_at=datetime.now(_tz.utc),
                           created_at=datetime.now(_tz.utc))
        self.db.add(job)
        await self.db.flush()
        # Index the freshest checkout we have: prefer a workspace, else clone URL
        # is remote-only and indexing runs at workspace creation. Here we index
        # whichever workspace exists, else record an empty job honestly.
        ws_res = await self.db.execute(select(CodeWorkspace).where(
            CodeWorkspace.repository_id == repo.id,
            CodeWorkspace.status.notin_([WorkspaceStatus.DELETED])).limit(1))
        ws = ws_res.scalars().first()
        try:
            if ws is None:
                job.status = "SUCCEEDED"
                job.error = "No local checkout yet; index on workspace creation"
            else:
                root = self._workspace_path(ws)
                counts = await self._index_tree(repo, root)
                job.files_indexed = counts["files"]
                job.symbols_indexed = counts["symbols"]
                job.status = "SUCCEEDED"
            job.completed_at = datetime.now(_tz.utc)
        except Exception as e:
            job.status = "FAILED"
            job.error = redact_text(str(e))[:500]
            job.completed_at = datetime.now(_tz.utc)
        await self.db.commit()
        await self.db.refresh(job)
        return job

    async def _index_tree(self, repo: Repository, root: Path) -> dict[str, int]:
        """Index a local tree; incremental via size+mtime fingerprints."""
        from datetime import timezone as _tz
        existing = (await self.db.execute(select(CodeFileIndex).where(
            CodeFileIndex.repository_id == repo.id))).scalars().all()
        known = {f.path: f for f in existing}
        seen: set[str] = set()
        files = symbols = 0
        for rel in intel.discover_files(root):
            seen.add(rel)
            p = root / rel
            try:
                size, mtime = intel.fingerprint_file(p)
            except OSError:
                continue
            prev = known.get(rel)
            if prev and prev.size == size and prev.mtime_ns == mtime:
                continue  # unchanged — incremental skip
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            sha = intel.sha256_file(p)
            lang = intel.detect_language(rel)
            syms, refs = intel.extract_symbols(text, rel, lang)
            chunks = intel.chunk_file(text, rel, syms)
            if prev:
                await self._delete_file_index(repo.id, rel)
            self.db.add(CodeFileIndex(
                repository_id=repo.id, path=rel, language=lang, size=size,
                sha256=sha, mtime_ns=mtime, indexed_at=datetime.now(_tz.utc)))
            for s in syms:
                self.db.add(CodeSymbol(
                    repository_id=repo.id, name=s.name, kind=s.kind, file=s.file,
                    line_start=s.line_start, line_end=s.line_end,
                    signature=s.signature[:500], parent=s.parent[:500]))
            for r in refs:
                self.db.add(CodeReference(
                    repository_id=repo.id, from_file=r.from_file,
                    from_symbol=r.from_symbol[:500], to_name=r.to_name[:500],
                    kind=r.kind, line=r.line))
            for c in chunks[:50]:
                self.db.add(CodeChunk(
                    repository_id=repo.id, file=c.file, symbol=c.symbol[:500],
                    content=c.content[:8000], line_start=c.line_start,
                    line_end=c.line_end))
            if rel.split("/")[-1].lower() in MANIFEST_BASENAMES or rel.endswith(".csproj"):
                for d in parse_dependencies(root, rel, text)[:200]:
                    self.db.add(CodeDependency(
                        repository_id=repo.id, file=d["file"], manager=d["manager"],
                        name=d["name"][:500], version_spec=d["version_spec"][:255],
                        scope=d["scope"]))
            files += 1
            symbols += len(syms)
        # Removals / renames: drop index rows for vanished paths.
        for rel in set(known) - seen:
            await self._delete_file_index(repo.id, rel)
        await self.db.flush()
        return {"files": files, "symbols": symbols}

    async def _delete_file_index(self, repo_id: UUID, rel: str) -> None:
        for model, col in ((CodeFileIndex, CodeFileIndex.path),
                           (CodeSymbol, CodeSymbol.file),
                           (CodeReference, CodeReference.from_file),
                           (CodeChunk, CodeChunk.file)):
            rows = (await self.db.execute(select(model).where(
                model.repository_id == repo_id, col == rel))).scalars().all()
            for r in rows:
                await self.db.delete(r)

    async def reindex_paths(self, ws_id: UUID, organization_id: UUID,
                            paths: list[str]) -> dict[str, Any]:
        """Incremental reindex of edited files (create/modify/delete aware)."""
        ws = await self._get_workspace(ws_id, organization_id)
        repo = await self._get_repo(ws.repository_id, organization_id)
        root = self._workspace_path(ws)
        from datetime import timezone as _tz
        done = {"indexed": [], "removed": []}
        for rel in paths[:200]:
            v = validate_workspace_path(str(root), rel)
            if not v.valid:
                continue
            p = Path(v.resolved or "")
            if not p.is_file():
                await self._delete_file_index(repo.id, rel)
                done["removed"].append(rel)
                continue
            try:
                size, mtime = intel.fingerprint_file(p)
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            await self._delete_file_index(repo.id, rel)
            lang = intel.detect_language(rel)
            syms, refs = intel.extract_symbols(text, rel, lang)
            self.db.add(CodeFileIndex(
                repository_id=repo.id, path=rel, language=lang, size=size,
                sha256=intel.sha256_file(p), mtime_ns=mtime,
                indexed_at=datetime.now(_tz.utc)))
            for s in syms:
                self.db.add(CodeSymbol(
                    repository_id=repo.id, name=s.name, kind=s.kind, file=s.file,
                    line_start=s.line_start, line_end=s.line_end,
                    signature=s.signature[:500], parent=s.parent[:500]))
            for r in refs:
                self.db.add(CodeReference(
                    repository_id=repo.id, from_file=r.from_file,
                    from_symbol=r.from_symbol[:500], to_name=r.to_name[:500],
                    kind=r.kind, line=r.line))
            done["indexed"].append(rel)
        await self.db.commit()
        return done

    async def get_index_status(self, repo_id: UUID,
                               organization_id: UUID) -> dict[str, Any]:
        repo = await self._get_repo(repo_id, organization_id)
        files = await self.db.scalar(select(func.count()).select_from(CodeFileIndex).where(
            CodeFileIndex.repository_id == repo.id)) or 0
        symbols = await self.db.scalar(select(func.count()).select_from(CodeSymbol).where(
            CodeSymbol.repository_id == repo.id)) or 0
        job = (await self.db.execute(select(CodeIndexJob).where(
            CodeIndexJob.repository_id == repo.id).order_by(
            CodeIndexJob.created_at.desc()).limit(1))).scalars().first()
        return {"files": files, "symbols": symbols,
                "last_job": {"status": job.status, "error": job.error} if job else None}

    async def build_task_context(self, task_id: UUID, organization_id: UUID,
                                 extra_files: Optional[list[str]] = None) -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id)
        if not task.workspace_id:
            raise CodePolicyDenied("Task has no workspace yet")
        ws = await self._get_workspace(task.workspace_id, organization_id)
        root = self._workspace_path(ws)
        candidates = intel.discover_files(root)[:500]
        syms = list((await self.db.execute(select(CodeSymbol).where(
            CodeSymbol.repository_id == ws.repository_id).limit(2000))).scalars().all())

        def _read(rel: str) -> str:
            return self._read_file_text(ws, rel)

        package = intel.build_context_package(
            task.objective, (extra_files or []) + candidates, _read,
            symbols=[intel.CodeSymbol(name=s.name, kind=s.kind, file=s.file,
                                      line_start=s.line_start, line_end=s.line_end,
                                      signature=s.signature) for s in syms])
        package["instructions"] = filter_repo_instructions(
            intel.load_repo_instructions(root))
        return package

    # -- diff -----------------------------------------------------------------------
    async def get_diff(self, ws_id: UUID, organization_id: UUID,
                       kind: str = "working", ref: Optional[str] = None,
                       path: Optional[str] = None) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        rel = str(self._workspace_path(ws).relative_to(self._root))
        args: list[str]
        if kind == "working":
            args = ["diff", "--", path] if path else ["diff"]
        elif kind == "staged":
            args = ["diff", "--cached", "--", path] if path else ["diff", "--cached"]
        elif kind == "commit":
            if not ref or not re.match(r"^[0-9a-fA-F]{4,64}$|^[A-Za-z0-9_.\-/]+$", ref):
                raise CodePolicyDenied("Invalid commit ref")
            args = ["show", ref, "--", path] if path else ["show", ref]
        elif kind == "file":
            if not path:
                raise CodePolicyDenied("file diff requires path")
            v = validate_workspace_path(str(self._workspace_path(ws)), path)
            if not v.valid:
                raise CodePolicyDenied(v.reason)
            args = ["diff", "--", path]
        else:
            raise CodePolicyDenied(f"Unknown diff kind: {kind}")
        out = await self._runner.check(args, cwd=rel)
        await self._emit(organization_id, "code.search.completed", workspace_id=ws.id,
                         payload={"op": "diff", "kind": kind})
        return {"diff": out[:200_000], "truncated": len(out) > 200_000,
                "untrusted": True}

    # -- patches ----------------------------------------------------------------------
    async def propose_patch(self, task_id: UUID, organization_id: UUID,
                            diff_text: str) -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id)
        if not task.workspace_id:
            raise CodePolicyDenied("Task has no workspace yet")
        ws = await self._get_workspace(task.workspace_id, organization_id)
        root = str(self._workspace_path(ws))
        try:
            fps = parse_unified_diff(diff_text)
        except PatchError as e:
            raise CodePolicyDenied(f"Malformed patch: {e}")
        ok, errors, needs_approval = validate_patch(root, fps)
        if not ok:
            raise CodePolicyDenied("Patch validation failed: " + "; ".join(errors[:5]))
        files = [(_target(f)) for f in fps]
        patch = CodePatch(task_id=task.id, organization_id=organization_id,
                          files=[{"path": p} for p in files],
                          insertions=sum(1 for f in fps for h in f.hunks
                                         for ln in h.lines if ln.startswith("+")),
                          deletions=sum(1 for f in fps for h in f.hunks
                                        for ln in h.lines if ln.startswith("-")),
                          status="VALIDATED" if not needs_approval else "PROPOSED",
                          created_at=_now())
        self.db.add(patch)
        await self.db.flush()
        await self._step(task, "diff", "SUCCEEDED",
                         {"files": files}, {"needs_approval": needs_approval})
        await self._emit(organization_id, "code.patch.proposed", task_id=task.id,
                         workspace_id=ws.id,
                         payload={"patch_id": str(patch.id), "files": files,
                                  "needs_approval": needs_approval})
        await self.db.commit()
        return {"patch_id": str(patch.id), "files": files,
                "needs_approval": needs_approval,
                "status": str(patch.status)}

    async def apply_patch(self, task_id: UUID, organization_id: UUID,
                          patch_id: Optional[UUID] = None,
                          diff_text: Optional[str] = None,
                          approved: bool = False,
                          approval_id: Optional[UUID] = None) -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id)
        self._check_budgets(task)
        if not task.workspace_id:
            raise CodePolicyDenied("Task has no workspace yet")
        ws = await self._get_workspace(task.workspace_id, organization_id)
        if str(ws.status) not in ("READY", "DIRTY", "WorkspaceStatus.READY",
                                  "WorkspaceStatus.DIRTY"):
            raise CodePolicyDenied(f"Workspace is {ws.status}; cannot edit now")
        root = str(self._workspace_path(ws))
        if patch_id and not diff_text:
            res = await self.db.execute(select(CodePatch).where(
                CodePatch.id == patch_id, CodePatch.organization_id == organization_id))
            stored = res.scalars().first()
            if not stored:
                raise CodeNotFound("Patch not found")
            raise CodePolicyDenied(
                "Stored patches re-apply from submitted diff text only "
                "(prevents stale-context replay)")
        if not diff_text:
            raise CodePolicyDenied("diff_text is required")
        try:
            fps = parse_unified_diff(diff_text)
        except PatchError as e:
            raise CodePolicyDenied(f"Malformed patch: {e}")
        ok, errors, needs_approval = validate_patch(root, fps)
        if not ok:
            raise CodePolicyDenied("Patch validation failed: " + "; ".join(errors[:5]))
        if needs_approval:
            # MP19: only a persisted approval bound to this exact diff authorizes
            # the apply. A client boolean is never proof.
            import hashlib as _hashlib
            diff_hash = _hashlib.sha256((diff_text or "").encode("utf-8")).hexdigest()
            verified = False
            if approval_id is not None:
                from openagent.approvals.integrations import consume_approval as _consume
                _ok, _ = await _consume(
                    self.db, approval_id=approval_id, organization_id=organization_id,
                    action_type="code.apply_patch", action_category="MODIFY_REPOSITORY",
                    target_type="code_task", target_id=str(task.id),
                    params={"diff_hash": diff_hash}, environment="development")
                verified = _ok
            if not verified:
                from openagent.approvals.integrations import park_for_approval as _park
                parked = await _park(
                    self.db, organization_id=organization_id,
                    action_type="code.apply_patch", action_category="MODIFY_REPOSITORY",
                    target_type="code_task", target_id=str(task.id),
                    params={"diff_hash": diff_hash}, environment="development",
                    impact_summary="Code patch touches sensitive paths/content",
                    requester_type="agent", task_id=str(task.id))
                await self._emit(organization_id, "code.patch.proposed", task_id=task.id,
                                 workspace_id=ws.id,
                                 payload={"needs_approval": True,
                                          "reason": "sensitive path or secret-like content",
                                          "approval_id": str(parked.id) if parked else None})
                return {"success": False, "needs_approval": True,
                        "approval_id": str(parked.id) if parked else None,
                        "status": "WAITING_FOR_APPROVAL",
                        "message": "Patch touches sensitive paths/content and requires approval"}
        # User-change protection: refuse files dirty outside agent work.
        # Anything with uncommitted changes that this task did not make is
        # treated as someone else's work (user or another agent).
        agent_files = set((task.meta or {}).get("agent_files", []))
        ws_rel = str(self._workspace_path(ws).relative_to(self._root))
        for f in fps:
            target = _target(f)
            if target not in agent_files and await self._is_dirty(ws_rel, target):
                raise CodePolicyDenied(
                    f"Refusing to overwrite file with outside changes: {target} "
                    f"(uncommitted changes pre-date this task's edits)")
        ws.status = "BUSY"
        await self.db.flush()
        try:
            result = apply_patch(root, diff_text, dry_run=False)
        except PatchError as e:
            ws.status = "READY"
            await self.db.commit()
            raise CodePolicyDenied(f"Patch apply failed: {e}")
        agent_files.update(result.files_changed)
        task.meta = {**(task.meta or {}), "agent_files": sorted(agent_files)}
        patch = CodePatch(task_id=task.id, organization_id=organization_id,
                          files=[{"path": c.file, "summary": c.summary}
                                 for c in result.changes],
                          insertions=result.insertions, deletions=result.deletions,
                          status="APPLIED", created_at=_now())
        self.db.add(patch)
        ws.status = "DIRTY"
        try:
            sha = (await self._runner.check(
                ["rev-parse", "HEAD"],
                cwd=str(self._workspace_path(ws).relative_to(self._root)))).strip()
            ws.current_revision = sha
        except GitSecurityError:
            pass
        await self._step(task, "edit", "SUCCEEDED", {"files": result.files_changed},
                         {"insertions": result.insertions, "deletions": result.deletions})
        await self._emit(organization_id, "code.patch.applied", task_id=task.id,
                         workspace_id=ws.id,
                         payload={"patch_id": str(patch.id),
                                  "files": result.files_changed})
        await self._audit(organization_id, task.user_id, "code.patch.applied",
                          "code_patch", patch.id, {"files": result.files_changed})
        await self.db.commit()
        # Incremental reindex of touched files (outside the commit).
        try:
            await self.reindex_paths(ws.id, organization_id, result.files_changed)
        except (CodeSecurityError, CodeNotFound):
            pass
        return {"success": True, "patch_id": str(patch.id),
                "files": result.files_changed,
                "insertions": result.insertions, "deletions": result.deletions}

    # -- review -------------------------------------------------------------------------
    async def review_task(self, task_id: UUID, organization_id: UUID,
                          reviewer: str = "static") -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id)
        if not task.workspace_id:
            raise CodePolicyDenied("Task has no workspace yet")
        ws = await self._get_workspace(task.workspace_id, organization_id)
        diff = await self.get_diff(ws.id, organization_id, kind="working")
        return await self._persist_review(
            organization_id, task, ws.repository_id, reviewer,
            review_diff(diff["diff"]), {"scope": "working-tree"})

    async def review_text(self, organization_id: UUID, filename: str, content: str,
                          task_id: Optional[UUID] = None) -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id) if task_id else None
        repo_id = task.repository_id if task else None
        if len(content) > 500_000:
            raise CodePolicyDenied("Review content exceeds size limit")
        result = await self._persist_review(
            organization_id, task, repo_id, "static",
            review_text(content, filename), {"scope": "adhoc", "file": filename})
        return result

    async def _persist_review(self, organization_id: UUID, task: Optional[CodingTask],
                              repository_id: Optional[UUID], reviewer: str,
                              result: ReviewResult, scope: dict) -> dict[str, Any]:
        from datetime import timezone as _tz
        await self._emit(organization_id, "code.review.started",
                         task_id=task.id if task else None, payload=scope)
        review = CodeReview(
            organization_id=organization_id, task_id=task.id if task else None,
            repository_id=repository_id, reviewer=reviewer,
            status="PASSED" if result.passed else "BLOCKED",
            summary=result.summary[:2000], created_at=_now(),
            completed_at=datetime.now(_tz.utc))
        self.db.add(review)
        await self.db.flush()
        for f in result.findings[:500]:
            self.db.add(CodeReviewFinding(
                review_id=review.id, severity=f.severity, file=f.file[:2000],
                line=f.line, category=f.category[:40], finding=f.finding[:2000],
                evidence=f.evidence[:1000], suggested_fix=f.suggested_fix[:2000]))
        gate = gate_summary(result)
        if task:
            await self._step(task, "review",
                             "SUCCEEDED" if result.passed else "FAILED",
                             scope, gate)
        await self._emit(organization_id, "code.review.completed",
                         task_id=task.id if task else None, payload=gate)
        await self._audit(organization_id, task.user_id if task else None,
                          "code.review.completed", "code_review", review.id, gate)
        await self.db.commit()
        return {"review_id": str(review.id), **gate}

    # -- execution ----------------------------------------------------------------------
    def _storage_service(self) -> Any:
        if self._storage is not None:
            return self._storage
        try:
            from openagent.core.storage import create_storage_service
            self._storage = create_storage_service()
            return self._storage
        except Exception:
            return None

    async def _store_text(self, organization_id: UUID, task_id: Optional[UUID],
                          name: str, text: str) -> Optional[str]:
        """Persist large output via the storage abstraction (tenant-namespaced)."""
        if not text:
            return None
        svc = self._storage_service()
        if svc is None:
            return None
        key = f"code/{organization_id}/{task_id or 'adhoc'}/{_eid(name)}.log"
        try:
            stored = await svc.upload(key, io.BytesIO(text.encode("utf-8", "replace")),
                                      "text/plain", f"{name}.log",
                                      metadata={"organization_id": str(organization_id)})
            return stored.key
        except Exception:
            return None

    async def run_command(self, task_id: Optional[UUID], organization_id: UUID,
                          workspace_id: Optional[UUID], profile: str, command: str,
                          timeout_seconds: Optional[int] = None) -> dict[str, Any]:
        from openagent.code.security import EXECUTION_PROFILES  # noqa: F401 (anchor)
        prof = resolve_profile(profile)
        task = await self._get_task(task_id, organization_id) if task_id else None
        if task:
            self._check_budgets(task)
        if workspace_id:
            ws = await self._get_workspace(workspace_id, organization_id)
        elif task and task.workspace_id:
            ws = await self._get_workspace(task.workspace_id, organization_id)
        else:
            raise CodePolicyDenied("Execution requires a workspace")
        if str(ws.status) not in ("READY", "DIRTY", "TESTING", "BUSY",
                                  "WorkspaceStatus.READY", "WorkspaceStatus.DIRTY",
                                  "WorkspaceStatus.TESTING", "WorkspaceStatus.BUSY"):
            raise CodePolicyDenied(f"Workspace is {ws.status}; cannot execute now")
        await self._emit(organization_id, "code.execution.requested",
                         task_id=task.id if task else None, workspace_id=ws.id,
                         payload={"profile": prof.name, "command": command[:300]})
        cwd = str(self._workspace_path(ws))
        provider = self._execution_provider(
            organization_id, task.id if task else None,
            task.user_id if task else None)
        run = CodeExecutionRun(
            organization_id=organization_id, task_id=task.id if task else None,
            profile=prof.name, command=redact_text(command)[:2000],
            status=ExecutionStatus.RUNNING, started_at=_now(), created_at=_now())
        self.db.add(run)
        await self.db.flush()
        prev_status = ws.status
        ws.status = "TESTING"
        await self.db.flush()
        try:
            outcome = await provider.execute(command=command, cwd=cwd,
                                             profile=prof.name,
                                             timeout_seconds=timeout_seconds)
        except CodePolicyDenied as e:
            run.status = ExecutionStatus.BLOCKED
            run.completed_at = _now()
            run.diagnostics = {"blocked": str(e)[:500]}
            ws.status = prev_status
            await self._emit(organization_id, "code.execution.blocked",
                             task_id=task.id if task else None, workspace_id=ws.id,
                             payload={"reason": str(e)[:300]})
            await self.db.commit()
            raise
        run.exit_code = outcome.exit_code
        run.duration_ms = outcome.duration_ms
        run.status = (ExecutionStatus.SUCCEEDED if outcome.exit_code == 0
                      else ExecutionStatus.TIMED_OUT if outcome.timed_out
                      else ExecutionStatus.FAILED)
        run.stdout_tail = redact_text(outcome.stdout[-8000:])
        run.stdout_ref = await self._store_text(
            organization_id, task.id if task else None, "stdout", outcome.stdout)
        run.stderr_ref = await self._store_text(
            organization_id, task.id if task else None, "stderr",
            redact_text(outcome.stderr))
        run.completed_at = _now()
        ws.status = prev_status
        if task:
            await self._step(task, "test" if prof.name == "TEST" else "validate",
                             "SUCCEEDED" if run.status == ExecutionStatus.SUCCEEDED
                             else "FAILED",
                             {"profile": prof.name, "command": command[:300]},
                             {"exit_code": run.exit_code,
                              "duration_ms": run.duration_ms})
        await self._emit(organization_id, "code.test.completed"
                         if prof.name == "TEST" else "code.execution.requested",
                         task_id=task.id if task else None, workspace_id=ws.id,
                         payload={"profile": prof.name, "exit_code": run.exit_code,
                                  "duration_ms": run.duration_ms})
        await self.db.commit()
        await self.db.refresh(run)
        return {"run_id": str(run.id), "profile": prof.name,
                "status": str(run.status), "exit_code": run.exit_code,
                "duration_ms": run.duration_ms, "stdout_tail": run.stdout_tail,
                "stdout_ref": run.stdout_ref, "stderr_ref": run.stderr_ref}

    async def run_tests(self, task_id: Optional[UUID], organization_id: UUID,
                        workspace_id: Optional[UUID], command: str,
                        timeout_seconds: Optional[int] = None) -> dict[str, Any]:
        """Execute tests through the TEST profile and persist parsed results."""
        res = await self.run_command(task_id, organization_id, workspace_id,
                                     "TEST", command, timeout_seconds)
        parsed = parse_test_output(command, res["exit_code"], res["stdout_tail"])
        run_id = UUID(res["run_id"])
        for f in parsed["failures"]:
            self.db.add(CodeTestResult(
                execution_id=run_id, task_id=task_id, suite="", name=f["name"][:500],
                status="failed", message=f["message"][:2000], created_at=_now()))
        await self._emit(organization_id, "code.test.completed",
                         task_id=task_id, payload={"run_id": res["run_id"], **parsed,
                                                   "failures_stored": len(parsed["failures"])})
        await self.db.commit()
        return {**res, **parsed}

    async def plan_tests(self, task_id: UUID, organization_id: UUID) -> dict[str, Any]:
        """Test planning: changed files -> related tests + discovered commands."""
        task = await self._get_task(task_id, organization_id)
        if not task.workspace_id:
            raise CodePolicyDenied("Task has no workspace yet")
        ws = await self._get_workspace(task.workspace_id, organization_id)
        root = self._workspace_path(ws)
        diff = await self.get_diff(ws.id, organization_id, kind="working")
        changed: list[str] = []
        for raw in diff["diff"].splitlines():
            if raw.startswith("+++ "):
                p = raw[4:].strip()
                if p.startswith("b/"):
                    p = p[2:]
                if p != "/dev/null":
                    changed.append(p)
        related: list[str] = []
        for rel in intel.discover_files(root)[:5000]:
            if not intel.is_test_file(rel):
                continue
            stem = Path(rel).stem
            for c in changed:
                cstem = Path(c).stem
                if cstem and (cstem in stem or stem in cstem or
                              cstem.replace("_", "") in stem.replace("_", "")):
                    related.append(rel)
                    break
        plan = {"existing_to_run": sorted(set(related))[:50],
                "targeted_first": True,
                "new_tests_required": [c for c in changed
                                       if not intel.is_test_file(c)][:50],
                "discovered_commands": discover_test_commands(root),
                "regression_policy": "run targeted tests first, then broader "
                                     "suite per discovered commands"}
        await self._step(task, "plan", "SUCCEEDED", {"changed": changed[:50]}, plan)
        await self.db.commit()
        return plan

    # -- git operations -------------------------------------------------------------------
    async def create_branch(self, ws_id: UUID, organization_id: UUID,
                            name: str) -> dict[str, Any]:
        ws = await self._get_workspace(ws_id, organization_id)
        clean = re.sub(r"[^A-Za-z0-9_.\-/]", "", name)[:200]
        if not clean or clean.startswith(("-", ".", "/")) or ".." in clean \
                or clean.endswith((".lock", "/")):
            raise CodePolicyDenied("Invalid branch name")
        rel = str(self._workspace_path(ws).relative_to(self._root))
        await self._runner.check(["checkout", "-b", clean], cwd=rel)
        ws.branch = clean
        await self._emit(organization_id, "branch.created", workspace_id=ws.id,
                         payload={"branch": clean})
        await self._audit(organization_id, None, "branch.created",
                          "code_workspace", ws.id, {"branch": clean})
        await self.db.commit()
        return {"branch": clean}

    async def commit(self, task_id: UUID, organization_id: UUID, message: str,
                     author_name: Optional[str] = None,
                     author_email: Optional[str] = None) -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id)
        if not task.workspace_id:
            raise CodePolicyDenied("Task has no workspace yet")
        ws = await self._get_workspace(task.workspace_id, organization_id)
        root = self._workspace_path(ws)
        rel = str(root.relative_to(self._root))
        branch = (await self._runner.check(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=rel)).strip()
        if is_protected_branch(branch):
            raise CodePolicyDenied(
                f"Branch '{branch}' is protected; commit to a task branch instead")
        porcelain = await self._runner.check(["status", "--porcelain"], cwd=rel)
        if not porcelain.strip():
            raise CodePolicyDenied("Nothing to commit")
        # User-change protection: stage ONLY agent-touched files. Unrelated
        # dirty files stay in the working tree untouched.
        agent_files = set((task.meta or {}).get("agent_files", []))
        if not agent_files:
            raise CodePolicyDenied("No agent changes to commit")
        scoped = sorted(agent_files)
        diff = await self.get_diff(ws.id, organization_id, kind="working")
        secrets = scan_text_for_secrets(diff["diff"][:200_000], "working-tree")
        if secrets:
            await self._emit(organization_id, "secret.detected", task_id=task.id,
                             workspace_id=ws.id,
                             payload={"kinds": sorted({s.kind for s in secrets})})
            raise CodePolicyDenied(
                "Secret-like content in diff — remove it or request approval")
        review = await self.review_task(task.id, organization_id)
        if not review["passed"]:
            raise CodePolicyDenied(
                "Blocking review findings — resolve them before commit")
        msg = message.strip()[:2000]
        if not msg:
            raise CodePolicyDenied("Commit message is required")
        msg = redact_text(msg)
        ws.status = "COMMITTING"
        await self.db.flush()
        try:
            # Scoped staging: only agent files enter the commit.
            await self._runner.check(["add", "--", *scoped], cwd=rel)
            # Verify nothing foreign got staged (e.g. renames resolving oddly).
            staged = await self._runner.check(
                ["diff", "--cached", "--name-only"], cwd=rel)
            staged_files = {l.strip() for l in staged.splitlines() if l.strip()}
            if not staged_files:
                raise CodePolicyDenied("No agent changes to commit")
            if not staged_files <= agent_files:
                await self._runner.check(["reset"], cwd=rel)
                raise CodePolicyDenied(
                    "Staging would include non-agent files; commit refused")
            env = self._runner._env()
            if author_name:
                env["GIT_AUTHOR_NAME"] = author_name
                env["GIT_COMMITTER_NAME"] = author_name
            if author_email:
                env["GIT_AUTHOR_EMAIL"] = author_email
                env["GIT_COMMITTER_EMAIL"] = author_email
            # Author identity via -c would violate the runner allowlist; use env.
            proc_args = ["commit", "-m", msg]
            import asyncio as _aio
            proc = await _aio.create_subprocess_exec(
                "git", *proc_args, cwd=str(root), env=env,
                stdout=_aio.subprocess.PIPE, stderr=_aio.subprocess.PIPE)
            out, err = await _aio.wait_for(proc.communicate(), timeout=120)
            if proc.returncode != 0:
                raise CodeSecurityError(
                    f"git commit failed: {redact_text(err.decode('utf-8', 'replace'))[:300]}")
            sha = (await self._runner.check(["rev-parse", "HEAD"], cwd=rel)).strip()
        except CodeSecurityError:
            ws.status = "DIRTY"
            await self.db.commit()
            raise
        ws.current_revision = sha
        ws.status = "READY"
        files = sorted(staged_files)
        leftover = await self._runner.check(["status", "--porcelain"], cwd=rel)
        commit = CodeCommit(task_id=task.id, repository_id=ws.repository_id, sha=sha,
                            branch=branch, message=msg, files=files,
                            validation={"review": review, "secrets": "clean"},
                            created_at=_now())
        self.db.add(commit)
        await self._step(task, "commit", "SUCCEEDED", {"files": files[:50]},
                         {"sha": sha, "branch": branch})
        await self._emit(organization_id, "code.commit.created", task_id=task.id,
                         workspace_id=ws.id,
                         payload={"sha": sha, "branch": branch, "files": len(files)})
        await self._audit(organization_id, task.user_id, "code.commit.created",
                          "code_commit", commit.id, {"sha": sha, "branch": branch})
        await self.db.commit()
        return {"sha": sha, "branch": branch, "files": files, "review": review,
                "untouched": [l for l in leftover.splitlines() if l.strip()][:20]}

    async def push(self, task_id: UUID, organization_id: UUID,
                   remote: str = "origin", approved: bool = False,
                   approval_id: Optional[UUID] = None,
                   force: bool = False) -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id)
        if not task.workspace_id:
            raise CodePolicyDenied("Task has no workspace yet")
        if remote != "origin":
            raise CodePolicyDenied("Pushing to non-origin remotes is not allowed")
        ws = await self._get_workspace(task.workspace_id, organization_id)
        repo = await self._get_repo(ws.repository_id, organization_id)
        root = self._workspace_path(ws)
        rel = str(root.relative_to(self._root))
        branch = (await self._runner.check(
            ["rev-parse", "--abbrev-ref", "HEAD"], cwd=rel)).strip()
        if is_protected_branch(branch):
            await self._emit(organization_id, "push.blocked", task_id=task.id,
                             workspace_id=ws.id, payload={"branch": branch})
            raise CodePolicyDenied(f"Pushing to protected branch '{branch}' is blocked")
        if force:
            await self._emit(organization_id, "push.blocked", task_id=task.id,
                             workspace_id=ws.id, payload={"force": True})
            if approval_id is None:
                return {"success": False, "needs_approval": True,
                        "status": "WAITING_FOR_APPROVAL",
                        "message": "Force push requires explicit approval"}
        diff_remote = await self._runner.check(
            ["diff", "--stat", f"origin/{repo.default_branch}...HEAD"], cwd=rel)
        secrets = scan_text_for_secrets(diff_remote, "push-range")
        if secrets:
            await self._emit(organization_id, "secret.detected", task_id=task.id,
                             workspace_id=ws.id,
                             payload={"kinds": sorted({s.kind for s in secrets})})
            await self._emit(organization_id, "push.blocked", task_id=task.id,
                             workspace_id=ws.id, payload={"reason": "secrets"})
            raise CodePolicyDenied("Secret-like content in push range — push BLOCKED")
        if True:  # push always requires a persisted human approval (MP19)
            from openagent.approvals.integrations import (
                consume_approval as _consume_push,
                park_for_approval as _park_push,
            )
            push_params = {"branch": branch, "force": force, "remote": remote}
            verified = False
            if approval_id is not None:
                _ok, _ = await _consume_push(
                    self.db, approval_id=approval_id, organization_id=organization_id,
                    action_type="code.push", action_category="MODIFY_REPOSITORY",
                    target_type="code_task", target_id=str(task.id),
                    params=push_params, environment="development")
                verified = _ok
            if not verified:
                await self._emit(organization_id, "push.requested", task_id=task.id,
                                 workspace_id=ws.id, payload={"branch": branch})
                parked = await _park_push(
                    self.db, organization_id=organization_id,
                    action_type="code.push", action_category="MODIFY_REPOSITORY",
                    target_type="code_task", target_id=str(task.id),
                    params=push_params, environment="development",
                    impact_summary=f"Push of '{branch}' to origin",
                    requester_type="agent", task_id=str(task.id))
                task.status = CodingTaskStatus.WAITING_FOR_APPROVAL
                await self.db.commit()
                return {"success": False, "needs_approval": True,
                        "approval_id": str(parked.id) if parked else None,
                        "status": "WAITING_FOR_APPROVAL",
                        "message": f"Push of '{branch}' parked for approval"}
        provider = self._provider_for(repo)
        auth = await self._auth_for(repo)
        await self._emit(organization_id, "push.requested", task_id=task.id,
                         workspace_id=ws.id, payload={"branch": branch, "approved": True})
        try:
            await provider.push(str(root), auth, f"{branch}:{branch}", force=force)
        except GitSecurityError as e:
            await self._emit(organization_id, "push.blocked", task_id=task.id,
                             workspace_id=ws.id, payload={"reason": str(e)[:300]})
            raise CodePolicyDenied(f"Push failed: {redact_text(str(e))[:300]}")
        await self._step(task, "commit", "SUCCEEDED", {"branch": branch},
                         {"pushed": True})
        await self._emit(organization_id, "push.completed", task_id=task.id,
                         workspace_id=ws.id, payload={"branch": branch})
        await self._audit(organization_id, task.user_id, "code.push.completed",
                          "code_task", task.id, {"branch": branch})
        await self.db.commit()
        return {"success": True, "branch": branch}

    async def prepare_pr(self, task_id: UUID, organization_id: UUID,
                         title: str, summary: str = "",
                         reviewers: Optional[list[str]] = None,
                         open_remote: bool = False) -> dict[str, Any]:
        """Prepare a PR/MR draft; optionally open it on the forge. Never merges."""
        task = await self._get_task(task_id, organization_id)
        if not task.workspace_id:
            raise CodePolicyDenied("Task has no workspace yet")
        ws = await self._get_workspace(task.workspace_id, organization_id)
        repo = await self._get_repo(ws.repository_id, organization_id)
        title = title.strip()[:500]
        if not title:
            raise CodePolicyDenied("PR title is required")
        diff = await self.get_diff(ws.id, organization_id, kind="working")
        if diff["diff"].strip():
            raise CodePolicyDenied("Uncommitted changes remain; commit first")
        review = await self.review_task(task.id, organization_id)
        commits = (await self._runner.check(
            ["log", f"origin/{repo.default_branch}..HEAD", "--format=%H %s"],
            cwd=str(self._workspace_path(ws).relative_to(self._root)))).splitlines()
        pr = CodePullRequest(
            task_id=task.id, repository_id=repo.id, title=redact_text(title),
            summary=redact_text(summary)[:5000], branch=ws.branch,
            base=repo.default_branch, status="DRAFT",
            meta={"reviewers": reviewers or [], "review": review,
                  "commits": [c[:120] for c in commits[:50]]},
            created_at=_now(), updated_at=_now())
        self.db.add(pr)
        await self.db.flush()
        url = None
        if open_remote:
            url = await self._open_remote_pr(repo, pr)
            if url:
                pr.url = url
                pr.status = "OPENED"
        task.status = CodingTaskStatus.READY_FOR_PR
        await self._step(task, "commit", "SUCCEEDED", {"pr": title[:100]},
                         {"pr_id": str(pr.id), "url": url})
        await self._emit(organization_id, "code.pr.created", task_id=task.id,
                         workspace_id=ws.id,
                         payload={"pr_id": str(pr.id), "title": title[:200], "url": url})
        await self._audit(organization_id, task.user_id, "code.pr.created",
                          "code_pull_request", pr.id, {"title": title[:200]})
        await self.db.commit()
        return {"pr_id": str(pr.id), "title": pr.title, "branch": pr.branch,
                "base": pr.base, "status": str(pr.status), "url": url,
                "review": review, "merge": "never automatic (policy)"}

    async def _open_remote_pr(self, repo: Repository, pr: CodePullRequest) -> Optional[str]:
        """Open the PR on GitHub/GitLab via REST (server-side token only)."""
        import httpx
        auth = await self._auth_for(repo)
        if not auth.token or repo.provider not in ("github", "gitlab"):
            return None
        body = f"{pr.summary}\n\n---\nPrepared by OpenAgent (task {pr.task_id})."
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                if repo.provider == "github":
                    owner_repo = repo.full_name
                    base = repo.provider_config.get("api_base",
                                                    "https://api.github.com")
                    r = await client.post(
                        f"{base}/repos/{owner_repo}/pulls",
                        headers={"Authorization": f"Bearer {auth.token}"},
                        json={"title": pr.title, "head": pr.branch,
                              "base": pr.base, "body": body, "draft": True})
                    r.raise_for_status()
                    return r.json().get("html_url")
                else:
                    base = repo.provider_config.get(
                        "api_base", "https://gitlab.com/api/v4")
                    project = repo.external_id or repo.full_name.replace("/", "%2F")
                    r = await client.post(
                        f"{base}/projects/{project}/merge_requests",
                        headers={"PRIVATE-TOKEN": auth.token},
                        json={"title": pr.title, "source_branch": pr.branch,
                              "target_branch": pr.base, "description": body})
                    r.raise_for_status()
                    return r.json().get("web_url")
        except Exception as e:
            logger.warning("code.pr.open_failed", error=redact_text(str(e))[:200])
            return None
        return None

    # -- tasks ----------------------------------------------------------------------------
    async def create_task(self, *, organization_id: UUID, repository_id: UUID,
                          objective: str, user_id: Optional[UUID] = None,
                          agent_id: Optional[UUID] = None,
                          branch: Optional[str] = None,
                          max_steps: int = 50, max_duration_seconds: int = 3600,
                          risk_level: str = "MEDIUM",
                          budgets: Optional[dict] = None,
                          create_workspace: bool = True) -> CodingTask:
        repo = await self._get_repo(repository_id, organization_id)
        objective = redact_text(objective).strip()[:4000]
        if not objective:
            raise CodePolicyDenied("Objective is required")
        task = CodingTask(
            task_id=_eid("codetask"), organization_id=organization_id,
            user_id=user_id, agent_id=agent_id, repository_id=repo.id,
            objective=objective, branch=branch,
            status="QUEUED", risk_level=risk_level,
            max_steps=max(1, min(max_steps, 200)),
            max_duration_seconds=max(60, min(max_duration_seconds, 8 * 3600)),
            budgets={"max_steps": max(1, min(max_steps, 200)),
                     "max_tool_calls": 500,
                     "max_duration_seconds": max(60, min(max_duration_seconds, 8 * 3600)),
                     **(budgets or {})},
            meta={})
        self.db.add(task)
        await self.db.flush()
        await self._emit(organization_id, "code.task.started", task_id=task.id,
                         payload={"objective": objective[:500],
                                  "repository_id": str(repo.id)})
        if create_workspace:
            task.status = CodingTaskStatus.INITIALIZING
            await self.db.flush()
            ws = await self.create_workspace(
                organization_id=organization_id, repository_id=repo.id,
                task_id=task.id, branch=branch or task_branch_name(task.task_id))
            task.workspace_id = ws.id
            task.branch = ws.branch
            task.base_revision = ws.base_revision
            task.status = CodingTaskStatus.ANALYZING
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def list_tasks(self, organization_id: UUID,
                         status: Optional[str] = None,
                         repository_id: Optional[UUID] = None,
                         limit: int = 50, offset: int = 0) -> list[CodingTask]:
        q = select(CodingTask).where(CodingTask.organization_id == organization_id)
        if status:
            q = q.where(CodingTask.status == status)
        if repository_id:
            q = q.where(CodingTask.repository_id == repository_id)
        q = q.order_by(CodingTask.created_at.desc()).limit(limit).offset(offset)
        return list((await self.db.execute(q)).scalars().all())

    async def get_task(self, task_id: UUID, organization_id: UUID) -> CodingTask:
        return await self._get_task(task_id, organization_id)

    async def set_task_status(self, task_id: UUID, organization_id: UUID,
                              status: str) -> CodingTask:
        task = await self._get_task(task_id, organization_id)
        target = CodingTaskStatus(status)
        allowed = TASK_TRANSITIONS.get(task.status, set())
        if target not in allowed and target != task.status:
            raise CodePolicyDenied(
                f"Illegal task transition {task.status} -> {target}")
        task.status = target
        if target in (CodingTaskStatus.SUCCEEDED, CodingTaskStatus.FAILED,
                      CodingTaskStatus.CANCELLED, CodingTaskStatus.TIMED_OUT):
            task.completed_at = _now()
            await self._emit(organization_id, "code.task.completed", task_id=task.id,
                             payload={"status": str(target)})
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def cancel_task(self, task_id: UUID, organization_id: UUID) -> None:
        await self.set_task_status(task_id, organization_id, "CANCELLED")

    async def pause_task(self, task_id: UUID, organization_id: UUID) -> CodingTask:
        # Pause is advisory (no PAUSED state in the machine): record + emit.
        task = await self._get_task(task_id, organization_id)
        await self._step(task, "plan", "PAUSED", {}, {"note": "operator pause"})
        await self._emit(organization_id, "code.task.planning", task_id=task.id,
                         payload={"paused": True})
        await self.db.commit()
        return task

    async def resume_task(self, task_id: UUID, organization_id: UUID) -> CodingTask:
        task = await self._get_task(task_id, organization_id)
        await self._step(task, "plan", "RESUMED", {}, {})
        await self.db.commit()
        return task

    def build_plan(self, objective: str, risk_level: str = "MEDIUM",
                   max_steps: int = 50) -> dict[str, Any]:
        """Bounded iterative plan scaffold (agent runtime iterates it)."""
        steps = [
            {"n": 1, "phase": "ANALYZING", "action": "inspect repository layout + instructions"},
            {"n": 2, "phase": "ANALYZING", "action": "search relevant code/symbols/tests"},
            {"n": 3, "phase": "PLANNING", "action": "read files, build bounded change plan"},
            {"n": 4, "phase": "EDITING", "action": "apply patches (validated, incremental)"},
            {"n": 5, "phase": "VALIDATING", "action": "self-review diff + lint/typecheck"},
            {"n": 6, "phase": "TESTING", "action": "run targeted tests, then broader suite"},
            {"n": 7, "phase": "TESTING", "action": "analyze failures, fix, retest (bounded retries)"},
            {"n": 8, "phase": "REVIEWING", "action": "independent review + secret scan"},
            {"n": 9, "phase": "COMMITTING", "action": "commit on task branch + prepare PR draft"},
        ]
        budgets = {"max_steps": max(1, min(max_steps, 200)),
                   "max_tool_calls": 500, "max_fix_retries": 3,
                   "risk_level": risk_level}
        return {"objective": objective[:1000], "steps": steps, "budgets": budgets}

    async def complete_task(self, task_id: UUID, organization_id: UUID,
                            success: bool, summary: str = "") -> CodingTask:
        task = await self._get_task(task_id, organization_id)
        # Walk the machine legally toward a terminal state.
        for nxt in ("READY_FOR_PR", "SUCCEEDED" if success else "FAILED"):
            try:
                if nxt == "READY_FOR_PR" and not success:
                    continue
                await self.set_task_status(task_id, organization_id, nxt)
            except CodePolicyDenied:
                break
        task = await self._get_task(task_id, organization_id)
        task.result = {"success": success, "summary": redact_text(summary)[:2000]}
        await self.db.commit()
        await self.db.refresh(task)
        return task

    async def task_diff(self, task_id: UUID, organization_id: UUID) -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id)
        if not task.workspace_id:
            return {"diff": "", "files": []}
        return await self.get_diff(task.workspace_id, organization_id, kind="working")

    async def task_events(self, task_id: UUID, organization_id: UUID,
                          limit: int = 100) -> list[CodeEvent]:
        task = await self._get_task(task_id, organization_id)
        res = await self.db.execute(select(CodeEvent).where(
            CodeEvent.task_id == task.id,
            CodeEvent.organization_id == organization_id)
            .order_by(CodeEvent.timestamp.desc()).limit(min(limit, 500)))
        return list(res.scalars().all())

    async def task_artifacts(self, task_id: UUID,
                             organization_id: UUID) -> dict[str, Any]:
        task = await self._get_task(task_id, organization_id)
        patches = (await self.db.execute(select(CodePatch).where(
            CodePatch.task_id == task.id))).scalars().all()
        runs = (await self.db.execute(select(CodeExecutionRun).where(
            CodeExecutionRun.task_id == task.id))).scalars().all()
        reviews = (await self.db.execute(select(CodeReview).where(
            CodeReview.task_id == task.id))).scalars().all()
        commits = (await self.db.execute(select(CodeCommit).where(
            CodeCommit.task_id == task.id))).scalars().all()
        prs = (await self.db.execute(select(CodePullRequest).where(
            CodePullRequest.task_id == task.id))).scalars().all()
        return {
            "patches": [{"id": str(p.id), "files": p.files, "status": str(p.status),
                         "insertions": p.insertions, "deletions": p.deletions}
                        for p in patches],
            "runs": [{"id": str(r.id), "profile": r.profile,
                      "status": str(r.status), "exit_code": r.exit_code,
                      "stdout_ref": r.stdout_ref} for r in runs],
            "reviews": [{"id": str(r.id), "status": str(r.status),
                         "summary": r.summary[:500]} for r in reviews],
            "commits": [{"sha": c.sha, "branch": c.branch} for c in commits],
            "prs": [{"id": str(p.id), "title": p.title, "status": str(p.status),
                     "url": p.url} for p in prs],
        }

    # -- memory -------------------------------------------------------------------------
    async def remember_knowledge(self, repository_id: UUID, organization_id: UUID,
                                 content: str, kind: str = "convention",
                                 agent_id: Optional[UUID] = None) -> dict[str, Any]:
        """Record repository knowledge in the Memory Engine (org-scoped, secret-free)."""
        repo = await self._get_repo(repository_id, organization_id)
        clean = redact_text(content).strip()[:4000]
        if not clean:
            raise CodePolicyDenied("Empty knowledge content")
        if scan_text_for_secrets(clean, "memory"):
            raise CodePolicyDenied("Knowledge content looks like secret material")
        from openagent.db.models.memory import (MemoryScope, MemoryType,
                                                MemoryVisibility)
        from openagent.management.memory_service import MemoryService
        mem = await MemoryService(self.db).create_memory(
            organization_id=organization_id, content=f"[{kind}] {clean}",
            memory_type=MemoryType.SEMANTIC, scope=MemoryScope.ORGANIZATION,
            visibility=MemoryVisibility.ORGANIZATION, agent_id=agent_id,
            tags=["code-agent", "repository", repo.full_name, kind])
        await self.db.commit()
        return {"memory_id": str(mem.id)}

    # -- maintenance ----------------------------------------------------------------------
    async def sweep_workspaces(self) -> dict[str, int]:
        """Expire/cleanup old workspaces per policy (scheduler hook)."""
        from datetime import timezone as _tz
        now = datetime.now(_tz.utc)
        expired = (await self.db.execute(select(CodeWorkspace).where(
            CodeWorkspace.status.notin_([WorkspaceStatus.DELETED]),
            CodeWorkspace.expires_at.is_not(None),
            CodeWorkspace.expires_at <= now))).scalars().all()
        count = 0
        for ws in expired:
            try:
                import shutil
                if Path(ws.filesystem_root).exists():
                    shutil.rmtree(ws.filesystem_root, ignore_errors=True)
                ws.status = WorkspaceStatus.DELETED
                count += 1
            except OSError:
                continue
        await self.db.commit()
        logger.info("code.sweep", workspaces=count)
        return {"workspaces": count}



