"""
Integration tests for Programs & Modules routes.
Demonstrates the nominal test pattern: authenticated client + mocked service.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.academic_schemas import ProgramRead, ModuleRead


# ── Programs ─────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_programs(admin_client, mock_program_service):
    """GET /programs returns a paginated list."""
    prog_id = uuid.uuid4()
    mock_program_service.list_page.return_value = CursorPage(
        items=[ProgramRead(id=prog_id, name="Informatique", code="INFO")],
        next_cursor=None,
        has_more=False,
    )
    response = await admin_client.get("/api/v1/programs")
    assert response.status_code == 200
    data = response.json()
    assert data["has_more"] is False
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "Informatique"


@pytest.mark.anyio
async def test_get_program_by_id(admin_client, mock_program_service):
    """GET /programs/{id} returns a single program."""
    prog_id = uuid.uuid4()
    mock_program_service.get_by_id.return_value = ProgramRead(
        id=prog_id, name="Mathématiques", code="MATH"
    )
    response = await admin_client.get(f"/api/v1/programs/{prog_id}")
    assert response.status_code == 200
    assert response.json()["code"] == "MATH"


@pytest.mark.anyio
async def test_create_program_as_admin(admin_client, mock_program_service):
    """POST /programs as admin returns 201."""
    prog_id = uuid.uuid4()
    mock_program_service.create.return_value = ProgramRead(
        id=prog_id, name="Physique", code="PHY"
    )
    response = await admin_client.post("/api/v1/programs", json={
        "name": "Physique",
        "code": "PHY",
    })
    assert response.status_code == 201
    assert response.json()["code"] == "PHY"
    mock_program_service.create.assert_called_once()


@pytest.mark.anyio
async def test_create_program_unauthenticated(client):
    """POST /programs without auth returns 401."""
    response = await client.post("/api/v1/programs", json={
        "name": "Test",
        "code": "TST",
    })
    assert response.status_code == 401


# ── Modules ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_list_modules(admin_client, mock_module_service):
    """GET /programs/{program_id}/modules returns a paginated list."""
    mod_id = uuid.uuid4()
    prog_id = uuid.uuid4()
    mock_module_service.list_by_program.return_value = CursorPage(
        items=[ModuleRead(
            id=mod_id, name="Algorithmique", code="ALGO",
            program_id=prog_id, program_name="Informatique",
        )],
        next_cursor=None,
        has_more=False,
    )
    response = await admin_client.get(f"/api/v1/programs/{prog_id}/modules")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["code"] == "ALGO"


@pytest.mark.anyio
async def test_create_module_as_admin(admin_client, mock_module_service):
    """POST /programs/{program_id}/modules as admin returns 201."""
    mod_id = uuid.uuid4()
    prog_id = uuid.uuid4()
    mock_module_service.create.return_value = ModuleRead(
        id=mod_id, name="Bases de données", code="BDD",
        program_id=prog_id, program_name="Informatique",
    )
    response = await admin_client.post(f"/api/v1/programs/{prog_id}/modules", json={
        "program_id": str(prog_id),
        "name": "Bases de données",
        "code": "BDD",
    })
    assert response.status_code == 201
    assert response.json()["name"] == "Bases de données"

