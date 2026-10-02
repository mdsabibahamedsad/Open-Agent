import httpx
import pytest

from openagent import AsyncOpenAgent, NotFoundError, OpenAgent, RateLimitError
from openagent.types_ import PaginatedResult


def make_sync_client(handler, org="org_123"):
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url="http://test")
    return OpenAgent(
        api_key="sk_test", organization_id=org, http_client=http_client
    )


def make_async_client(handler, org="org_123"):
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return AsyncOpenAgent(
        api_key="sk_test", organization_id=org, http_client=http_client
    )


def test_auth_and_org_headers_sent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["org"] = request.headers.get("x-organization-id")
        seen["rid"] = request.headers.get("x-request-id")
        return httpx.Response(200, json={"id": "a1"})

    client = make_sync_client(handler)
    client.agents.get("a1")
    assert seen["auth"] == "Bearer sk_test"
    assert seen["org"] == "org_123"
    assert seen["rid"]
    client.close()


def test_404_raises_not_found_with_request_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "missing"}},
            headers={"x-request-id": "req_1"},
        )

    client = make_sync_client(handler)
    with pytest.raises(NotFoundError) as excinfo:
        client.agents.get("missing")
    assert excinfo.value.request_id == "req_1"
    client.close()


def test_429_raises_rate_limit_with_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"code": "RATE_LIMITED", "message": "slow"}},
            headers={"retry-after": "2"},
        )

    # max_retries=0 so the 429 surfaces immediately
    transport = httpx.MockTransport(handler)
    client = OpenAgent(
        api_key="sk_test",
        organization_id="org_123",
        max_retries=0,
        http_client=httpx.Client(transport=transport, base_url="http://test"),
    )
    with pytest.raises(RateLimitError) as excinfo:
        client.agents.list()
    assert excinfo.value.retry_after == 2.0
    client.close()


def test_idempotency_header_sent_on_create():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["idem"] = request.headers.get("idempotency-key")
        seen["method"] = request.method
        return httpx.Response(201, json={"id": "a9", "name": "x"})

    client = make_sync_client(handler)
    client.agents.create("x", idempotency_key="key-1")
    assert seen["idem"] == "key-1"
    assert seen["method"] == "POST"
    client.close()


def test_pagination_iterator_follows_cursor():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        calls.append(cursor)
        if cursor is None:
            return httpx.Response(
                200, json={"items": [{"id": "1"}], "next_cursor": "c2"}
            )
        return httpx.Response(200, json={"items": [{"id": "2"}]})

    client = make_sync_client(handler)
    items = list(client.agents.iterate())
    assert [i["id"] for i in items] == ["1", "2"]
    assert calls == [None, "c2"]
    page = client.agents.list()
    assert isinstance(page, PaginatedResult)
    client.close()


def test_base_url_normalized_to_api_v1():
    client = OpenAgent(api_key="sk_test", base_url="http://localhost:8000/")
    assert client.base_url == "http://localhost:8000/api/v1"
    client.close()
    client2 = OpenAgent(api_key="sk_test", base_url="http://localhost:8000/api/v1")
    assert client2.base_url == "http://localhost:8000/api/v1"
    client2.close()


async def test_async_client_crud_and_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk_test"
        assert request.headers["x-organization-id"] == "org_123"
        if request.url.path.endswith("/agents") and request.method == "POST":
            assert request.headers.get("idempotency-key") == "k1"
            return httpx.Response(201, json={"id": "a1"})
        return httpx.Response(
            404, json={"error": {"code": "NOT_FOUND", "message": "missing"}}
        )

    client = make_async_client(handler)
    created = await client.agents.create("n", idempotency_key="k1")
    assert created["id"] == "a1"
    with pytest.raises(NotFoundError):
        await client.agents.get("missing")
    await client.aclose()


async def test_async_pagination_iterator():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "c2":
            return httpx.Response(200, json={"items": [{"id": "2"}]})
        return httpx.Response(200, json={"items": [{"id": "1"}], "next_cursor": "c2"})

    client = make_async_client(handler)
    ids = [item["id"] async for item in client.agents.iterate()]
    assert ids == ["1", "2"]
    await client.aclose()
