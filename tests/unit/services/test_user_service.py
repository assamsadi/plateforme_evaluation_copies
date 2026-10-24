"""
Tests UserService — couvre en particulier :
- authenticate() : vérification is_active APRÈS le mot de passe (jamais
  révéler qu'un compte est désactivé à quelqu'un sans le bon mot de passe)
- list_users / deactivate_account / reactivate_account (gestion admin)
- garde-fou explicite : un admin ne peut jamais se désactiver lui-même
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models.identity.user import Admin, UserRole
from app.domain.schemas.auth_schemas import LoginRequest
from app.services.user_service import UserService


def _make_admin(user_id=None, is_active=True):
    return Admin(
        id=user_id or uuid.uuid4(),
        role=UserRole.ADMIN,
        first_name="Charlie",
        last_name="Bernard",
        email="charlie@test.edu",
        hashed_password="hashed_pw",
        is_active=is_active,
        totp_enabled=False,  # instance transiente (jamais flush) — default= ORM ne s'applique qu'au flush, jamais deviné ici
    )


@pytest.mark.anyio
class TestAuthenticate:
    async def test_wrong_password_never_reveals_is_active(self, monkeypatch):
        """Mot de passe faux -> 'Identifiants invalides', jamais 'Compte désactivé', même si le compte est inactif."""
        user = _make_admin(is_active=False)
        user_repo = AsyncMock()
        user_repo.get_by_email.return_value = user
        service = UserService(user_repo, AsyncMock())
        monkeypatch.setattr("app.services.user_service.verify_password", lambda plain, hashed: False)

        with pytest.raises(ValueError, match="Identifiants invalides"):
            await service.authenticate(LoginRequest(email=user.email, password="wrong"))

    async def test_deactivated_account_blocks_login_after_password_ok(self, monkeypatch):
        user = _make_admin(is_active=False)
        user_repo = AsyncMock()
        user_repo.get_by_email.return_value = user
        service = UserService(user_repo, AsyncMock())
        monkeypatch.setattr("app.services.user_service.verify_password", lambda plain, hashed: True)

        with pytest.raises(ValueError, match="Compte désactivé"):
            await service.authenticate(LoginRequest(email=user.email, password="correct"))

        user_repo.update.assert_not_awaited()  # jamais de "last login" mis à jour pour un login refusé

    async def test_active_account_login_succeeds(self, monkeypatch):
        user = _make_admin(is_active=True)
        user_repo = AsyncMock()
        user_repo.get_by_email.return_value = user
        service = UserService(user_repo, AsyncMock())
        monkeypatch.setattr("app.services.user_service.verify_password", lambda plain, hashed: True)

        result = await service.authenticate(LoginRequest(email=user.email, password="correct"))

        assert result is user
        user_repo.update.assert_awaited_once()

    async def test_unknown_email_raises_generic_error(self):
        user_repo = AsyncMock()
        user_repo.get_by_email.return_value = None
        service = UserService(user_repo, AsyncMock())

        with pytest.raises(ValueError, match="Identifiants invalides"):
            await service.authenticate(LoginRequest(email="nobody@test.edu", password="x"))


@pytest.mark.anyio
class TestListUsers:
    async def test_delegates_to_repository(self):
        user_repo = AsyncMock()
        fake_page = MagicMock()
        user_repo.list_users.return_value = fake_page
        service = UserService(user_repo, AsyncMock())

        result = await service.list_users(cursor="abc", limit=10, role=UserRole.STUDENT)

        assert result is fake_page
        user_repo.list_users.assert_awaited_once_with(cursor="abc", limit=10, role=UserRole.STUDENT)


@pytest.mark.anyio
class TestDeactivateAccount:
    async def test_self_deactivation_is_blocked(self):
        admin_id = uuid.uuid4()
        user_repo = AsyncMock()
        service = UserService(user_repo, AsyncMock())

        with pytest.raises(ValueError, match="propre compte"):
            await service.deactivate_account(admin_id, acting_admin_id=admin_id)

        user_repo.update.assert_not_awaited()  # jamais atteint la base — garde-fou avant toute lecture

    async def test_deactivate_unknown_user_raises(self):
        user_repo = AsyncMock()
        user_repo.update.return_value = None
        service = UserService(user_repo, AsyncMock())

        with pytest.raises(ValueError, match="introuvable"):
            await service.deactivate_account(uuid.uuid4(), acting_admin_id=uuid.uuid4())

    async def test_deactivate_success(self):
        target_id = uuid.uuid4()
        acting_admin_id = uuid.uuid4()
        deactivated_user = _make_admin(user_id=target_id, is_active=False)
        user_repo = AsyncMock()
        user_repo.update.return_value = deactivated_user
        audit_repo = AsyncMock()
        service = UserService(user_repo, audit_repo)

        result = await service.deactivate_account(target_id, acting_admin_id=acting_admin_id)

        assert result.is_active is False
        user_repo.update.assert_awaited_once_with(target_id, is_active=False)
        audit_repo.create.assert_awaited_once()


@pytest.mark.anyio
class TestReactivateAccount:
    async def test_reactivate_unknown_user_raises(self):
        user_repo = AsyncMock()
        user_repo.update.return_value = None
        service = UserService(user_repo, AsyncMock())

        with pytest.raises(ValueError, match="introuvable"):
            await service.reactivate_account(uuid.uuid4())

    async def test_reactivate_success(self):
        target_id = uuid.uuid4()
        reactivated_user = _make_admin(user_id=target_id, is_active=True)
        user_repo = AsyncMock()
        user_repo.update.return_value = reactivated_user
        service = UserService(user_repo, AsyncMock())

        result = await service.reactivate_account(target_id)

        assert result.is_active is True
        user_repo.update.assert_awaited_once_with(target_id, is_active=True)
