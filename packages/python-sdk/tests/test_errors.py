import pytest

from openagent.errors import (
    ApprovalRequiredError,
    AuthenticationError,
    AuthorizationError,
    CompatibilityError,
    ConflictError,
    ConnectorError,
    DeploymentError,
    ExtensionError,
    MCPError,
    NotFoundError,
    OpenAgentError,
    PolicyDeniedError,
    RateLimitError,
    SandboxError,
    TimeoutError,
    ToolExecutionError,
    ValidationError,
    from_response,
)


def test_401_maps_to_authentication_error():
    err = from_response(
        401, {"error": {"code": "AUTHENTICATION_ERROR", "message": "bad key"}}, "r1"
    )
    assert isinstance(err, AuthenticationError)
    assert err.request_id == "r1"
    assert err.message == "bad key"


def test_404_maps_to_not_found():
    err = from_response(404, {"error": {"code": "NOT_FOUND", "message": "nope"}}, "r2")
    assert isinstance(err, NotFoundError)
    assert err.details["http_status"] == 404


def test_429_maps_to_rate_limit_with_metadata():
    err = from_response(
        429,
        {"error": {"code": "RATE_LIMITED", "message": "slow down"}},
        "r3",
        retry_after=2.0,
        rate_limit={"x-ratelimit-remaining": "0"},
    )
    assert isinstance(err, RateLimitError)
    assert err.retry_after == 2.0
    assert err.rate_limit["x-ratelimit-remaining"] == "0"


def test_detail_shape_supported():
    err = from_response(422, {"detail": "field required"}, "r4")
    assert isinstance(err, ValidationError)
    assert err.message == "field required"


def test_detail_list_shape_supported():
    err = from_response(
        422, {"detail": [{"loc": ["body", "name"], "msg": "missing"}]}, "r5"
    )
    assert isinstance(err, ValidationError)
    assert "name" in err.message


def test_code_drives_subclass_on_shared_status():
    err = from_response(
        403, {"error": {"code": "POLICY_DENIED", "message": "denied"}}, ""
    )
    assert isinstance(err, PolicyDeniedError)
    err2 = from_response(
        403, {"error": {"code": "APPROVAL_REQUIRED", "message": "needs approval"}}, ""
    )
    assert isinstance(err2, ApprovalRequiredError)
    err3 = from_response(403, {"detail": "forbidden"}, "")
    assert isinstance(err3, AuthorizationError)


def test_502_code_mapping():
    assert isinstance(
        from_response(502, {"error": {"code": "CONNECTOR_ERROR", "message": "x"}}, ""), ConnectorError
    )
    assert isinstance(
        from_response(502, {"error": {"code": "MCP_ERROR", "message": "x"}}, ""), MCPError
    )
    assert isinstance(
        from_response(502, {"error": {"code": "SANDBOX_ERROR", "message": "x"}}, ""), SandboxError
    )
    assert isinstance(
        from_response(502, {"error": {"code": "TOOL_EXECUTION_ERROR", "message": "x"}}, ""),
        ToolExecutionError,
    )
    assert isinstance(
        from_response(502, {"error": {"code": "DEPLOYMENT_ERROR", "message": "x"}}, ""),
        DeploymentError,
    )


def test_422_code_mapping():
    assert isinstance(
        from_response(422, {"error": {"code": "COMPATIBILITY_ERROR", "message": "x"}}, ""),
        CompatibilityError,
    )
    assert isinstance(
        from_response(422, {"error": {"code": "EXTENSION_ERROR", "message": "x"}}, ""),
        ExtensionError,
    )


def test_409_and_504_and_unknown():
    assert isinstance(from_response(409, {"detail": "dup"}, ""), ConflictError)
    assert isinstance(from_response(504, {"detail": "slow"}, ""), TimeoutError)
    err = from_response(500, {"error": {"code": "NOPE", "message": "weird"}}, "r9")
    assert isinstance(err, OpenAgentError)
    assert err.details["code"] == "NOPE"


def test_messages_are_truncated_and_safe():
    err = from_response(400, {"detail": "x" * 5000}, "")
    assert len(err.message) <= 503
