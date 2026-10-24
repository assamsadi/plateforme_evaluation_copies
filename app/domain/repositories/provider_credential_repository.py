"""
Repository ProviderCredential — surcharges admin des secrets fournisseurs
IA (clé/valeur générique, cf. docstring du modèle voisin).
"""
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.provider_credential import ProviderCredential


class ProviderCredentialRepositoryProtocol(Protocol):
    async def get_all(self) -> list[ProviderCredential]: ...
    async def get_by_key(self, key: str) -> ProviderCredential | None: ...
    async def upsert(self, key: str, value: str) -> ProviderCredential: ...
    async def delete(self, key: str) -> None: ...


class SQLAlchemyProviderCredentialRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[ProviderCredential]:
        result = await self._session.execute(select(ProviderCredential))
        return list(result.scalars().all())

    async def get_by_key(self, key: str) -> ProviderCredential | None:
        return await self._session.get(ProviderCredential, key)

    async def upsert(self, key: str, value: str) -> ProviderCredential:
        existing = await self.get_by_key(key)
        if existing is not None:
            existing.value = value
            await self._session.flush()
            return existing

        credential = ProviderCredential(key=key, value=value)
        self._session.add(credential)
        await self._session.flush()
        return credential

    async def delete(self, key: str) -> None:
        existing = await self.get_by_key(key)
        if existing is not None:
            await self._session.delete(existing)
            await self._session.flush()
