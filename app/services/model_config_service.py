"""
Service admin — configuration des modèles LLM par TaskType (chantier
"Configuration des modèles IA"). Lecture TOUJOURS fraîche (jamais via le
cache TTL de ModelRegistry, cf. docstring get_default_specs_for_task) :
c'est une vue admin peu fréquente, pas le chemin d'appel LLM.
"""
from typing import Protocol

from app.domain.repositories.model_configuration_repository import (
    ModelConfigurationRepositoryProtocol,
)
from app.domain.schemas.system_schemas import ModelConfigurationRead
from app.model_registry.models import ModelProvider, TaskType
from app.model_registry.registry import registry


class ModelConfigAdminServiceProtocol(Protocol):
    async def get_effective_config(self) -> list[ModelConfigurationRead]: ...
    async def update_model_config(
        self, task_type: TaskType, provider: ModelProvider, model_name: str, timeout_seconds: int,
    ) -> ModelConfigurationRead: ...


class ModelConfigAdminService:
    def __init__(self, model_config_repo: ModelConfigurationRepositoryProtocol) -> None:
        self._model_config_repo = model_config_repo

    async def get_effective_config(self) -> list[ModelConfigurationRead]:
        overrides = {o.task_type: o for o in await self._model_config_repo.get_all()}
        result: list[ModelConfigurationRead] = []
        for task_type in TaskType:
            defaults = registry.get_default_specs_for_task(task_type)
            primary = defaults[0]
            override = overrides.get(task_type)
            if override is not None:
                result.append(ModelConfigurationRead(
                    task_type=task_type, provider=override.provider, model_name=override.model_name,
                    timeout_seconds=override.timeout_seconds, temperature=primary.temperature,
                    max_tokens=primary.max_tokens, supports_vision=primary.supports_vision,
                    is_overridden=True, updated_at=override.updated_at,
                ))
            else:
                result.append(ModelConfigurationRead(
                    task_type=task_type, provider=primary.provider, model_name=primary.model_name,
                    timeout_seconds=primary.timeout_seconds, temperature=primary.temperature,
                    max_tokens=primary.max_tokens, supports_vision=primary.supports_vision,
                    is_overridden=False, updated_at=None,
                ))
        return result

    async def update_model_config(
        self, task_type: TaskType, provider: ModelProvider, model_name: str, timeout_seconds: int,
    ) -> ModelConfigurationRead:
        """
        task_type/provider déjà validés en amont (enums Pydantic au niveau
        du schema/routeur — une valeur hors enum est rejetée en 422 avant
        d'atteindre ce service, jamais acceptée silencieusement).
        model_name/timeout_seconds validés côté schema (min_length=1, > 0).
        """
        row = await self._model_config_repo.upsert(
            task_type=task_type, provider=provider, model_name=model_name, timeout_seconds=timeout_seconds,
        )
        # Effet réel au prochain appel LLM — invalidation explicite du
        # cache de ce processus (cf. docstring ModelRegistry, best-effort
        # cross-process, garanti sous _DEFAULT_CACHE_TTL_SECONDS partout).
        registry.invalidate_cache()

        defaults = registry.get_default_specs_for_task(task_type)
        primary = defaults[0]
        return ModelConfigurationRead(
            task_type=task_type, provider=row.provider, model_name=row.model_name,
            timeout_seconds=row.timeout_seconds, temperature=primary.temperature,
            max_tokens=primary.max_tokens, supports_vision=primary.supports_vision,
            is_overridden=True, updated_at=row.updated_at,
        )
