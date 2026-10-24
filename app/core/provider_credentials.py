"""
Résolveur des secrets fournisseurs IA (clé API LLM) avec surcharge admin
à effet vivant — même principe que app/model_registry/registry.py
(ModelRegistry) : cache TTL court en mémoire PAR PROCESSUS (web + workers
Celery restent des processus séparés, jamais d'état partagé entre eux —
même compromis assumé, cf. docstring ModelRegistry), get_effective_
credential reste SYNCHRONE (ne lit QUE le cache), refresh_if_stale est la
seule fonction async, appelée explicitement par l'appelant (cf.
app/llm/client.py, juste à côté de registry.refresh_cache_if_stale()).

Best-effort explicite : une erreur DB ne doit JAMAIS interrompre un appel
LLM — c'est une fonctionnalité d'admin, pas un prérequis du pipeline. En
cas d'échec, repli sur le cache existant (ou vide, donc repli intégral
sur Settings/.env).
"""
import logging
import os
from datetime import datetime, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_TTL_SECONDS = 30


class ProviderCredentialCache:
    def __init__(self, cache_ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._cache_ttl_seconds = cache_ttl_seconds
        self._overrides: dict[str, str] = {}
        self._loaded_at: datetime | None = None

    def _is_stale(self) -> bool:
        if self._loaded_at is None:
            return True
        age_seconds = (datetime.now(timezone.utc) - self._loaded_at).total_seconds()
        return age_seconds >= self._cache_ttl_seconds

    async def refresh_if_stale(self) -> None:
        if not self._is_stale():
            return

        from app.core.database import get_db_context
        from app.domain.repositories.provider_credential_repository import (
            SQLAlchemyProviderCredentialRepository,
        )

        try:
            async with get_db_context() as db:
                rows = await SQLAlchemyProviderCredentialRepository(db).get_all()
            self._overrides = {row.key: row.value for row in rows}
            self._loaded_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning(
                f"Impossible de rafraîchir le cache des secrets fournisseurs "
                f"(repli sur le cache existant / .env) : {e}"
            )

    def invalidate(self) -> None:
        """Force un rafraîchissement au prochain appel — effet immédiat SEULEMENT dans ce processus (cf. docstring module)."""
        self._loaded_at = None

    def get_effective(self, key: str) -> str | None:
        """
        Ordre de résolution : surcharge DB (cache) -> Settings (.env) ->
        os.environ brut (repli générique pour une clé que Settings ne
        connaît pas explicitement, ex. un futur fournisseur nommé par
        l'admin avant d'être ajouté à app/core/config.py).
        """
        override = self._overrides.get(key)
        if override is not None:
            return override
        return getattr(settings, key, None) or os.getenv(key)


# Singleton global — mêmes garanties/limites que app.model_registry.registry.registry.
credential_cache = ProviderCredentialCache()


def get_effective_credential(key: str) -> str | None:
    return credential_cache.get_effective(key)
