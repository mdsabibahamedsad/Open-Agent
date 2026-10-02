"""Connector performance tests (MP21 §10).

Throughput and concurrency on mocked providers (no network): discovery,
validation, parallel execution, bounded pagination. Prints timings for the
implementation report.
"""

import asyncio
import time

from openagent.connectors import pagination as pagination_mod
from openagent.connectors.manifest import validate_manifest
from openagent.connectors.registry import ConnectorRegistry
from openagent.connectors.testing import MockProviderHTTP, mock_ctx, paged


def _manifest(connector_id: str):
    return {
        "id": connector_id, "name": connector_id.title(), "version": "1.0.0",
        "category": "automation", "type": "CUSTOM", "trust": "CUSTOM",
        "auth": {"type": "api_key"},
        "capabilities": [{"id": f"{connector_id}.items.read"}],
        "actions": [{"id": f"{connector_id}.list_items", "name": "List",
                     "input_schema": {"type": "object"},
                     "required_capabilities": [f"{connector_id}.items.read"],
                     "mutation": False}],
    }


def test_registry_scales():
    registry = ConnectorRegistry()
    for i in range(200):
        registry.register_manifest(_manifest(f"conn{i:03d}"))
    started = time.perf_counter()
    for _ in range(200):
        assert len(registry.search_actions("list items", limit=10)) == 10
    elapsed = time.perf_counter() - started
    print(f"\nregistry search: 200 queries over 200 connectors in {elapsed:.2f}s")
    assert elapsed < 10.0


def test_manifest_validation_throughput():
    raw = _manifest("acme")
    started = time.perf_counter()
    for _ in range(200):
        validate_manifest(raw)
    elapsed = time.perf_counter() - started
    print(f"\nmanifest validation: 200 in {elapsed:.2f}s")
    assert elapsed < 10.0


async def _run_mock_executions(count: int) -> float:
    from openagent.connectors.providers import github
    started = time.perf_counter()

    async def _one(_i: int):
        http = MockProviderHTTP()
        http.add("GET", "/repos", [{"id": 1, "full_name": "a/b"}])
        return await github.execute(
            "github.list_repos", {},
            {"secrets": {"access_token": "t"}}, mock_ctx(http))

    results = await asyncio.gather(*(_one(i) for i in range(count)))
    elapsed = time.perf_counter() - started
    assert all(r["status"] == "ok" for r in results)
    return elapsed


async def test_concurrent_executions():
    elapsed = await _run_mock_executions(100)
    print(f"\n100 concurrent mock executions in {elapsed:.2f}s")
    assert elapsed < 30.0


async def _collect_large():
    paginator = pagination_mod.Paginator(pagination_mod.PageSpec(
        strategy="cursor", cursor_param="cursor", cursor_path="next_cursor",
        items_path="items", max_items=500, max_pages=5, per_page=50))
    return await paginator.collect(paged([{"id": i} for i in range(1000)]))


async def test_large_evidence_set_bounded():
    result = await _collect_large()
    assert len(result.items) == 10  # 5 pages x fixture per_page=2
    assert result.pages_fetched == 5
    assert result.truncated is True
    print(f"\nbounded pagination: {len(result.items)} items, "
          f"{result.pages_fetched} pages, truncated={result.truncated}")
