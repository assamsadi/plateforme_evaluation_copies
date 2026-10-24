"""
Tests unitaires de app.api.deps — get_current_active_user en particulier.

Appelle la fonction directement (pas de client HTTP, pas de Redis) :
get_current_active_user ne dépend que du current_user déjà résolu par
get_current_user (décodage token + blacklist Redis, testé ailleurs via
tests/integration/test_user_deactivation.py pour le chemin actif) — la
vérification is_active elle-même est un point isolé, testable sans aucune
infrastructure.
"""
import pytest
from fastapi import HTTPException

from app.api.deps import get_current_active_user
from app.domain.models.identity.user import Admin, UserRole


def _make_admin(is_active: bool) -> Admin:
    return Admin(
        role=UserRole.ADMIN, first_name="Charlie", last_name="Bernard",
        email="charlie@test.edu", hashed_password="hashed_pw", is_active=is_active,
    )


@pytest.mark.anyio
async def test_get_current_active_user_allows_active_account():
    user = _make_admin(is_active=True)

    result = await get_current_active_user(user)

    assert result is user


@pytest.mark.anyio
async def test_get_current_active_user_rejects_inactive_user():
    """
    Preuve directe du câblage : un token émis avant désactivation reste
    signé valide jusqu'à expiration (JWT stateless) — cette vérification à
    CHAQUE requête authentifiée coupe l'accès immédiatement, pas seulement
    à la prochaine connexion (cf. UserService.authenticate, chemin
    "nouvelle connexion", testé séparément avec une vraie base).
    """
    user = _make_admin(is_active=False)

    with pytest.raises(HTTPException) as exc_info:
        await get_current_active_user(user)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Compte désactivé"
