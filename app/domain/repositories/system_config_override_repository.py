"""
Repository SystemConfigOverride — surcharges admin des seuils Settings
(stockage/lecture seulement à ce stade, cf. docstring du modèle).
"""
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.system_config_override import SystemConfigOverride


class SystemConfigOverrideRepositoryProtocol(Protocol):
    async def get_all(self) -> list[SystemConfigOverride]: ...
    async def get_by_key(self, key: str) -> SystemConfigOverride | None: ...
    async def upsert(self, key: str, value: str) -> SystemConfigOverride: ...


class SQLAlchemySystemConfigOverrideRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[SystemConfigOverride]:
        result = await self._session.execute(select(SystemConfigOverride))
        return list(result.scalars().all())

    async def get_by_key(self, key: str) -> SystemConfigOverride | None:
        return await self._session.get(SystemConfigOverride, key)

    async def upsert(self, key: str, value: str) -> SystemConfigOverride:
        existing = await self.get_by_key(key)
        if existing is not None:
            existing.value = value
            await self._session.flush()
            return existing

        override = SystemConfigOverride(key=key, value=value)
        self._session.add(override)
        await self._session.flush()
        return override
