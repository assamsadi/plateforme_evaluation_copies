"""
Tests SystemConfigService — get_all_settings()/update_setting() : allowlist
stricte, cast typé, rejet explicite des valeurs invalides/négatives/clés
hors allowlist (contrainte du ticket : jamais silencieux).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.system_config_service import _ALLOWED_SETTINGS, SystemConfigService


def _make_row(key, value):
    return MagicMock(key=key, value=value, updated_at=None)


@pytest.mark.anyio
class TestGetAllSettings:
    async def test_returns_all_allowlisted_keys(self):
        repo = AsyncMock()
        repo.get_all.return_value = []
        service = SystemConfigService(repo)

        result = await service.get_all_settings()

        assert {r.key for r in result} == set(_ALLOWED_SETTINGS.keys())
        assert all(r.override_value is None for r in result)
        # Sans surcharge, la valeur effective = la valeur par défaut Settings.
        for r in result:
            assert r.effective_value == r.default_value

    async def test_overridden_key_reflects_db_value(self):
        repo = AsyncMock()
        repo.get_all.return_value = [_make_row("MAX_LLM_CALLS_PER_THREAD", "50")]
        service = SystemConfigService(repo)

        result = await service.get_all_settings()

        overridden = next(r for r in result if r.key == "MAX_LLM_CALLS_PER_THREAD")
        assert overridden.override_value == "50"
        assert overridden.effective_value == "50"
        assert overridden.value_type == "int"


@pytest.mark.anyio
class TestUpdateSetting:
    async def test_rejects_key_not_in_allowlist(self):
        repo = AsyncMock()
        service = SystemConfigService(repo)

        with pytest.raises(ValueError, match="allowlist"):
            await service.update_setting("GROQ_API_KEY", "hacked")

        repo.upsert.assert_not_awaited()

    async def test_rejects_non_numeric_value_for_int_setting(self):
        repo = AsyncMock()
        service = SystemConfigService(repo)

        with pytest.raises(ValueError, match="invalide"):
            await service.update_setting("MAX_LLM_CALLS_PER_THREAD", "not-a-number")

        repo.upsert.assert_not_awaited()

    async def test_rejects_negative_value(self):
        repo = AsyncMock()
        service = SystemConfigService(repo)

        with pytest.raises(ValueError, match="négative"):
            await service.update_setting("LLM_RATE_LIMIT_WAIT_SECONDS", "-5")

        repo.upsert.assert_not_awaited()

    async def test_accepts_and_persists_valid_int_value(self):
        repo = AsyncMock()
        repo.upsert.return_value = _make_row("MAX_LLM_CALLS_PER_THREAD", "50")
        service = SystemConfigService(repo)

        result = await service.update_setting("MAX_LLM_CALLS_PER_THREAD", "50")

        repo.upsert.assert_awaited_once_with(key="MAX_LLM_CALLS_PER_THREAD", value="50")
        assert result.effective_value == "50"

    async def test_accepts_valid_decimal_value(self):
        repo = AsyncMock()
        repo.upsert.return_value = _make_row("COMPETENCY_DECAY_FACTOR", "0.85")
        service = SystemConfigService(repo)

        result = await service.update_setting("COMPETENCY_DECAY_FACTOR", "0.85")

        assert result.effective_value == "0.85"

    async def test_rejects_invalid_decimal_value(self):
        repo = AsyncMock()
        service = SystemConfigService(repo)

        with pytest.raises(ValueError, match="invalide"):
            await service.update_setting("COMPETENCY_DECAY_FACTOR", "not-a-decimal")

        repo.upsert.assert_not_awaited()

    async def test_never_exposes_api_keys_or_secrets(self):
        """Vérifie explicitement l'exclusion des secrets/identifiants (contrainte du ticket)."""
        forbidden = {"GROQ_API_KEY", "OPENAI_API_KEY", "JWT_SECRET_KEY", "DATABASE_URL", "AZURE_STORAGE_CONNECTION_STRING"}
        assert forbidden.isdisjoint(_ALLOWED_SETTINGS.keys())
