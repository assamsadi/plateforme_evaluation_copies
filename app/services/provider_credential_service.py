"""
Service admin — secrets fournisseurs IA (clé API LLM, config Langfuse),
cf. docstring app/domain/models/system_infrastructure/provider_credential.py.

SANS allowlist fermée (contrairement à SystemConfigService, fichier
voisin) : décision actée avec l'utilisateur, l'admin nomme lui-même la
clé. `_KNOWN_KEYS` ci-dessous n'est PAS une contrainte de validation —
uniquement une liste d'affichage (préremplit la vue avec les clés
attendues de .env même si jamais surchargées en base, et signale
lesquelles ont un effet réellement câblé aujourd'hui via `is_wired`).
"""
import os
from typing import Protocol

from app.core.config import settings
from app.core.provider_credentials import credential_cache
from app.domain.repositories.provider_credential_repository import (
    ProviderCredentialRepositoryProtocol,
)
from app.domain.schemas.system_schemas import ProviderCredentialRead

# Clés connues de .env, affichées même sans surcharge DB — PAS une
# allowlist (cf. docstring module). is_wired=True seulement pour les clés
# réellement consommées aujourd'hui par
# app/model_registry/providers.py::create_llm_from_spec — tout le reste
# (y compris les 3 clés Langfuse) est stocké mais inerte tant qu'aucun
# code ne le consomme, ou n'a d'effet qu'au prochain redémarrage
# (Langfuse, cf. app/core/langfuse_client.py), jamais à chaud.
_KNOWN_KEYS: dict[str, bool] = {
    "GROQ_API_KEY": True,
    "OPENAI_API_KEY": True,
    "GOOGLE_API_KEY": True,
    "GOOGLE_API_KEY_2": True,
    "GOOGLE_API_KEY_3": True,
    "GOOGLE_API_KEY_4": True,
    "OPENROUTER_API_KEY": True,
    "LANGFUSE_SECRET_KEY": False,
    "LANGFUSE_PUBLIC_KEY": False,
    "LANGFUSE_BASE_URL": False,
}


class ProviderCredentialServiceProtocol(Protocol):
    async def list_credentials(self) -> list[ProviderCredentialRead]: ...
    async def set_credential(self, key: str, value: str) -> ProviderCredentialRead: ...
    async def create_credential(self, key: str, value: str) -> ProviderCredentialRead: ...
    async def clear_credential(self, key: str) -> None: ...


class ProviderCredentialService:
    def __init__(self, credential_repo: ProviderCredentialRepositoryProtocol) -> None:
        self._repo = credential_repo

    def _to_read(self, key: str, db_value: str | None, updated_at) -> ProviderCredentialRead:
        if db_value is not None:
            source = "database"
        elif getattr(settings, key, None) or os.getenv(key):
            source = "environment"
        else:
            source = "unset"
        return ProviderCredentialRead(
            key=key,
            source=source,
            is_wired=_KNOWN_KEYS.get(key, False),
            updated_at=updated_at,
        )

    async def list_credentials(self) -> list[ProviderCredentialRead]:
        rows = {r.key: r for r in await self._repo.get_all()}
        keys = set(_KNOWN_KEYS) | set(rows)
        result = [
            self._to_read(key, rows[key].value if key in rows else None, rows[key].updated_at if key in rows else None)
            for key in sorted(keys)
        ]
        return result

    async def create_credential(self, key: str, value: str) -> ProviderCredentialRead:
        key = key.strip()
        if not key:
            raise ValueError("Le nom de la clé ne peut pas être vide")
        existing = await self._repo.get_by_key(key)
        if existing is not None:
            raise ValueError(f"Une clé nommée {key!r} existe déjà — utilisez la modification plutôt qu'un ajout")
        row = await self._repo.upsert(key=key, value=value)
        credential_cache.invalidate()
        return self._to_read(key, row.value, row.updated_at)

    async def set_credential(self, key: str, value: str) -> ProviderCredentialRead:
        row = await self._repo.upsert(key=key, value=value)
        credential_cache.invalidate()
        return self._to_read(key, row.value, row.updated_at)

    async def clear_credential(self, key: str) -> None:
        await self._repo.delete(key)
        credential_cache.invalidate()
