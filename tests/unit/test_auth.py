import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import pyotp

from app.domain.models.identity.user import User, UserRole, Student, Professor, Admin
from app.domain.schemas.auth_schemas import (
    LoginRequest,
    StudentCreate,
    ProfessorCreate,
    AdminCreate,
)
from app.services.user_service import UserService


@pytest.fixture
def mock_user_repo():
    return AsyncMock()


@pytest.fixture
def mock_audit_repo():
    return AsyncMock()


@pytest.fixture
def user_service(mock_user_repo, mock_audit_repo):
    return UserService(user_repo=mock_user_repo, audit_repo=mock_audit_repo)


@pytest.mark.anyio
async def test_login_success(user_service, mock_user_repo):
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="hashed",
        role=UserRole.STUDENT,
        totp_enabled=False,
        first_name="Test",
        last_name="User",
        is_active=True,
    )
    mock_user_repo.get_by_email.return_value = user
    mock_user_repo.update.return_value = user

    with patch("app.services.user_service.verify_password", return_value=True):
        result = await user_service.authenticate(
            LoginRequest(email="test@example.com", password="password")
        )

    assert result.email == "test@example.com"
    mock_user_repo.get_by_email.assert_called_once_with("test@example.com")


@pytest.mark.anyio
async def test_login_failure_wrong_password(user_service, mock_user_repo):
    user = User(
        id=uuid.uuid4(),
        email="test@example.com",
        hashed_password="hashed",
        role=UserRole.STUDENT,
        totp_enabled=False,
        first_name="Test",
        last_name="User",
    )
    mock_user_repo.get_by_email.return_value = user

    with patch("app.services.user_service.verify_password", return_value=False):
        with pytest.raises(ValueError, match="Identifiants invalides"):
            await user_service.authenticate(
                LoginRequest(email="test@example.com", password="wrong")
            )


@pytest.mark.anyio
async def test_mfa_setup_and_verify_flow(user_service, mock_user_repo):
    user = User(
        id=uuid.uuid4(),
        email="mfa@example.com",
        hashed_password="hashed",
        role=UserRole.STUDENT,
        totp_enabled=False,
        totp_secret=None,
    )

    # 1. Setup MFA
    mfa_info = await user_service.setup_mfa(user)
    assert "secret" in mfa_info
    secret = mfa_info["secret"]
    mock_user_repo.update.assert_called_with(user.id, totp_secret=secret)

    # 2. Enable MFA with correct TOTP code
    user.totp_secret = secret
    totp = pyotp.TOTP(secret)
    valid_code = totp.now()

    await user_service.enable_mfa(user, valid_code)
    mock_user_repo.update.assert_called()

    # 3. Verify MFA
    user.totp_enabled = True
    await user_service.verify_mfa(user, valid_code)

    # 4. Invalid TOTP code raises ValueError
    with pytest.raises(ValueError, match="Code TOTP invalide"):
        await user_service.verify_mfa(user, "000000")
