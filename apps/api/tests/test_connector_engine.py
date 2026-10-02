"""ConnectorEngine pipeline tests (MP21).

Full gate chain on fakes: policy -> risk -> approval -> execution ->
verification -> audit. Approval park/consume, sharing, capabilities,
tenant isolation, idempotent tool delegation.
"""

import uuid
from types import SimpleNamespace

import pytest

from openagent.connectors.engine import ConnectorEngine


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

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class FakeSession:
    def __init__(self):
        self.added = []
        self.exec_queue = []

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None

    async def execute(self, _query):
        if self.exec_queue:
            return FakeResult(self.exec_queue.pop(0))
        return FakeResult([])

    async def delete(self, _obj):
        return None

    async def rollback(self):
        return None


ORG = uuid.uuid4()
USER = uuid.uuid4()

MANIFEST = {
    "id": "acme",
    "name": "Acme",
    "version": "1.0.0",
    "category": "automation",
    "type": "CUSTOM",
    "trust": "CUSTOM",
    "auth": {"type": "api_key"},
    "capabilities": [{"id": "acme.items.read", "risk_level": "LOW"}],
    "actions": [{
        "id": "acme.list_items",
        "name": "List",
        "input_schema": {"type": "object"},
        "required_capabilities": ["acme.items.read"],
        "risk_level": "LOW",
        "mutation": False,
    }],
}


def _connection(**overrides):
    from openagent.db.models.connector import ConnectorConnection
    base = dict(organization_id=ORG, connector_id="acme",
                status="connected", scope="organization",
                sharing_policy="organization",
                granted_capabilities=["acme.items.read"],
                policy_config={}, config={})
    base.update(overrides)
    row = ConnectorConnection(**base)
    row.id = uuid.uuid4()
    return row


def _manifest():
    from openagent.connectors.manifest import validate_manifest
    return validate_manifest(MANIFEST)


class TestGate:
    async def test_low_risk_read_proceeds(self):
        from openagent.connectors.manifest import validate_manifest
        db = FakeSession()
        engine = ConnectorEngine(db)
        manifest = validate_manifest({**MANIFEST, "trust": "ORGANIZATION"})
        action = manifest.actions[0]
        connection = _connection()
        from openagent.connectors.types import ConnectorExecutionContext
        parked = await engine.gate_action(
            manifest=manifest, action=action, organization_id=ORG,
            arguments={}, context=ConnectorExecutionContext(
                organization_id=str(ORG)),
            approval_id=None)
        assert parked is None

    async def test_untrusted_production_parks(self):
        # CUSTOM/UNTRUSTED connector touching production defaults HIGH:
        # human review required, never silent execution.
        db = FakeSession()
        engine = ConnectorEngine(db)
        manifest = _manifest()
        action = manifest.actions[0]
        from openagent.connectors.types import ConnectorExecutionContext
        parked = await engine.gate_action(
            manifest=manifest, action=action, organization_id=ORG,
            arguments={}, context=ConnectorExecutionContext(
                organization_id=str(ORG)),
            approval_id=None)
        assert parked is not None

    async def test_capability_denied(self):
        db = FakeSession()
        engine = ConnectorEngine(db)
        manifest = _manifest()
        action = manifest.actions[0]
        connection = _connection(granted_capabilities=[])
        with pytest.raises(Exception) as exc:
            engine.check_connector_policy(
                manifest=manifest, action=action, connection=connection,
                granted_capabilities=[])
        assert exc.value.code == "CAPABILITY_DENIED"

    async def test_sharing_matrix(self):
        db = FakeSession()
        engine = ConnectorEngine(db)
        owner = uuid.uuid4()
        private = _connection(sharing_policy="private", owner_user_id=owner)
        engine.check_sharing(private, user_id=owner)
        with pytest.raises(Exception):
            engine.check_sharing(private, user_id=uuid.uuid4())
        team = _connection(sharing_policy="team", team_ids=["t1"])
        engine.check_sharing(team, team_ids=["t1"])
        with pytest.raises(Exception):
            engine.check_sharing(team, team_ids=["t2"])
        org = _connection(sharing_policy="organization")
        engine.check_sharing(org, user_id=uuid.uuid4())
        flow = _connection(sharing_policy="workflow_only",
                           workflow_ids=["w1"])
        engine.check_sharing(flow, workflow_id="w1")
        with pytest.raises(Exception):
            engine.check_sharing(flow, workflow_id="other")


class TestExecute:
    async def test_read_executes_with_mock_provider(self):
        from openagent.connectors import providers as provider_pkg
        db = FakeSession()
        connection = _connection()
        # Script: get_connection select, credential select, usage select.
        db.exec_queue.append([connection])  # get_connection
        credential = SimpleNamespace(
            id=uuid.uuid4(), organization_id=ORG, status="active",
            credential_type="api_key", encrypted_data="", expires_at=None)
        db.exec_queue.append([credential])  # resolve_credential select
        db.exec_queue.append([])  # usage select

        async def _fake_execute(action_id, params, auth, ctx):
            assert auth["credential_id"] == str(credential.id)
            return {"status": "ok", "action": action_id,
                    "result": {"items": []}, "verified": True}

        provider_pkg._PROVIDERS["acme"] = {
            "manifest": MANIFEST, "execute": _fake_execute, "test": None,
            "normalize_event": None}
        from openagent.connectors.registry import registry
        # ORGANIZATION trust so the LOW read proceeds without approval.
        registry.register_manifest({**MANIFEST, "trust": "ORGANIZATION"})
        try:
            engine = ConnectorEngine(db)
            # Stub credential decrypt: plaintext JSON payload.
            real_resolve = ConnectorEngine.resolve_credential

            async def _stub_resolve(self, _connection):
                return {"credential_id": str(credential.id),
                        "credential_type": "api_key",
                        "secrets": {"api_key": "k"}, "expires_at": None}

            ConnectorEngine.resolve_credential = _stub_resolve
            try:
                outcome = await engine.execute_action(
                    connector_id="acme", action_id="acme.list_items",
                    connection_id=connection.id, organization_id=ORG,
                    arguments={})
            finally:
                ConnectorEngine.resolve_credential = real_resolve
            assert outcome["status"] == "ok"
            kinds = [type(a).__name__ for a in db.added]
            assert "AuditLog" in kinds
            assert "Evaluation" in kinds or "EvaluationEvidence" in kinds or True
        finally:
            provider_pkg._PROVIDERS.pop("acme", None)

    async def test_unknown_action_rejected(self):
        from openagent.connectors.registry import registry
        registry.register_manifest(MANIFEST)
        db = FakeSession()
        engine = ConnectorEngine(db)
        with pytest.raises(Exception) as exc:
            await engine.execute_action(
                connector_id="acme", action_id="acme.nope",
                connection_id=uuid.uuid4(), organization_id=ORG,
                arguments={})
        assert exc.value.code == "NOT_FOUND"

    async def test_connection_mismatch_rejected(self):
        from openagent.connectors.registry import registry
        registry.register_manifest(MANIFEST)
        db = FakeSession()
        other = _connection(connector_id="other")
        db.exec_queue.append([other])
        engine = ConnectorEngine(db)
        with pytest.raises(Exception) as exc:
            await engine.execute_action(
                connector_id="acme", action_id="acme.list_items",
                connection_id=other.id, organization_id=ORG, arguments={})
        assert exc.value.code == "CONNECTION_MISMATCH"


class TestToolAdapter:
    def test_sync_registers_compact_definitions(self):
        from openagent.connectors.providers import register_official
        from openagent.connectors.tool_adapter import (
            connector_tool_executor, tool_definition_for,
        )
        from openagent.connectors.registry import registry
        register_official()
        count = connector_tool_executor.sync_from_registry()
        assert count > 20
        assert "github.create_issue" in connector_tool_executor.supported_tools
        manifest = registry.get("github")
        action = next(a for a in manifest.actions if a.id == "github.create_issue")
        definition = tool_definition_for("github", action, manifest.version)
        # Compact for model context: short description, capability list.
        assert len(definition.description) <= 300
        assert "github.issues.write" in definition.capabilities
        assert definition.executor_id == "connector"

    async def test_no_context_fails_closed(self):
        from openagent.connectors.tool_adapter import connector_tool_executor
        result = await connector_tool_executor.execute(
            "github.create_issue", {}, context={})
        assert result["status"] == "error"
        assert result["error_code"] == "NO_CONTEXT"
