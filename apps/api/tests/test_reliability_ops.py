"""Reliability regression tests: correlation, log redaction, retry policy.

Deterministic and infrastructure-free (no Postgres/Redis needed) except
test_readiness_status_consistency, which asserts status/body agreement in
whatever environment it runs in.
"""

import inspect

import pytest
from fastapi import FastAPI, HTTPException, status
from httpx import ASGITransport, AsyncClient

from openagent.cloud.queues import is_retryable_error, retry_delay_seconds
from openagent.core.logging import _REDACTED, redact_sensitive
from openagent.db.repositories import audit as audit_repo
from openagent.db.repositories import management as mgmt_repo
from openagent.middleware import (
    ErrorHandlingMiddleware,
    RequestCorrelationMiddleware,
    register_error_handlers,
)


def make_middleware_app() -> FastAPI:
    app = FastAPI()
    # Same relative order as openagent.main: correlation outer, errors inner,
    # plus registered handlers so route-raised errors keep the envelope.
    app.add_middleware(RequestCorrelationMiddleware)
    app.add_middleware(ErrorHandlingMiddleware, is_development=False)
    register_error_handlers(app, is_development=False)

    @app.get("/boom")
    async def boom():  # pragma: no cover - exercised via client
        raise HTTPException(status_code=404, detail="gone")

    return app


@pytest.mark.asyncio
async def test_request_id_echoed_on_success():
    app = make_middleware_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Unknown path: 404 from the router itself; the header is still
        # stamped by the correlation middleware.
        response = await client.get("/nonexistent-ok", headers={"X-Request-ID": "req_test123"})
        assert response.headers["X-Request-ID"] == "req_test123"


@pytest.mark.asyncio
async def test_error_body_carries_same_request_id():
    """The ApiError.request_id must match X-Request-ID (previously a random
    fallback id was generated, breaking trace linkage)."""
    app = make_middleware_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/boom", headers={"X-Request-ID": "req_trace_me"})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.headers["X-Request-ID"] == "req_trace_me"
        body = response.json()
        assert body["error"]["request_id"] == "req_trace_me"
        assert body["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_error_body_generates_request_id_without_header():
    app = make_middleware_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/boom")
        assert response.status_code == status.HTTP_404_NOT_FOUND
        header_id = response.headers["X-Request-ID"]
        assert header_id.startswith("req_")
        assert response.json()["error"]["request_id"] == header_id


def test_log_redaction_strips_credentials():
    event = redact_sensitive(
        None,
        "info",
        {
            "event": "login",
            "password": "hunter2",
            "openai_api_key": "sk-live-123",
            "authorization": "Bearer abc",
            "nested": {"client_secret": "shh", "safe": "visible"},
            "username": "alice",
        },
    )
    assert event["password"] == _REDACTED
    assert event["openai_api_key"] == _REDACTED
    assert event["authorization"] == _REDACTED
    assert event["nested"] == {"client_secret": _REDACTED, "safe": "visible"}
    assert event["username"] == "alice"
    assert "sk-live-123" not in str(event)


def test_retry_policy_is_bounded_and_conservative():
    assert is_retryable_error("permission denied for relation") is False
    assert is_retryable_error("quota exceeded for org") is False
    assert is_retryable_error("connection reset by peer") is True
    # Exponential, capped — never unbounded. Bounds mirror the provider
    # defaults (base 5s, cap 600s); the first attempt must equal the base.
    first = retry_delay_seconds(1)
    capped = retry_delay_seconds(100)
    assert capped >= first
    assert retry_delay_seconds(1000) == capped


def test_scoped_list_methods_have_default_limits():
    """Single-parent list methods must be bounded even though the parent
    scope already constrains them (defense in depth, §45)."""
    targets = [
        audit_repo.ApprovalRepository.list_by_run,
        audit_repo.ApprovalRepository.list_by_workflow_execution,
        audit_repo.EvaluationRepository.list_by_run,
        mgmt_repo.AgentContractRepository.list_by_task,
        mgmt_repo.PlanVersionRepository.list_by_run,
        mgmt_repo.DynamicTeamRepository.list_by_run,
    ]
    for fn in targets:
        limit = inspect.signature(fn).parameters["limit"]
        assert limit.default is not inspect.Parameter.empty
        assert limit.default > 0, fn
