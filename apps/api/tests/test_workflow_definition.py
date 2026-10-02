"""Unit tests for workflow definition validation (no DB required)."""

from openagent.services.workflow_definition import (
    build_envelope,
    extract_expressions,
    migrate_definition,
    parse_envelope,
    validate_definition,
    empty_definition,
    slugify,
)


def _valid_definition():
    return {
        "schema_version": "1.0",
        "triggers": [
            {"id": "trg_1", "type": "manual", "name": "Run manually", "config": {}}
        ],
        "nodes": [
            {"id": "n_1", "type": "agent", "name": "Triage",
             "position": {"x": 120, "y": 80},
             "config": {"agent_id": "00000000-0000-0000-0000-000000000000"}},
            {"id": "n_2", "type": "condition", "name": "Urgent?",
             "position": {"x": 360, "y": 80},
             "config": {"expression": "priority == 'high'"}},
        ],
        "edges": [
            {"id": "e_1", "from": "trg_1", "to": "n_1",
             "condition": {"when": "always"}},
            {"id": "e_2", "from": "n_1", "to": "n_2",
             "condition": {"when": "success"}},
        ],
        "variables": [
            {"name": "ticket_id", "type": "string", "required": True},
        ],
        "settings": {},
    }


def test_valid_definition_passes():
    result = validate_definition(_valid_definition())
    assert result.valid is True
    assert result.errors == []


def test_non_object_definition_rejected():
    result = validate_definition(["not", "an", "object"])
    assert result.valid is False
    assert any(e.code == "INVALID_DEFINITION" for e in result.errors)


def test_missing_trigger_rejected():
    d = _valid_definition()
    d["triggers"] = []
    d["edges"] = [e for e in d["edges"] if e["from"] != "trg_1"]
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "NO_TRIGGER" for e in result.errors)


def test_unknown_node_type_rejected():
    d = _valid_definition()
    d["nodes"][0]["type"] = "teleport"
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "UNKNOWN_NODE_TYPE" for e in result.errors)


def test_duplicate_ids_rejected():
    d = _valid_definition()
    d["nodes"][1]["id"] = "n_1"
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "DUPLICATE_ID" for e in result.errors)


def test_self_loop_rejected():
    d = _valid_definition()
    d["edges"].append({"id": "e_x", "from": "n_1", "to": "n_1"})
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "SELF_LOOP" for e in result.errors)


def test_cycle_rejected():
    d = _valid_definition()
    d["edges"].append({"id": "e_x", "from": "n_2", "to": "n_1"})
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "CYCLE_DETECTED" for e in result.errors)


def test_edge_into_trigger_rejected():
    d = _valid_definition()
    d["edges"].append({"id": "e_x", "from": "n_2", "to": "trg_1"})
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "EDGE_INTO_TRIGGER" for e in result.errors)


def test_unknown_edge_endpoint_rejected():
    d = _valid_definition()
    d["edges"].append({"id": "e_x", "from": "n_2", "to": "ghost"})
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "UNKNOWN_EDGE_TARGET" for e in result.errors)


def test_unreachable_node_rejected():
    d = _valid_definition()
    d["nodes"].append({"id": "n_9", "type": "delay", "name": "Wait",
                        "config": {"duration_seconds": 5}})
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "UNREACHABLE_NODE" for e in result.errors)


def test_agent_node_requires_reference():
    d = _valid_definition()
    d["nodes"][0]["config"] = {}
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "NODE_CONFIG_REQUIRED" for e in result.errors)


def test_webhook_trigger_requires_path():
    d = _valid_definition()
    d["triggers"][0] = {"id": "trg_1", "type": "webhook", "name": "Hook", "config": {}}
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "TRIGGER_CONFIG_REQUIRED" for e in result.errors)


def test_invalid_variable_name_rejected():
    d = _valid_definition()
    d["variables"].append({"name": "9bad", "type": "string"})
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "INVALID_VARIABLE_NAME" for e in result.errors)


def test_trigger_without_edges_warns():
    d = _valid_definition()
    d["triggers"].append({"id": "trg_2", "type": "manual", "name": "Extra", "config": {}})
    result = validate_definition(d)
    assert result.valid is True
    assert any(w.code == "TRIGGER_WITHOUT_EDGES" for w in result.warnings)


def test_unsupported_schema_version_rejected():
    d = _valid_definition()
    d["schema_version"] = "9.9"
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "UNSUPPORTED_SCHEMA_VERSION" for e in result.errors)


def test_empty_definition_helper_shape():
    d = empty_definition()
    assert d["schema_version"] == "1.0"
    assert d["triggers"] == [] and d["nodes"] == [] and d["edges"] == []


def test_slugify():
    assert slugify("Support Triage Flow!") == "support-triage-flow"
    assert slugify("!!!") == "workflow"


def test_new_node_types_validate():
    d = _valid_definition()
    d["nodes"].extend([
        {"id": "n_sw", "type": "switch", "name": "Route",
         "config": {"routes": [{"name": "vip", "expression": "tier == 'vip'"}]}},
        {"id": "n_mg", "type": "merge", "name": "Join", "config": {}},
        {"id": "n_set", "type": "set", "name": "Defaults",
         "config": {"values": {"region": "eu"}}},
        {"id": "n_pr", "type": "prompt", "name": "Summarize",
         "config": {"prompt": "Summarize {{ticket_id}}", "model": "default"}},
        {"id": "n_sub", "type": "subworkflow", "name": "Child",
         "config": {"workflow_id": "00000000-0000-0000-0000-000000000001"}},
    ])
    d["edges"].extend([
        {"id": "e_3", "from": "n_2", "to": "n_sw", "label": "true"},
        {"id": "e_4", "from": "n_sw", "to": "n_mg", "label": "vip"},
        {"id": "e_5", "from": "n_2", "to": "n_mg", "label": "false"},
        {"id": "e_6", "from": "n_mg", "to": "n_set"},
        {"id": "e_7", "from": "n_set", "to": "n_pr"},
        {"id": "e_8", "from": "n_pr", "to": "n_sub"},
    ])
    result = validate_definition(d)
    assert result.valid is True, [e.message for e in result.errors]
    assert result.errors == []


def test_switch_requires_routes():
    d = _valid_definition()
    d["nodes"].append({"id": "n_sw", "type": "switch", "name": "Route", "config": {}})
    d["edges"].append({"id": "e_x", "from": "n_2", "to": "n_sw", "label": "true"})
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "NODE_CONFIG_REQUIRED" for e in result.errors)


def test_prompt_requires_model():
    d = _valid_definition()
    d["nodes"].append({"id": "n_p", "type": "prompt", "name": "Ask",
                        "config": {"prompt": "hi"}})
    d["edges"].append({"id": "e_x", "from": "n_2", "to": "n_p", "label": "true"})
    result = validate_definition(d)
    assert any(e.code == "NODE_CONFIG_REQUIRED" for e in result.errors)


def test_literal_secret_rejected():
    d = _valid_definition()
    d["nodes"][0]["config"]["api_key"] = "sk-live-abc123"
    result = validate_definition(d)
    assert result.valid is False
    assert any(e.code == "SECRET_VALUE" for e in result.errors)


def test_secret_reference_allowed():
    d = _valid_definition()
    d["nodes"][0]["config"]["api_key"] = "{{credentials.openai}}"
    d["nodes"].append({"id": "n_c", "type": "tool", "name": "Call",
                        "config": {"tool_id": "t", "credential_id": "some-id"}})
    d["edges"].append({"id": "e_x", "from": "n_2", "to": "n_c", "label": "true"})
    result = validate_definition(d)
    assert not any(e.code == "SECRET_VALUE" for e in result.errors)


def test_disabled_nodes_skip_config_and_reachability():
    d = _valid_definition()
    d["nodes"].append({"id": "n_off", "type": "agent", "name": "Paused",
                        "disabled": True, "config": {}})
    result = validate_definition(d)
    assert result.valid is True
    assert not any(e.node_id == "n_off" for e in result.errors)


def test_multiple_inbound_rejected_except_merge():
    d = _valid_definition()
    d["edges"].append({"id": "e_x", "from": "n_2", "to": "n_1", "label": "true"})
    result = validate_definition(d)
    assert any(e.code == "MULTIPLE_INBOUND_EDGES" for e in result.errors)
    # Cycles also trigger here; the cardinality error must be present regardless.


def test_expression_reference_warnings():
    d = _valid_definition()
    d["nodes"][0]["config"]["task"] = "Handle {{variables.nope}} via {{nodes.ghost.output}}"
    result = validate_definition(d)
    assert result.valid is True  # advisory only
    assert any(w.code == "UNKNOWN_VARIABLE_REFERENCE" for w in result.warnings)
    assert any(w.code == "UNKNOWN_NODE_REFERENCE" for w in result.warnings)


def test_unused_variable_warns():
    result = validate_definition(_valid_definition())
    assert any(w.code == "UNUSED_VARIABLE" for w in result.warnings)


def test_extract_expressions():
    assert extract_expressions({"a": "Hi {{variables.x}}", "b": ["{{nodes.n.output}}", 1]}) == [
        "variables.x", "nodes.n.output",
    ]
    assert extract_expressions({}) == []


def test_validation_issues_carry_severity():
    result = validate_definition(["nope"])
    d = result.to_dict()
    assert d["errors"][0]["severity"] == "error"
    ok = validate_definition(_valid_definition())
    assert all(i["severity"] == "warning" for i in ok.to_dict()["warnings"])


def test_migrate_current_version_passes_through():
    d = _valid_definition()
    out, migrated, error = migrate_definition(d)
    assert error is None and migrated is False and out is d


def test_migrate_unknown_version_errors():
    _, _, error = migrate_definition({"schema_version": "9.9"})
    assert error is not None


def test_envelope_round_trip():
    d = _valid_definition()
    env = build_envelope("Triage", "triage", "desc", ["support"], d)
    assert env["format"] == "openagent-workflow"
    assert env["schemaVersion"] == "1.0"
    parsed, error = parse_envelope(env)
    assert error is None
    assert parsed["definition"] == d
    assert parsed["meta"]["name"] == "Triage"
    assert parsed["meta"]["tags"] == ["support"]


def test_parse_envelope_accepts_raw_definition():
    parsed, error = parse_envelope(_valid_definition())
    assert error is None
    assert parsed["definition"]["schema_version"] == "1.0"


def test_parse_envelope_rejects_garbage():
    parsed, error = parse_envelope({"nope": True})
    assert parsed is None and error is not None
