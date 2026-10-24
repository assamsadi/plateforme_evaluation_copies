import uuid
from unittest.mock import MagicMock

import pytest

from app.domain.models.identity.user import UserRole


def _make_student_public():
    return {
        "id": str(uuid.uuid4()),
        "email": "alice@test.edu",
        "role": UserRole.STUDENT.value,
        "first_name": "Alice",
        "last_name": "Dupont",
        "is_active": True,
        "student_number": "STU20240001",
        "group_id": str(uuid.uuid4()),
        "enrollment_year": 2024,
        "academic_status": "active",
        "level": "L3",
    }


def _make_user_mock():
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "alice@test.edu"
    user.role = UserRole.STUDENT
    user.first_name = "Alice"
    user.last_name = "Dupont"
    user.totp_enabled = False
    user.totp_verified_at = None
    user.totp_last_used_at = None
    user.model_dump = lambda: {
        "id": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }
    return user


@pytest.mark.anyio
async def test_register_student_success(client, mock_user_service):
    payload = {
        "email": "alice@test.edu",
        "password": "password123",
        "first_name": "Alice",
        "last_name": "Dupont",
        "student_number": "STU20240001",
        "group_id": str(uuid.uuid4()),
        "enrollment_year": 2024,
        "level": "L3",
    }
    mock_user_service.register_student.return_value = _make_student_public()

    response = await client.post("/api/v1/auth/register/student", json=payload)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@test.edu"
    assert body["role"] == UserRole.STUDENT.value
    mock_user_service.register_student.assert_awaited_once()


@pytest.mark.anyio
async def test_register_student_validation_error(client, mock_user_service):
    payload = {
        "email": "alice@test.edu",
        "password": "short",
        "first_name": "Alice",
        "last_name": "Dupont",
        "student_number": "STU20240001",
        "group_id": str(uuid.uuid4()),
        "enrollment_year": 2024,
        "level": "L3",
    }
    response = await client.post("/api/v1/auth/register/student", json=payload)
    assert response.status_code == 422
    mock_user_service.register_student.assert_not_awaited()


@pytest.mark.anyio
async def test_register_student_value_error_400(client, mock_user_service):
    payload = {
        "email": "alice@test.edu",
        "password": "password123",
        "first_name": "Alice",
        "last_name": "Dupont",
        "student_number": "STU20240001",
        "group_id": str(uuid.uuid4()),
        "enrollment_year": 2024,
        "level": "L3",
    }
    mock_user_service.register_student.side_effect = ValueError("Email déjà utilisé")

    response = await client.post("/api/v1/auth/register/student", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Email déjà utilisé"


@pytest.mark.anyio
async def test_login_success(client, mock_user_service):
    user = _make_user_mock()
    mock_user_service.authenticate.return_value = user
    # generate_tokens est synchrone dans le service — on utilise MagicMock
    # au lieu d'AsyncMock pour qu'il retourne le dict directement.
    mock_user_service.generate_tokens = MagicMock(return_value={
        "access_token": "access-token",
        "refresh_token": "refresh-token",
    })

    response = await client.post("/api/v1/auth/login", json={"email": "alice@test.edu", "password": "password123"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"] == "access-token"
    assert body["refresh_token"] == "refresh-token"
    assert body["token_type"] == "bearer"
    # Le user est un MagicMock sérialisé par FastAPI — on vérifie juste
    # la présence de la clé user et des tokens.
    assert "user" in body
    mock_user_service.authenticate.assert_awaited_once()
    mock_user_service.generate_tokens.assert_called_once_with(user)


@pytest.mark.anyio
async def test_login_mfa_required(client, mock_user_service):
    user = _make_user_mock()
    user.totp_enabled = True
    mock_user_service.authenticate.return_value = user
    mock_user_service.generate_tokens = MagicMock(return_value={})

    response = await client.post("/api/v1/auth/login", json={"email": "alice@test.edu", "password": "password123"})

    assert response.status_code == 200
    body = response.json()
    assert body["mfa_required"] is True
    assert "mfa_token" in body
    mock_user_service.generate_tokens.assert_not_called()


@pytest.mark.anyio
async def test_login_invalid_credentials_400(client, mock_user_service):
    mock_user_service.authenticate.side_effect = ValueError("Identifiants invalides")

    response = await client.post("/api/v1/auth/login", json={"email": "alice@test.edu", "password": "wrong"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Identifiants invalides"


@pytest.mark.anyio
async def test_login_validation_error_422(client, mock_user_service):
    response = await client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "password123"})
    assert response.status_code == 422
    mock_user_service.authenticate.assert_not_awaited()


@pytest.mark.anyio
async def test_mfa_status_success(student_client, fake_student):
    """GET /api/v1/auth/mfa/status → 200 + MFAStatusResponse."""
    # fake_student est déjà positionné par student_client, mais on s'assure
    # que les champs totp sont bien None pour la sérialisation JSON.
    response = await student_client.get("/api/v1/auth/mfa/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["verified_at"] is None
    assert body["last_used_at"] is None


@pytest.mark.anyio
async def test_mfa_status_requires_auth(client):
    response = await client.get("/api/v1/auth/mfa/status")
    assert response.status_code == 401


@pytest.mark.anyio
async def test_mfa_enable_success(student_client, mock_user_service):
    mock_user_service.enable_mfa.return_value = None
    response = await student_client.post("/api/v1/auth/mfa/enable", json={"code": "123456"})
    assert response.status_code == 200
    assert response.json()["detail"] == "MFA activé avec succès"
    mock_user_service.enable_mfa.assert_awaited_once()


@pytest.mark.anyio
async def test_mfa_enable_validation_error_422(student_client, mock_user_service):
    response = await student_client.post("/api/v1/auth/mfa/enable", json={"code": "123"})
    assert response.status_code == 422
    mock_user_service.enable_mfa.assert_not_awaited()


@pytest.mark.anyio
async def test_mfa_disable_success(student_client, mock_user_service):
    mock_user_service.disable_mfa.return_value = None
    response = await student_client.post("/api/v1/auth/mfa/disable", json={"password": "password123"})
    assert response.status_code == 200
    assert response.json()["detail"] == "MFA désactivé avec succès"
    mock_user_service.disable_mfa.assert_awaited_once()


@pytest.mark.anyio
async def test_mfa_disable_value_error_400(student_client, mock_user_service):
    mock_user_service.disable_mfa.side_effect = ValueError("Mot de passe incorrect")
    response = await student_client.post("/api/v1/auth/mfa/disable", json={"password": "wrong"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Mot de passe incorrect"