"""Sandbox manager tests: lifecycle, gated execution, leases, quotas, sweep.

Uses an in-memory FakeSession + FakeProvider (no database, no daemon).
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from openagent.db.models.sandbox import (
    Sandbox,
    SandboxExecution,
    SandboxExecutionStatus,
    SandboxLease,
    SandboxStatus,
)
from openagent.sandbox.config import SandboxSettings
from openagent.sandbox.providers import ExecutionOutcome, ExecutionSpec
from openagent.sandbox.service import (
    SandboxManager,
    SandboxNotFound,
    SandboxPolicyDenied,
)

ORG = uuid.uuid4()
ACTOR = uuid.uuid4()
SECRET = "ghp_" + "x" * 36


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return FakeScalars(self._items)


class FakeSession:
    """Minimal AsyncSession stand-in with scripted reads."""

    def __init__(self):
        self.added = []
        self.deleted = []
        self.commits = 0
        self.scalar_queue = []
        self.exec_queue = []

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None

    async def scalar(self, query):
        if self.scalar_queue:
            return self.scalar_queue.pop(0)
        return None

    async def execute(self, query):
        if self.exec_queue:
            return FakeResult(self.exec_queue.pop(0))
        return FakeResult([])


class FakeStored:
    def __init__(self, key):
        self.key = key


class FakeStorage:
    def __init__(self):
        self.uploads = {}

    async def upload(self, key, file, content_type, filename, metadata=None):
        self.uploads[key] = file.read()
        return FakeStored(key)

    async def delete(self, key):
        self.uploads.pop(key, None)
        return True


class FakeProvider:
    provider_name = "docker"

    def __init__(self, outcome=None):
        self.calls = []
        self.outcome = outcome or ExecutionOutcome(
            exit_code=0, stdout="ok\n", stderr="", duration_ms=12)

    async def create(self, spec):
        self.calls.append(("create", spec))
        return "fake-container-1"

    async def start(self, handle):
        self.calls.append(("start", handle))

    async def execute(self, handle, spec: ExecutionSpec):
        self.calls.append(("execute", handle, spec))
        return self.outcome

    async def stop(self, handle, timeout_seconds=10):
        self.calls.append(("stop", handle))

    async def destroy(self, handle):
        self.calls.append(("destroy", handle))

    async def inspect(self, handle):
        return {"handle": handle, "available": True, "privileged": False}


def _settings(**kw):
    s = SandboxSettings(provider="docker")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _sandbox(**kw):
    now = datetime.now(timezone.utc)
    sb = Sandbox(
        sandbox_id="sbx_test_1", organization_id=ORG, owner_id=ACTOR,
        profile="TEST", status=SandboxStatus.READY,
        provider_handle="fake-container-1", image="openagent-sandbox-base",
        expires_at=now + timedelta(hours=1),
        resource_config={}, mounts=[{"host": "/tmp/ws", "container": "/workspace",
                                     "read_only": False}],
        meta={})
    for k, v in kw.items():
        setattr(sb, k, v)
    return sb


def _manager(db, provider=None, **kw):
    return SandboxManager(db, storage=FakeStorage(),
                          settings=_settings(), provider=provider or FakeProvider(),
                          **kw)


class TestLifecycle:
    async def test_create_start_stop_destroy(self):
        db = FakeSession()
        db.scalar_queue = [None, 0]  # profile overlay, sandbox count
        mgr = _manager(db)
        sb = await mgr.create_sandbox(organization_id=ORG, profile="TEST",
                                      owner_id=ACTOR)
        assert sb.status == SandboxStatus.CREATED
        assert sb.provider_handle == "fake-container-1"

        db.scalar_queue = [sb]
        sb = await mgr.start_sandbox(sb.id, ORG, ACTOR)
        assert sb.status == SandboxStatus.READY

        db.scalar_queue = [sb]
        sb = await mgr.stop_sandbox(sb.id, ORG, ACTOR)
        assert sb.status == SandboxStatus.STOPPED

        db.scalar_queue = [sb]
        db.exec_queue = [[]]
        await mgr.destroy_sandbox(sb.id, ORG, ACTOR)
        assert sb.status == SandboxStatus.DESTROYED
        assert db.commits >= 4

    async def test_quota_enforced(self):
        db = FakeSession()
        db.scalar_queue = [None, 99]
        mgr = _manager(db)
        with pytest.raises(SandboxPolicyDenied):
            await mgr.create_sandbox(organization_id=ORG, profile="TEST")

    async def test_workspace_mount_outside_root_denied(self, tmp_path):
        db = FakeSession()
        db.scalar_queue = [None, 0]
        mgr = _manager(db)
        mgr._settings.workspace_root = str(tmp_path / "root")
        with pytest.raises(Exception):
            await mgr.create_sandbox(
                organization_id=ORG, profile="TEST",
                workspace_host_path="/etc")


class TestGatedExecution:
    async def test_success_and_redaction(self):
        leak = f"leaked {SECRET} done"
        provider = FakeProvider(ExecutionOutcome(
            exit_code=0, stdout=leak, stderr="", duration_ms=5))
        db = FakeSession()
        sb = _sandbox()
        db.scalar_queue = [sb, 0, None]
        db.exec_queue = [[]]
        mgr = _manager(db, provider)
        res = await mgr.execute(sandbox_id=sb.id, organization_id=ORG,
                                command="pytest tests/ -q", workdir="/workspace")
        assert res["status"] == "SUCCEEDED"
        assert SECRET not in (res["stdout_tail"] or "")
        assert "[REDACTED]" in (res["stdout_tail"] or "")
        assert res["stdout_ref"]  # full output lives behind a storage ref
        assert res["stderr_ref"] is None  # empty stderr stores nothing
        assert db.commits >= 1

    async def test_disallowed_command_denied(self):
        db = FakeSession()
        sb = _sandbox()
        db.scalar_queue = [sb, 0, None]
        db.exec_queue = [[]]
        mgr = _manager(db)
        res = await mgr.execute(sandbox_id=sb.id, organization_id=ORG,
                                command="curl http://169.254.169.254/",
                                workdir="/workspace")
        assert res["status"] == "POLICY_DENIED"

    async def test_shell_operators_denied(self):
        db = FakeSession()
        sb = _sandbox()
        db.scalar_queue = [sb, 0, None]
        db.exec_queue = [[]]
        mgr = _manager(db)
        res = await mgr.execute(sandbox_id=sb.id, organization_id=ORG,
                                command="pytest tests/ && rm -rf /",
                                workdir="/workspace")
        assert res["status"] == "POLICY_DENIED"

    async def test_workdir_escape_denied(self):
        db = FakeSession()
        sb = _sandbox()
        db.scalar_queue = [sb, 0, None]
        db.exec_queue = [[]]
        mgr = _manager(db)
        res = await mgr.execute(sandbox_id=sb.id, organization_id=ORG,
                                command="pytest -q", workdir="/etc")
        assert res["status"] == "POLICY_DENIED"

    async def test_credentialed_run_parks_for_approval(self):
        async def _resolver(ref):
            return "s3cr3t"
        db = FakeSession()
        sb = _sandbox()
        db.scalar_queue = [sb, 0, None]
        db.exec_queue = [[]]
        mgr = _manager(db, credential_resolver=_resolver)
        res = await mgr.execute(
            sandbox_id=sb.id, organization_id=ORG, command="pytest -q",
            workdir="/workspace", credential_refs={"GITHUB_TOKEN": "cred_1"})
        assert res["status"] == "WAITING_FOR_APPROVAL"
        assert res["risk_level"] in ("HIGH", "CRITICAL")

    async def test_credential_without_resolver_denied(self):
        db = FakeSession()
        sb = _sandbox()
        db.scalar_queue = [sb, 0, None]
        db.exec_queue = [[]]
        mgr = _manager(db)
        res = await mgr.execute(
            sandbox_id=sb.id, organization_id=ORG, command="pytest -q",
            workdir="/workspace", credential_refs={"GITHUB_TOKEN": "cred_1"})
        assert res["status"] == "POLICY_DENIED"

    async def test_lease_conflict(self):
        db = FakeSession()
        sb = _sandbox()
        lease = SandboxLease(
            sandbox_id=sb.id, organization_id=ORG, owner="other-agent",
            acquired_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
        db.scalar_queue = [sb]
        db.exec_queue = [[lease]]
        mgr = _manager(db)
        with pytest.raises(SandboxPolicyDenied):
            await mgr.execute(sandbox_id=sb.id, organization_id=ORG,
                              command="pytest -q", owner="me")

    async def test_concurrent_quota(self):
        db = FakeSession()
        sb = _sandbox()
        db.scalar_queue = [sb, 10]
        mgr = SandboxManager(db, storage=FakeStorage(),
                             settings=_settings(max_concurrent_executions_per_org=10),
                             provider=FakeProvider())
        with pytest.raises(SandboxPolicyDenied):
            await mgr.execute(sandbox_id=sb.id, organization_id=ORG,
                              command="pytest -q")

    async def test_not_found(self):
        db = FakeSession()
        mgr = _manager(db)
        with pytest.raises(SandboxNotFound):
            await mgr.get_sandbox(uuid.uuid4(), ORG)


class TestCancelAndSweep:
    async def test_cancel_marks_cancelled(self):
        db = FakeSession()
        sb = _sandbox()
        ex = SandboxExecution(
            execution_id="exe_1", organization_id=ORG, sandbox_id=sb.id,
            command="pytest", workdir="/workspace", profile="TEST",
            status=SandboxExecutionStatus.RUNNING)
        db.scalar_queue = [ex, sb]
        mgr = _manager(db)
        res = await mgr.cancel_execution(ex.id, ORG, ACTOR)
        assert res["status"] == "CANCELLED"

    async def test_sweep_reaps_expired(self):
        db = FakeSession()
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        sb = _sandbox(status=SandboxStatus.READY, expires_at=past,
                      provider_handle="fake-container-1")
        db.exec_queue = [[sb], [], [], []]
        mgr = _manager(db)
        counts = await mgr.sweep()
        assert counts["sandboxes"] == 1
        assert sb.status == SandboxStatus.EXPIRED
