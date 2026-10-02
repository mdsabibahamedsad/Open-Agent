import pytest
from httpx import ASGITransport, AsyncClient

from openagent.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health_check(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "openagent-api"


@pytest.mark.asyncio
async def test_readiness_check(client):
    response = await client.get("/api/v1/health/ready")
    # 200 when all dependencies answer, 503 when degraded (never 200
    # while degraded — load balancers must not route to a sick instance).
    assert response.status_code in (200, 503)
    data = response.json()
    assert data["service"] == "openagent-api"
    assert "checks" in data
    if response.status_code == 200:
        assert data["status"] == "ok"
        assert all(data["checks"].values())
    else:
        assert data["status"] == "degraded"
        assert not all(data["checks"].values())


@pytest.mark.asyncio
async def test_api_root(client):
    response = await client.get("/api/v1")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "OpenAgent API"
