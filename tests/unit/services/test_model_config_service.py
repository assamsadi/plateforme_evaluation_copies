"""
Tests ModelConfigAdminService — get_effective_config() (11 TaskType
toujours présents, base + repli) et update_model_config() (persiste +
invalide le cache registry). `registry` est patché (app.services.
model_config_service.registry) pour isoler du singleton global réel.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.model_registry.models import ModelProvider, ModelSpec, TaskType
from app.services.model_config_service import ModelConfigAdminService


def _make_row(task_type, provider=ModelProvider.OPENAI, model_name="gpt-4o", timeout_seconds=77, updated_at=None):
    return MagicMock(
        task_type=task_type, provider=provider, model_name=model_name,
        timeout_seconds=timeout_seconds, updated_at=updated_at,
    )


@pytest.mark.anyio
class TestGetEffectiveConfig:
    async def test_returns_all_eleven_task_types(self):
        repo = AsyncMock()
        repo.get_all.return_value = []
        service = ModelConfigAdminService(repo)

        with patch("app.services.model_config_service.registry") as mock_registry:
            mock_registry.get_default_specs_for_task.return_value = [
                ModelSpec(provider=ModelProvider.GROQ, model_name="llama-3.3-70b-versatile", timeout_seconds=45),
                ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini", timeout_seconds=45),
            ]
            result = await service.get_effective_config()

        assert len(result) == len(TaskType)
        assert {r.task_type for r in result} == set(TaskType)
        assert all(r.is_overridden is False for r in result)

    async def test_overridden_task_type_reflects_db_row(self):
        repo = AsyncMock()
        repo.get_all.return_value = [_make_row(TaskType.FEEDBACK_GENERATION)]
        service = ModelConfigAdminService(repo)

        with patch("app.services.model_config_service.registry") as mock_registry:
            mock_registry.get_default_specs_for_task.return_value = [
                ModelSpec(
                    provider=ModelProvider.GROQ, model_name="llama-3.3-70b-versatile",
                    temperature=0.1, timeout_seconds=45,
                ),
                ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini", timeout_seconds=45),
            ]
            result = await service.get_effective_config()

        overridden = next(r for r in result if r.task_type == TaskType.FEEDBACK_GENERATION)
        assert overridden.is_overridden is True
        assert overridden.provider == ModelProvider.OPENAI
        assert overridden.model_name == "gpt-4o"
        assert overridden.timeout_seconds == 77
        # temperature toujours héritée de l'entrée d'origine, jamais de la ligne DB (qui ne la porte pas).
        assert overridden.temperature == 0.1

    async def test_non_overridden_task_type_reflects_defaults(self):
        repo = AsyncMock()
        repo.get_all.return_value = [_make_row(TaskType.FEEDBACK_GENERATION)]
        service = ModelConfigAdminService(repo)

        with patch("app.services.model_config_service.registry") as mock_registry:
            mock_registry.get_default_specs_for_task.return_value = [
                ModelSpec(provider=ModelProvider.GROQ, model_name="llama-3.3-70b-versatile", timeout_seconds=45),
                ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini", timeout_seconds=45),
            ]
            result = await service.get_effective_config()

        untouched = next(r for r in result if r.task_type == TaskType.REASONING_GRAPH)
        assert untouched.is_overridden is False
        assert untouched.provider == ModelProvider.GROQ
        assert untouched.model_name == "llama-3.3-70b-versatile"


@pytest.mark.anyio
class TestUpdateModelConfig:
    async def test_persists_and_invalidates_cache(self):
        repo = AsyncMock()
        repo.upsert.return_value = _make_row(TaskType.OCR_VISION, timeout_seconds=99)
        service = ModelConfigAdminService(repo)

        with patch("app.services.model_config_service.registry") as mock_registry:
            mock_registry.get_default_specs_for_task.return_value = [
                ModelSpec(
                    provider=ModelProvider.GROQ, model_name="qwen/qwen3.6-27b",
                    temperature=0.1, supports_vision=True, max_tokens=8000, timeout_seconds=90,
                ),
                ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini", timeout_seconds=90),
            ]
            result = await service.update_model_config(
                task_type=TaskType.OCR_VISION, provider=ModelProvider.OPENAI,
                model_name="gpt-4o", timeout_seconds=99,
            )

            mock_registry.invalidate_cache.assert_called_once()

        repo.upsert.assert_awaited_once_with(
            task_type=TaskType.OCR_VISION, provider=ModelProvider.OPENAI,
            model_name="gpt-4o", timeout_seconds=99,
        )
        assert result.is_overridden is True
        assert result.timeout_seconds == 99
        # supports_vision/max_tokens toujours hérités de l'entrée d'origine (OCR_VISION), jamais perdus.
        assert result.supports_vision is True
        assert result.max_tokens == 8000
