"""MP26 unit: observability — redaction, correlation, SLI/budgets,
spans, platform events, failure-safe telemetry."""

import pytest

from openagent.control.observability import (
    STANDARD_SLIS, ErrorBudget, Telemetry, Tracer, bind_context,
    clear_context, get_context, log_event, platform_event, redact,
)


def setup_function(_):
    clear_context()


def test_redact_keys_and_values():
    payload = {"password": "hunter2", "nested": {"api_key": "x"},
               "note": "hello", "token": "sk-live-ABCDEFGH12345678"}
    clean = redact(payload)
    assert clean["password"] == "[REDACTED]"
    assert clean["nested"]["api_key"] == "[REDACTED]"
    assert clean["note"] == "hello"
    assert "ABCDEFGH" not in clean["token"]


def test_redact_private_keys_and_bearers():
    text = ("Authorization: Bearer abcdefgh12345678 and key "
            "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----")
    clean = redact(text)
    assert "abcdefgh" not in clean and "MIIB" not in clean
    assert "[REDACTED]" in clean


def test_log_event_redacted_with_correlation():
    bind_context(request_id="req_1", execution_id="cexe_1",
                 organization_id="org-1")
    record = log_event("worker", "execution.started",
                       execution_id="cexe_1", api_key="secret!")
    assert record["request_id"] == "req_1"
    assert record["api_key"] == "[REDACTED]"
    assert record["level"] == "INFO" and "timestamp" in record


def test_correlation_roundtrip():
    bind_context(request_id="r", trace_id="t", span_id="s")
    ctx = get_context()
    assert (ctx["request_id"], ctx["trace_id"]) == ("r", "t")
    clear_context()
    assert get_context() == {}


def test_sli_no_data_never_claims_met():
    sli = STANDARD_SLIS[0]
    result = sli.evaluate(0, 0)
    assert result["met"] is None and result["value"] is None


def test_sli_evaluation():
    sli = STANDARD_SLIS[0]
    assert sli.evaluate(999, 1000)["met"] is True
    assert sli.evaluate(900, 1000)["met"] is False


def test_error_budget():
    budget = ErrorBudget(slo_target=0.99)
    assert budget.allowed_error_ratio() == pytest.approx(0.01)
    fresh = budget.evaluate(999, 1000)
    assert not fresh["exhausted"] and fresh["remaining"] > 0
    blown = budget.evaluate(900, 1000)
    assert blown["exhausted"]


def test_spans_redact_attributes_and_time():
    tracer = Tracer()
    span = tracer.start("worker", "execute", api_key="sk-live-zzz")
    assert span.attributes["api_key"] == "[REDACTED]"
    span.finish(result="ok")
    body = span.to_dict()
    assert body["duration_ms"] >= 0 and body["service"] == "worker"


def test_platform_event_sanitized_and_typed():
    event = platform_event("incident.created", source="ops-api",
                           actor="u1", payload={"token": "x"})
    assert event["payload"] == {"token": "[REDACTED]"}
    assert event["event_id"].startswith("evt_")
    try:
        platform_event("bogus.event", source="x")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown event type must raise")


def test_telemetry_failure_safe():
    telemetry = Telemetry()
    telemetry.counter("api.request.count")
    telemetry.gauge("worker.count", 3)
    telemetry.observe("api.request.latency_seconds", 0.2)
    snapshot = telemetry.snapshot()
    assert snapshot["counters"] and snapshot["gauges"]["worker.count|[]"] == 3
    telemetry.disabled = True  # monitoring outage: silent no-op
    telemetry.counter("x")
    telemetry.gauge("y", 1)
    telemetry.observe("z", 2)
    assert telemetry.snapshot()["counters"] == snapshot["counters"]
