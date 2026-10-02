import pytest
from httpx import AsyncClient, ASGITransport
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
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ok", "degraded"]
    assert data["service"] == "openagent-api"
    assert "checks" in data


@pytest.mark.asyncio
async def test_api_root(client):
    response = await client.get("/api/v1")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "OpenAgent API"