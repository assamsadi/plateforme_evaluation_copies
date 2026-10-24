"""
Exécuteur d'appels LLM haut niveau avec fallback transparent entre fournisseurs (Groq -> OpenAI/Azure_OpenAI).
"""
import asyncio
import logging
import re
import uuid
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agents.context import AgentExecutionContext
from app.core.config import settings
from app.core.database import get_db_context
from app.core.exceptions import LLMBudgetExceededError, VisionProviderError
from app.core.provider_credentials import credential_cache
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.llm.retry import infrastructure_retry
from app.model_registry.models import ModelSpec, TaskType
from app.model_registry.registry import registry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Rate limiting fournisseur (429/413 "rate_limit_exceeded") — constaté en
# usage réel sur le palier gratuit Groq (plafond TPM). Détection robuste
# sans dépendre d'une hiérarchie d'exception précise : Groq et OpenAI
# utilisent 2 SDK différents (groq.APIStatusError vs openai.APIStatusError),
# tous deux posent status_code à l'INSTANCE (jamais visible via hasattr sur
# la classe) — on lit l'attribut s'il existe, sinon on retombe sur le
# message déjà formaté par le SDK ("Error code: 429/413 - ..."), TOUJOURS
# combiné à la présence du marqueur "rate_limit" (jamais un 413 générique
# quelconque, ex. une image réellement trop volumineuse doit rester un
# échec définitif, pas un cas à attendre puis réessayer).
_RATE_LIMIT_STATUS_CODES = (429, 413)
_RATE_LIMIT_CODE_PATTERN = re.compile(r"error code:\s*(\d+)", re.IGNORECASE)


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    if status_code is None:
        match = _RATE_LIMIT_CODE_PATTERN.search(message)
        status_code = int(match.group(1)) if match else None
    return status_code in _RATE_LIMIT_STATUS_CODES and "rate_limit" in message


def _resolve_thread_id(context: AgentExecutionContext | None) -> uuid.UUID | None:
    """thread_id = submission_id (student_evaluation) ou exercise_id (exercise_setup) — même convention que Job."""
    if context is None:
        return None
    return context.submission_id or context.exercise_id


@infrastructure_retry(max_attempts=2)
async def _execute_single_provider_async(
    llm: Any,
    messages: list[Any],
    response_schema: type[T] | None = None,
) -> tuple[T | Any, dict]:
    """Exécute un appel à un fournisseur LLM avec retry d'infrastructure."""
    if response_schema is not None:
        structured_llm = llm.with_structured_output(response_schema)
        result = await structured_llm.ainvoke(messages)
    else:
        result = await llm.ainvoke(messages)
    
    # Métriques approximatives de tokens si disponibles
    token_usage = getattr(result, "response_metadata", {}).get("token_usage", {})
    return result, token_usage


async def _execute_with_rate_limit_retry(
    llm: Any,
    messages: list[Any],
    response_schema: type[T] | None,
    spec: ModelSpec,
    task_type: TaskType,
) -> tuple[T | Any, dict]:
    """
    Retries UNIQUEMENT sur un rate limit fournisseur détecté (cf. _is_rate_
    limit_error) — distinct d'infrastructure_retry déjà appliqué à
    _execute_single_provider_async ci-dessus (réseau/5xx, backoff court
    <=10s) : un plafond TPM se libère sur une fenêtre ~1 minute, jamais
    résolu par un backoff de quelques secondes. Réessaie CE MÊME fournisseur
    (jamais un basculement immédiat) jusqu'à Settings.LLM_RATE_LIMIT_MAX_
    RETRIES fois, avec une attente Settings.LLM_RATE_LIMIT_WAIT_SECONDS
    entre chaque tentative — au-delà, l'exception remonte telle quelle et
    invoke_llm_with_fallback bascule sur le fournisseur suivant de la
    chaîne, comportement de repli déjà existant, jamais supprimé.
    """
    max_retries = settings.LLM_RATE_LIMIT_MAX_RETRIES
    for attempt in range(max_retries):
        try:
            return await _execute_single_provider_async(
                llm=llm, messages=messages, response_schema=response_schema,
            )
        except Exception as e:
            if not _is_rate_limit_error(e) or attempt == max_retries - 1:
                raise
            wait_seconds = settings.LLM_RATE_LIMIT_WAIT_SECONDS
            logger.warning(
                f"Rate limit atteint pour {spec.provider} ({spec.model_name}) sur {task_type} — "
                f"attente de {wait_seconds}s avant nouvelle tentative sur ce même fournisseur "
                f"(#{attempt + 1}/{max_retries}) : {e}"
            )
            await asyncio.sleep(wait_seconds)
    # Défensif — la boucle re-lève toujours avant d'arriver ici (dernier
    # essai jamais retenté), jamais atteint en pratique.
    raise AssertionError("_execute_with_rate_limit_retry: boucle de retry sortie sans résultat ni exception")


async def invoke_llm_with_fallback(
    task_type: TaskType,
    messages: list[Any],
    response_schema: type[T] | None = None,
    context: AgentExecutionContext | None = None,
) -> tuple[T | Any, ModelSpec, bool, dict]:
    """
    Tente la chaîne de fournisseurs enregistrés pour `task_type`.
    En cas d'erreur réseau/5xx/timeout sur le fournisseur principal,
    bascule automatiquement sur le fournisseur suivant dans la chaîne (ex. Groq -> OpenAI).

    context : si fourni (submission_id/exercise_id résolu en thread_id),
    active le plafond d'appels LLM par thread (Settings.MAX_LLM_CALLS_
    PER_THREAD, cf. Job.llm_call_count, audit "garanties transverses" Plan
    D) — vérifié avant toute tentative, incrémenté à CHAQUE tentative
    (succès ou échec, fallback inclus, puisque chacune consomme réellement
    un appel fournisseur). Sans context (None), aucun garde-fou appliqué —
    ex. appels hors graph (tests, scripts).

    Retourne:
        (resultat_pydantic_ou_msg, spec_utilisee, fallback_effectue, token_usage)
    """
    thread_id = _resolve_thread_id(context)
    if thread_id is not None:
        async with get_db_context() as db:
            job = await SQLAlchemyJobRepository(db).get_active_job_for_thread(thread_id)
            if job is not None and job.llm_call_count >= settings.MAX_LLM_CALLS_PER_THREAD:
                raise LLMBudgetExceededError(
                    thread_id=str(thread_id),
                    max_calls=settings.MAX_LLM_CALLS_PER_THREAD,
                )

    # Chantier "Configuration des modèles IA" (admin) — no-op si le cache
    # n'est pas encore périmé (TTL, cf. docstring ModelRegistry), jamais
    # une requête DB à chaque appel. Best-effort (jamais levé vers
    # l'appelant, cf. ModelRegistry.refresh_cache_if_stale).
    await registry.refresh_cache_if_stale()
    # Même principe pour les secrets fournisseurs (clés API) — cache
    # séparé (app/core/provider_credentials.py), consommé par
    # create_llm_from_spec au moment de get_llm_chain() ci-dessous.
    await credential_cache.refresh_if_stale()

    chain = registry.get_llm_chain(task_type)
    accumulated_errors: list[Exception] = []
    fallback_occurred = False

    try:
        for idx, (llm, spec, http_client) in enumerate(chain):
            if idx > 0:
                fallback_occurred = True
                logger.info(
                    f"Fallback déclenché pour {task_type} : bascule vers le fournisseur {spec.provider} ({spec.model_name})"
                )

            if thread_id is not None:
                async with get_db_context() as db:
                    await SQLAlchemyJobRepository(db).increment_llm_call_count(thread_id)

            try:
                result, token_usage = await _execute_with_rate_limit_retry(
                    llm=llm,
                    messages=messages,
                    response_schema=response_schema,
                    spec=spec,
                    task_type=task_type,
                )
                return result, spec, fallback_occurred, token_usage
            except Exception as e:
                logger.warning(
                    f"Échec du fournisseur {spec.provider} ({spec.model_name}) pour {task_type} : {e}"
                )
                accumulated_errors.append(e)

        raise VisionProviderError(
            f"Tous les fournisseurs LLM ont échoué pour la tâche {task_type}",
            errors=accumulated_errors,
        )
    finally:
        # Ferme TOUS les httpx.AsyncClient de la chaîne, y compris ceux des
        # fournisseurs de secours jamais tentés (get_llm_chain construit la
        # chaîne ENTIÈRE à l'avance — Groq+OpenAI — pas seulement le
        # fournisseur effectivement utilisé ; un retour anticipé dès le
        # premier succès laissait les httpx.AsyncClient des fallbacks
        # suivants construits mais jamais fermés). aclose() est idempotent
        # (sans effet si déjà fermé), donc rappeler ici sur un client déjà
        # fermé par une tentative précédente est sûr.
        for _, _, remaining_client in chain:
            if remaining_client is not None:
                await remaining_client.aclose()
