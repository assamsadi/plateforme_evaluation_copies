"""
Integration tests for core API routes — health check and auth guard.
Uses AnyIO runner to avoid pytest-asyncio compatibility issues.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture
def anyio_backend():
    return "asyncio"

@pytest.mark.anyio
async def test_health_check():
    """The /health endpoint is public and always returns 200."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
