"""
Tâche Celery pour le pipeline exercise_setup complet (document de référence
professeur) — invoque désormais pipeline_graph.py (branche exercise_setup :
entry -> structuration -> vérification d'extraction) au lieu d'appeler
ExerciseOCRPipelineService directement (câblage LangGraph, conversation
"diagnostic + plan pipeline_graph").

StructuringIncompleteError n'est plus levée jusqu'ici : elle devient une
pause de graph (interrupt(), await_structuring_resolution_node, cf.
pipeline_graph.py) — le run se termine normalement (ainvoke() retourne,
aucune exception), la pause se lit dans le résultat via la clé
"__interrupt__". Même principe pour une clarification BLOCKING côté
Extraction_Verification_Agent (jamais une exception non plus avant ce
câblage : déjà un champ de résultat, cf. Phase 6).

Deux classes ExerciseAlreadyPublishedError distinctes coexistent dans ce
run désormais (une par agent, jamais partagées entre eux) :
document_structuring_exceptions (Document_Structuring_Agent) et
extraction_verification_exceptions (Extraction_Verification_Agent,
maintenant chaîné dans le même run) — les deux exclues du retry Celery,
sémantique terminale identique (republication refusée).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.agents.document_structuring_exceptions import ClassificationSchemaError
from app.agents.document_structuring_exceptions import (
    ExerciseAlreadyPublishedError as StructuringExerciseAlreadyPublishedError,
)
from app.agents.extraction_verification_exceptions import (
    ExerciseAlreadyPublishedError as ExtractionExerciseAlreadyPublishedError,
)
from app.core.broker import celery_app, CeleryQueue, DEFAULT_RETRY_POLICY
from app.core.database import engine, get_db_context
from app.infra_services.storage_service import storage_service
from app.core.exceptions import (
    DocumentQualityError,
    DomainError,
    ExerciseNotFoundError,
    OCRExtractionError,
)
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.graph.checkpointer import get_checkpointer
from app.graph.job_sync import mark_job_failed, sync_job_after_graph_run
from app.graph.pipeline_graph import compile_pipeline_graph
from app.graph.state import PipelineState
from app.observability.langfuse import AgentTraceSpan

logger = logging.getLogger(__name__)


class _FailureTrackingTask(celery_app.Task):
    """
    on_failure() : Celery l'appelle exactement une fois pour l'échec
    TERMINAL d'une tâche — après épuisement de tous les retries (autoretry_for),
    jamais à chaque tentative individuelle (celles-ci restent RUNNING pendant
    le backoff, correct). Seul point qui marque Job FAILED pour une exception
    inconnue non captée dans _run() (ex. 429 provider épuisant tout le
    fallback puis les 5 retries Celery, constaté en session — Job restait
    bloqué à RUNNING indéfiniment, aucun code n'écrivait jamais FAILED).
    """
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        exercise_id = kwargs.get("exercise_id")
        if exercise_id:
            asyncio.run(mark_job_failed(uuid.UUID(exercise_id), str(exc)))


# Mêmes états terminaux qu'avant le câblage (StructuringIncompleteError en
# moins, désormais une pause de graph, jamais une exception ; deux nouvelles
# entrées : la variante Extraction_Verification_Agent d'ExerciseAlreadyPublishedError,
# et ExerciseNotFoundError — retenter un exercice inexistant ne changerait
# jamais le résultat). Sans cette exclusion, Celery relance jusqu'à 5 fois
# (backoff jusqu'à 10 min) un échec garanti de se reproduire à l'identique,
# en re-payant le coût LLM et en risquant une double persistance.
@celery_app.task(
    bind=True,
    base=_FailureTrackingTask,
    queue=CeleryQueue.OCR,
    autoretry_for=(Exception,),
    dont_autoretry_for=(
        DocumentQualityError,
        OCRExtractionError,
        StructuringExerciseAlreadyPublishedError,
        ExtractionExerciseAlreadyPublishedError,
        ClassificationSchemaError,
        ExerciseNotFoundError,
    ),
    # cf. submission_tasks.py::process_submission_created pour le détail du
    # bug réel corrigé (blocage silencieux sans limite de temps) — seuil
    # plus large : structuration + vérification + génération de variantes
    # pour TOUTES les questions d'un exercice, constaté à >1000s même sur
    # un run réel réussi sous rate-limiting Gemini.
    soft_time_limit=2700,
    time_limit=2760,
    **DEFAULT_RETRY_POLICY,
)
def process_exercise_reference_document(
    self,
    exercise_id: str,
    professor_id: str,
    document_path: str,
    mime_type: str,
) -> None:
    """Point d'entrée du pipeline exercise_setup (OCR -> structuration -> vérification d'extraction)."""
    logger.info(
        "Démarrage pipeline exercise_setup",
        extra={
            "exercise_id": exercise_id,
            "professor_id": professor_id,
            "document_path": document_path,
        },
    )

    async def _run() -> None:
        # `engine` (app/core/database.py) est un singleton process-wide dont
        # le pool de connexions asyncpg est lié à la boucle asyncio active
        # au moment du checkout. Ici, chaque exécution de tâche Celery (et
        # CHAQUE retry) tourne dans son propre asyncio.run() — une nouvelle
        # boucle à chaque fois — alors qu'un process worker Celery survit à
        # plusieurs exécutions. Sans dispose(), une connexion déjà en pool
        # depuis un run précédent (boucle désormais fermée) est reprise sur
        # la boucle courante -> RuntimeError("... attached to a different
        # loop" / "Event loop is closed"), constaté en test réel (dépôt
        # document de référence, plusieurs retries). dispose() est sans
        # effet si le pool est déjà vide (premier run du process).
        await engine.dispose()
        # Même piège, même correctif, pour un DEUXIÈME singleton process-wide :
        # storage_service (BlobServiceClient Azure, app/infra_services/
        # storage_service.py) — sa détection interne de boucle fermée
        # (_get_client) s'est révélée inopérante en test réel (RuntimeError
        # "Event loop is closed" dans scan_quality_control_node malgré le
        # fix engine.dispose() ci-dessus). close() force une reconstruction
        # paresseuse propre à la boucle courante au prochain appel.
        await storage_service.close()
        async with get_db_context() as db:
            exercise = await SQLAlchemyExerciseRepository(db).get_by_id(uuid.UUID(exercise_id))
        if exercise is None:
            logger.warning("Exercice introuvable pour exercise_id=%s — abandon", exercise_id)
            return

        now = datetime.now(timezone.utc)
        initial_state = PipelineState(
            thread_id=exercise_id,
            flow_type="exercise_setup",
            trace_id=exercise_id,
            exercise_id=exercise_id,
            module_id=str(exercise.module_id),
            professor_id=professor_id,
            raw_file_path=document_path,
            mime_type=mime_type,
            created_at=now,
            updated_at=now,
        )
        config = {"configurable": {"thread_id": exercise_id}}

        try:
            # Span racine englobant TOUT le run du graph (cf. mémoire de
            # session : sans ce span, chaque nœud/agent appelé À L'INTÉRIEUR
            # du graph ferme son propre span avant que le nœud suivant
            # démarre — le contexte ambiant est donc systématiquement vide
            # pour le nœud suivant, et TOUS deviennent leur propre racine
            # Langfuse déconnectée malgré un trace_id applicatif partagé).
            with AgentTraceSpan(
                "exercise_setup_pipeline", trace_id=str(exercise_id),
                metadata={"flow_type": "exercise_setup", "exercise_id": exercise_id},
            ) as pipeline_span:
                async with get_checkpointer() as checkpointer:
                    graph = compile_pipeline_graph(checkpointer)
                    result = await graph.ainvoke(initial_state, config=config)
                    state_snapshot = await graph.aget_state(config)
                pipeline_span.record_metrics(
                    interrupted="__interrupt__" in result,
                    next_node=state_snapshot.next[0] if state_snapshot.next else None,
                )
        except DocumentQualityError as exc:
            logger.warning(
                "Qualité document insuffisante pour exercise_id=%s : %s", exercise_id, exc,
            )
            await mark_job_failed(uuid.UUID(exercise_id), str(exc))
            return
        except OCRExtractionError as exc:
            logger.warning(
                "Échec OCR déterministe (format non supporté, aucune page "
                "extraite, ou exercice pas en DRAFT) pour exercise_id=%s : %s",
                exercise_id, exc,
            )
            await mark_job_failed(uuid.UUID(exercise_id), str(exc))
            return
        except (StructuringExerciseAlreadyPublishedError, ExtractionExerciseAlreadyPublishedError) as exc:
            logger.warning(
                "Exercice déjà publié, traitement automatique refusé pour exercise_id=%s : %s",
                exercise_id, exc,
            )
            await mark_job_failed(uuid.UUID(exercise_id), str(exc))
            return
        except ClassificationSchemaError as exc:
            logger.error(
                "Échec technique de classification LLM (schéma non conforme après "
                "retry) pour exercise_id=%s : %s",
                exercise_id, exc,
            )
            await mark_job_failed(uuid.UUID(exercise_id), str(exc))
            return
        except DomainError:
            raise

        next_node = state_snapshot.next[0] if state_snapshot.next else None
        await sync_job_after_graph_run(uuid.UUID(exercise_id), result, next_node)

        if "__interrupt__" in result:
            interrupt_info = result["__interrupt__"][0].value
            logger.info(
                "Pipeline exercise_setup en pause pour exercise_id=%s : %s",
                exercise_id, interrupt_info.get("reason"),
            )
            return

        logger.info("Pipeline exercise_setup terminé pour exercise_id=%s", exercise_id)

    asyncio.run(_run())
