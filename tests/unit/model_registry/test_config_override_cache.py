"""
Tests du cache de surcharge admin sur ModelRegistry (chantier
"Configuration des modèles IA") — refresh_cache_if_stale/invalidate_cache/
_apply_override. Utilise des instances ModelRegistry LOCALES (jamais le
singleton global `registry`) avec un repository mocké — isole le
comportement du cache lui-même de toute base réelle (couvert séparément
par tests/integration/test_model_config_override_e2e.py).
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.model_registry.models import ModelProvider, ModelSpec, TaskType
from app.model_registry.registry import ModelRegistry


def _fake_override(task_type, provider=ModelProvider.OPENAI, model_name="gpt-4o", timeout_seconds=77):
    return MagicMock(task_type=task_type, provider=provider, model_name=model_name, timeout_seconds=timeout_seconds)


@asynccontextmanager
async def _fake_db_context():
    yield AsyncMock()


@pytest.mark.anyio
class TestNoOverrideBehaviorUnchanged:
    """Contrainte du ticket : comportement STRICTEMENT identique si aucune configuration en base."""

    async def test_get_specs_for_task_matches_default_without_any_refresh(self):
        """Même sans jamais appeler refresh_cache_if_stale (ex. usages hors invoke_llm_with_fallback) -> comportement d'avant ce chantier."""
        reg = ModelRegistry()
        specs = reg.get_specs_for_task(TaskType.FEEDBACK_GENERATION)

        assert specs[0].provider == ModelProvider.GROQ
        assert specs[0].model_name == "llama-3.3-70b-versatile"
        assert specs[1].provider == ModelProvider.OPENAI
        assert specs[1].model_name == "gpt-4o-mini"

    async def test_refresh_with_empty_repository_changes_nothing(self):
        reg = ModelRegistry()
        empty_repo = AsyncMock()
        empty_repo.get_all.return_value = []

        with patch(
            "app.domain.repositories.model_configuration_repository.SQLAlchemyModelConfigurationRepository",
            return_value=empty_repo,
        ):
            with patch("app.core.database.get_db_context", _fake_db_context):
                await reg.refresh_cache_if_stale()

        specs = reg.get_specs_for_task(TaskType.OCR_VISION)
        assert specs[0].model_name == "qwen/qwen3.6-27b"


@pytest.mark.anyio
class TestCacheTTL:
    async def test_refresh_is_noop_within_ttl(self):
        reg = ModelRegistry(cache_ttl_seconds=30)
        reg._cache_loaded_at = datetime.now(timezone.utc)  # vient d'être chargé

        repo = AsyncMock()
        with patch(
            "app.domain.repositories.model_configuration_repository.SQLAlchemyModelConfigurationRepository",
            return_value=repo,
        ):
            await reg.refresh_cache_if_stale()

        repo.get_all.assert_not_called()

    async def test_refresh_queries_again_after_ttl_expiry(self):
        reg = ModelRegistry(cache_ttl_seconds=30)
        reg._cache_loaded_at = datetime.now(timezone.utc) - timedelta(seconds=31)

        repo = AsyncMock()
        repo.get_all.return_value = []
        with patch(
            "app.domain.repositories.model_configuration_repository.SQLAlchemyModelConfigurationRepository",
            return_value=repo,
        ):
            with patch("app.core.database.get_db_context", _fake_db_context):
                await reg.refresh_cache_if_stale()

        repo.get_all.assert_awaited_once()

    async def test_invalidate_cache_forces_refresh_regardless_of_ttl(self):
        reg = ModelRegistry(cache_ttl_seconds=30)
        reg._cache_loaded_at = datetime.now(timezone.utc)  # frais, ne devrait PAS se rafraîchir normalement

        reg.invalidate_cache()
        assert reg._cache_loaded_at is None

        repo = AsyncMock()
        repo.get_all.return_value = []
        with patch(
            "app.domain.repositories.model_configuration_repository.SQLAlchemyModelConfigurationRepository",
            return_value=repo,
        ):
            with patch("app.core.database.get_db_context", _fake_db_context):
                await reg.refresh_cache_if_stale()

        repo.get_all.assert_awaited_once()

    async def test_refresh_failure_is_swallowed_never_raised(self):
        """Best-effort explicite (docstring refresh_cache_if_stale) — une panne DB ne doit jamais interrompre invoke_llm_with_fallback."""
        reg = ModelRegistry(cache_ttl_seconds=30)

        with patch("app.core.database.get_db_context", side_effect=RuntimeError("DB indisponible")):
            await reg.refresh_cache_if_stale()  # ne doit lever aucune exception

        # Cache resté vide -> repli intégral sur les valeurs par défaut, jamais cassé.
        specs = reg.get_specs_for_task(TaskType.REASONING_GRAPH)
        assert specs[0].model_name == "llama-3.3-70b-versatile"


@pytest.mark.anyio
class TestApplyOverride:
    async def test_override_replaces_primary_only_fallback_preserved(self):
        reg = ModelRegistry()
        reg._overrides = {TaskType.FEEDBACK_GENERATION: _fake_override(TaskType.FEEDBACK_GENERATION)}

        specs = reg.get_specs_for_task(TaskType.FEEDBACK_GENERATION)

        assert specs[0].provider == ModelProvider.OPENAI
        assert specs[0].model_name == "gpt-4o"
        assert specs[0].timeout_seconds == 77
        # Repli JAMAIS retiré ni modifié.
        assert len(specs) == 2
        assert specs[1].provider == ModelProvider.OPENAI
        assert specs[1].model_name == "gpt-4o-mini"

    async def test_override_preserves_original_temperature_max_tokens_supports_vision(self):
        """temperature/max_tokens/supports_vision ne sont JAMAIS surchargeables — toujours hérités de l'entrée d'origine."""
        reg = ModelRegistry()
        reg._overrides = {TaskType.OCR_VISION: _fake_override(TaskType.OCR_VISION, model_name="gpt-4o")}

        specs = reg.get_specs_for_task(TaskType.OCR_VISION)

        assert specs[0].model_name == "gpt-4o"
        assert specs[0].supports_vision is True  # hérité de l'entrée OCR_VISION d'origine, jamais deviné
        assert specs[0].max_tokens == 8000  # idem
        assert specs[0].temperature == 0.1

    async def test_override_on_task_type_without_default_entry_uses_generic_fallback_base(self):
        """QUESTION_ATTACHMENT n'a pas d'entrée dans _DEFAULT_REGISTRY_CONFIG -> temperature/max_tokens/supports_vision viennent du repli générique."""
        reg = ModelRegistry()
        reg._overrides = {TaskType.QUESTION_ATTACHMENT: _fake_override(TaskType.QUESTION_ATTACHMENT)}

        specs = reg.get_specs_for_task(TaskType.QUESTION_ATTACHMENT)

        assert specs[0].provider == ModelProvider.OPENAI
        assert specs[0].model_name == "gpt-4o"
        assert specs[0].supports_vision is False
        assert specs[0].max_tokens is None

    async def test_no_override_for_task_type_returns_default_unchanged(self):
        reg = ModelRegistry()
        reg._overrides = {TaskType.FEEDBACK_GENERATION: _fake_override(TaskType.FEEDBACK_GENERATION)}

        specs = reg.get_specs_for_task(TaskType.REASONING_GRAPH)  # pas de surcharge pour celle-ci

        assert specs[0].provider == ModelProvider.GROQ
        assert specs[0].model_name == "llama-3.3-70b-versatile"


@pytest.mark.anyio
class TestGetDefaultSpecsForTask:
    async def test_ignores_overrides_always_raw_defaults(self):
        """Câblage ModelConfigAdminService (vue admin toujours fraîche) — jamais influencé par le cache."""
        reg = ModelRegistry()
        reg._overrides = {TaskType.FEEDBACK_GENERATION: _fake_override(TaskType.FEEDBACK_GENERATION)}

        specs = reg.get_default_specs_for_task(TaskType.FEEDBACK_GENERATION)

        assert specs[0].provider == ModelProvider.GROQ
        assert specs[0].model_name == "llama-3.3-70b-versatile"
