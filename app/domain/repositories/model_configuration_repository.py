"""
Repository ModelConfiguration — surcharges admin du choix de modèle LLM
par TaskType (chantier "Configuration des modèles IA").
"""
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.model_configuration import ModelConfiguration
from app.model_registry.models import ModelProvider, TaskType


class ModelConfigurationRepositoryProtocol(Protocol):
    async def get_all(self) -> list[ModelConfiguration]: ...
    async def get_by_task_type(self, task_type: TaskType) -> ModelConfiguration | None: ...
    async def upsert(
        self, task_type: TaskType, provider: ModelProvider, model_name: str, timeout_seconds: int,
    ) -> ModelConfiguration: ...
    async def delete(self, task_type: TaskType) -> None: ...


class SQLAlchemyModelConfigurationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[ModelConfiguration]:
        result = await self._session.execute(select(ModelConfiguration))
        return list(result.scalars().all())

    async def get_by_task_type(self, task_type: TaskType) -> ModelConfiguration | None:
        return await self._session.get(ModelConfiguration, task_type)

    async def upsert(
        self, task_type: TaskType, provider: ModelProvider, model_name: str, timeout_seconds: int,
    ) -> ModelConfiguration:
        """
        task_type est la clé primaire (une ligne par tâche, jamais un
        historique) — upsert applicatif (get puis create/update), pas un
        ON CONFLICT SQL : le volume est trivial (au plus 11 TaskType) et
        cohérent avec le reste du projet (aucun autre repository n'utilise
        ON CONFLICT).
        """
        existing = await self.get_by_task_type(task_type)
        if existing is not None:
            existing.provider = provider
            existing.model_name = model_name
            existing.timeout_seconds = timeout_seconds
            await self._session.flush()
            return existing

        config = ModelConfiguration(
            task_type=task_type, provider=provider, model_name=model_name, timeout_seconds=timeout_seconds,
        )
        self._session.add(config)
        await self._session.flush()
        return config

    async def delete(self, task_type: TaskType) -> None:
        """Retire la surcharge (retour au repli _DEFAULT_REGISTRY_CONFIG) — no-op si aucune ligne n'existe."""
        existing = await self.get_by_task_type(task_type)
        if existing is not None:
            await self._session.delete(existing)
            await self._session.flush()
