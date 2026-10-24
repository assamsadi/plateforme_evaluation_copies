"""
Test d'intégration RÉEL (DB réelle, commits réels, singleton ModelRegistry
réel — jamais une instance locale reconstruite) — preuve explicitement
demandée par le ticket "Configuration des modèles IA" : "Modification via
l'endpoint, effet réellement pris en compte au prochain appel LLM (test
d'intégration, pas juste que la ligne est en base)".

N'utilise PAS `db_session` (rollback-only, cf. tests/conftest.py) : le
cache de ModelRegistry (registry.refresh_cache_if_stale) ouvre sa PROPRE
session via get_db_context() (commit réel, pas la transaction du test) —
une écriture jamais committée via db_session serait invisible pour lui.
Écrit donc directement via get_db_context() (même mécanisme que la
production), avec nettoyage explicite en fin de test (try/finally,
task_type = clé primaire partagée entre runs, jamais un UUID généré).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.database import get_db_context
from app.domain.repositories.model_configuration_repository import SQLAlchemyModelConfigurationRepository
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import ModelProvider, TaskType
from app.model_registry.registry import registry

# TaskType dédié à ce test — jamais réutilisé par un vrai agent en test
# (FEEDBACK_GENERATION est purement textuel, chaîne simple Groq->OpenAI),
# choisi pour éviter toute collision avec d'autres tests d'intégration
# qui pourraient s'exécuter en parallèle sur le même TaskType.
_TASK_TYPE = TaskType.FEEDBACK_GENERATION


async def _clear_override() -> None:
    async with get_db_context() as db:
        await SQLAlchemyModelConfigurationRepository(db).delete(_TASK_TYPE)
    registry.invalidate_cache()


@pytest.fixture(autouse=True)
async def _cleanup():
    await _clear_override()
    yield
    await _clear_override()


@pytest.mark.anyio
class TestModelConfigOverrideEndToEnd:
    async def test_no_config_in_db_behaves_exactly_like_before(self):
        """Contrainte du ticket : comportement inchangé si aucune configuration en base."""
        registry.invalidate_cache()
        await registry.refresh_cache_if_stale()

        specs = registry.get_specs_for_task(_TASK_TYPE)

        assert specs[0].provider == ModelProvider.GROQ
        assert specs[0].model_name == "llama-3.3-70b-versatile"
        assert specs[1].provider == ModelProvider.OPENAI
        assert specs[1].model_name == "gpt-4o-mini"

    async def test_override_persisted_but_cache_not_yet_refreshed_still_shows_old_value(self):
        """Preuve que le cache existe VRAIMENT (pas juste une ligne en base jamais consultée) — un fait explicitement demandé par le ticket."""
        registry.invalidate_cache()
        await registry.refresh_cache_if_stale()  # charge le cache (vide) AVANT l'écriture

        async with get_db_context() as db:
            await SQLAlchemyModelConfigurationRepository(db).upsert(
                task_type=_TASK_TYPE, provider=ModelProvider.OPENAI, model_name="gpt-4o", timeout_seconds=77,
            )

        # Cache pas encore invalidé -> reflète toujours l'ancienne valeur.
        stale_specs = registry.get_specs_for_task(_TASK_TYPE)
        assert stale_specs[0].model_name == "llama-3.3-70b-versatile"

    async def test_override_takes_effect_after_invalidation_fallback_preserved(self):
        async with get_db_context() as db:
            await SQLAlchemyModelConfigurationRepository(db).upsert(
                task_type=_TASK_TYPE, provider=ModelProvider.OPENAI, model_name="gpt-4o", timeout_seconds=77,
            )

        registry.invalidate_cache()
        await registry.refresh_cache_if_stale()

        specs = registry.get_specs_for_task(_TASK_TYPE)

        assert specs[0].provider == ModelProvider.OPENAI
        assert specs[0].model_name == "gpt-4o"
        assert specs[0].timeout_seconds == 77
        # Le repli n'est JAMAIS retiré par une ligne de config admin.
        assert len(specs) == 2
        assert specs[1].provider == ModelProvider.OPENAI
        assert specs[1].model_name == "gpt-4o-mini"

    async def test_invoke_llm_with_fallback_uses_overridden_primary_on_next_call(self):
        """
        Le coeur de la preuve demandée : PUT (simulé ici par un upsert
        direct, le routeur appelle exactement le même chemin) -> le
        PROCHAIN appel invoke_llm_with_fallback utilise réellement le
        modèle surchargé, via son propre appel interne à
        registry.refresh_cache_if_stale() (cf. app/llm/client.py).
        create_llm_from_spec est mocké (jamais un vrai appel réseau LLM) —
        tout le reste (registry, cache, DB) est réel.
        """
        async with get_db_context() as db:
            await SQLAlchemyModelConfigurationRepository(db).upsert(
                task_type=_TASK_TYPE, provider=ModelProvider.OPENAI, model_name="gpt-4o", timeout_seconds=55,
            )
        registry.invalidate_cache()

        fake_llm = AsyncMock()
        fake_llm.ainvoke.return_value = MagicMock(content="ok", response_metadata={})
        fake_http_client = AsyncMock()

        with patch(
            "app.model_registry.registry.create_llm_from_spec",
            return_value=(fake_llm, fake_http_client),
        ):
            result, spec, fallback_occurred, token_usage = await invoke_llm_with_fallback(
                task_type=_TASK_TYPE, messages=[{"role": "user", "content": "test"}],
            )

        assert spec.provider == ModelProvider.OPENAI
        assert spec.model_name == "gpt-4o"
        assert spec.timeout_seconds == 55
        assert fallback_occurred is False  # succès direct sur l'entrée primaire (désormais OpenAI/gpt-4o)
