"""
Integration tests for auth-protected routes.
Uses shared fixtures from conftest.py — no manual mock_get_db.
"""
import pytest


@pytest.mark.anyio
async def test_access_admin_route_without_token(client):
    """Requests without a Bearer token must be rejected with 401."""
    response = await client.post("/api/v1/admin/users/professors", json={
        "email": "prof@test.com",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
        "department": "CS",
        "title": "Dr",
        "employee_number": "EMP123",
    })
    assert response.status_code == 401


@pytest.mark.anyio
async def test_admin_route_as_student_returns_403(student_client):
    """A student accessing an admin-only route gets 403 Forbidden."""
    response = await student_client.post("/api/v1/admin/users/professors", json={
        "email": "prof@test.com",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
        "department": "CS",
        "title": "Dr",
        "employee_number": "EMP123",
    })
    assert response.status_code == 403


@pytest.mark.anyio
async def test_professor_route_as_student_returns_403(student_client):
    """A student accessing a professor-only route gets 403 Forbidden."""
    response = await student_client.post("/api/v1/exercises", json={
        "module_id": "00000000-0000-4000-a000-000000000099",
        "title": "Test Exercise",
        "questions": [{"order": 1, "statement": "Q?", "bareme": {"points": 10}}],
    })
    assert response.status_code == 403


@pytest.mark.anyio
async def test_student_route_as_professor_returns_403(professor_client):
    """A professor accessing a student-only route gets 403 Forbidden."""
    response = await professor_client.get("/api/v1/students/me/submissions")
    assert response.status_code == 403
