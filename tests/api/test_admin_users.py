"""
Tests GET/PATCH/POST /admin/users* — protégés par get_current_admin
(mécanisme existant, réutilisé tel quel).
"""
import uuid

import pytest

from app.domain.models.identity.user import UserRole


def _make_user_public(role=UserRole.STUDENT, is_active=True):
    return {
        "id": str(uuid.uuid4()),
        "email": "user@test.edu",
        "role": role.value,
        "first_name": "John",
        "last_name": "Doe",
        "is_active": is_active,
    }


@pytest.mark.anyio
async def test_list_users_as_admin_returns_200(admin_client, mock_user_service):
    from app.domain.repositories.pagination import CursorPage
    mock_user_service.list_users.return_value = CursorPage(
        items=[_make_user_public(), _make_user_public(UserRole.PROFESSOR)],
        next_cursor=None, has_more=False,
    )

    response = await admin_client.get("/api/v1/admin/users")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    mock_user_service.list_users.assert_awaited_once()


@pytest.mark.anyio
async def test_list_users_passes_role_filter(admin_client, mock_user_service):
    from app.domain.repositories.pagination import CursorPage
    mock_user_service.list_users.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    response = await admin_client.get("/api/v1/admin/users?role=professor")

    assert response.status_code == 200
    _, kwargs = mock_user_service.list_users.call_args
    assert kwargs["role"] == UserRole.PROFESSOR


@pytest.mark.anyio
async def test_list_users_requires_admin_role(student_client, mock_user_service):
    response = await student_client.get("/api/v1/admin/users")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_deactivate_user_success(admin_client, mock_user_service):
    target_id = uuid.uuid4()
    mock_user_service.deactivate_account.return_value = _make_user_public(is_active=False)

    response = await admin_client.patch(f"/api/v1/admin/users/{target_id}/deactivate")

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    mock_user_service.deactivate_account.assert_awaited_once()


@pytest.mark.anyio
async def test_deactivate_self_guard_returns_400(admin_client, mock_user_service, fake_admin):
    """Le garde-fou vit dans le service (ValueError) — le routeur le traduit en 400."""
    mock_user_service.deactivate_account.side_effect = ValueError(
        "Un administrateur ne peut pas désactiver son propre compte"
    )

    response = await admin_client.patch(f"/api/v1/admin/users/{fake_admin.id}/deactivate")

    assert response.status_code == 400
    assert "propre compte" in response.json()["detail"]


@pytest.mark.anyio
async def test_deactivate_user_requires_admin_role(student_client, mock_user_service):
    response = await student_client.patch(f"/api/v1/admin/users/{uuid.uuid4()}/deactivate")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_reactivate_user_success(admin_client, mock_user_service):
    target_id = uuid.uuid4()
    mock_user_service.reactivate_account.return_value = _make_user_public(is_active=True)

    response = await admin_client.patch(f"/api/v1/admin/users/{target_id}/reactivate")

    assert response.status_code == 200
    assert response.json()["is_active"] is True
    mock_user_service.reactivate_account.assert_awaited_once()


@pytest.mark.anyio
async def test_reactivate_unknown_user_returns_400(admin_client, mock_user_service):
    mock_user_service.reactivate_account.side_effect = ValueError("Utilisateur introuvable")

    response = await admin_client.patch(f"/api/v1/admin/users/{uuid.uuid4()}/reactivate")

    assert response.status_code == 400


@pytest.mark.anyio
async def test_create_student_as_admin_success(admin_client, mock_user_service):
    mock_user_service.register_student.return_value = {
        **_make_user_public(UserRole.STUDENT),
        "student_number": "STU20240001",
        "group_id": str(uuid.uuid4()),
        "enrollment_year": 2024,
        "academic_status": "active",
        "level": "L3",
    }
    payload = {
        "email": "newstudent@test.edu",
        "password": "password123",
        "first_name": "Alice",
        "last_name": "Dupont",
        "student_number": "STU20240001",
        "group_id": str(uuid.uuid4()),
        "enrollment_year": 2024,
        "level": "L3",
    }

    response = await admin_client.post("/api/v1/admin/users/students", json=payload)

    assert response.status_code == 201
    assert response.json()["role"] == UserRole.STUDENT.value
    mock_user_service.register_student.assert_awaited_once()


@pytest.mark.anyio
async def test_create_student_as_admin_requires_admin_role(student_client, mock_user_service):
    payload = {
        "email": "newstudent@test.edu",
        "password": "password123",
        "first_name": "Alice",
        "last_name": "Dupont",
        "student_number": "STU20240001",
        "group_id": str(uuid.uuid4()),
        "enrollment_year": 2024,
        "level": "L3",
    }
    response = await student_client.post("/api/v1/admin/users/students", json=payload)
    assert response.status_code == 403
