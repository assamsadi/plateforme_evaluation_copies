"""
Tâche Celery déclenchée par le consumer Kafka submission-created.v1 —
invoque désormais pipeline_graph.py (branche student_evaluation : entry ->
OCR étudiant+rattachement -> pause vérification étudiant) au lieu d'appeler
SubmissionOCRPipelineService directement (câblage LangGraph, conversation
"diagnostic + plan pipeline_graph").

Pipeline student_evaluation aujourd'hui :
  1. OCR_Extraction_Agent v3 + Question_Attachment_Agent (combinés dans
     question_attachment_node, cf. son docstring pour pourquoi)
  2. Pause réelle (interrupt(), await_student_verification_node) au lieu
     d'un simple retour après avoir posé PENDING_STUDENT_VERIFICATION en
     base — reprenable via job_tasks.py::process_job_resumed (confirmation
     simple ou contestation traitée, cf. cette tâche et
     contestation_tasks.py).
  3. [À venir] variantes, évaluation — pas câblés, rien en aval de la pause
     aujourd'hui (cf. diagnostic pipeline_graph).
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from app.agents.question_attachment_exceptions import (
    AttachmentTimeoutError,
    MissingReferenceSolutionError,
)
from app.core.broker import celery_app, CeleryQueue, DEFAULT_RETRY_POLICY
from app.core.database import engine, get_db_context
from app.infra_services.storage_service import storage_service
from app.core.exceptions import DocumentQualityError, DomainError, OCRExtractionError
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.graph.checkpointer import get_checkpointer
from app.graph.job_sync import mark_job_failed, sync_job_after_graph_run
from app.graph.pipeline_graph import compile_pipeline_graph
from app.graph.state import PipelineState
from app.observability.langfuse import AgentTraceSpan

logger = logging.getLogger(__name__)


class _FailureTrackingTask(celery_app.Task):
    """cf. app/tasks/exercise_tasks.py::_FailureTrackingTask — même correctif, même bug."""
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        submission_id = kwargs.get("submission_id")
        if submission_id:
            asyncio.run(mark_job_failed(uuid.UUID(submission_id), str(exc)))


# Mêmes états terminaux qu'avant le câblage (OCRExtractionError, AttachmentTimeoutError,
# MissingReferenceSolutionError, DocumentQualityError) : se reproduiraient à
# l'identique sur retry, jamais des pannes transitoires (celles-ci sont déjà
# gérées en amont, à l'intérieur des agents). Sans cette exclusion, Celery
# relance jusqu'à 5 fois (backoff jusqu'à 10 min) un échec garanti.
@celery_app.task(
    bind=True,
    base=_FailureTrackingTask,
    queue=CeleryQueue.LLM,
    autoretry_for=(Exception,),
    dont_autoretry_for=(
        DocumentQualityError,
        OCRExtractionError,
        AttachmentTimeoutError,
        MissingReferenceSolutionError,
    ),
    # Bug réel corrigé (2026-09-06, test réel) : sans limite de temps, une
    # coroutine réellement bloquée (ex. transaction Postgres "idle in
    # transaction" tenant un verrou consultatif indéfiniment, suite à une
    # boucle asyncio corrompue) ne lève jamais d'exception — task_acks_late
    # ne protège QUE contre un worker qui meurt, jamais contre une tâche
    # vivante mais figée dans un worker vivant. Résultat constaté : la
    # soumission restait bloquée indéfiniment, sans échec ni nouvelle
    # tentative, silence total. soft_time_limit lève SoftTimeLimitExceeded
    # dans la tâche (capturé par autoretry_for) ; time_limit (marge de 60s)
    # tue le process enfant si la tâche ignore le signal — task_reject_on_
    # worker_lost=True (déjà configuré) requeue alors automatiquement,
    # combiné à task_acks_late pour ne jamais perdre le message.
    soft_time_limit=1800,
    time_limit=1860,
    **DEFAULT_RETRY_POLICY,
)
def process_submission_created(
    self,
    submission_id: str,
    exercise_id: str,
    student_id: str,
    attempt_number: int,
    document_path: str,
    mime_type: str,
) -> None:
    """
    Point d'entrée du pipeline student_evaluation (OCR -> rattachement ->
    pause de vérification étudiant). Appelé par SubmissionCreatedConsumer
    après réception de l'événement Kafka.
    """
    logger.info(
        "Démarrage pipeline student_evaluation",
        extra={
            "submission_id": submission_id,
            "exercise_id": exercise_id,
            "student_id": student_id,
            "attempt_number": attempt_number,
            "document_path": document_path,
        },
    )

    async def _run() -> None:
        # cf. app/tasks/exercise_tasks.py::_run pour le détail — `engine`
        # (pool asyncpg) doit être disposé avant tout usage dans une NOUVELLE
        # boucle asyncio (chaque exécution/retry Celery en crée une via
        # asyncio.run), sous peine de "attached to a different loop".
        await engine.dispose()
        # cf. app/tasks/exercise_tasks.py::_run — même correctif pour le
        # deuxième singleton process-wide, storage_service (client Azure Blob).
        await storage_service.close()
        async with get_db_context() as db:
            exercise = await SQLAlchemyExerciseRepository(db).get_by_id(uuid.UUID(exercise_id))
        if exercise is None:
            logger.warning("Exercice introuvable pour exercise_id=%s — abandon", exercise_id)
            return

        now = datetime.now(timezone.utc)
        initial_state = PipelineState(
            thread_id=submission_id,
            flow_type="student_evaluation",
            trace_id=submission_id,
            exercise_id=exercise_id,
            submission_id=submission_id,
            module_id=str(exercise.module_id),
            student_id=student_id,
            raw_file_path=document_path,
            mime_type=mime_type,
            created_at=now,
            updated_at=now,
        )
        config = {"configurable": {"thread_id": submission_id}}

        try:
            # Span racine englobant TOUT le run du graph — même correctif
            # que exercise_tasks.py (cf. mémoire de session : sans lui,
            # chaque nœud/agent du graph devient sa propre racine Langfuse
            # déconnectée malgré un trace_id applicatif partagé).
            with AgentTraceSpan(
                "student_evaluation_pipeline", trace_id=str(submission_id),
                metadata={"flow_type": "student_evaluation", "submission_id": submission_id},
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
                "Qualité document insuffisante pour submission_id=%s : %s", submission_id, exc,
            )
            await mark_job_failed(uuid.UUID(submission_id), str(exc))
            return
        except OCRExtractionError as exc:
            logger.warning(
                "Échec OCR déterministe (format non supporté, aucune page "
                "extraite, ou soumission sans document associé) pour "
                "submission_id=%s : %s",
                submission_id, exc,
            )
            await mark_job_failed(uuid.UUID(submission_id), str(exc))
            return
        except AttachmentTimeoutError as exc:
            logger.warning(
                "Timeout global de rattachement dépassé pour submission_id=%s "
                "(copie trop longue/complexe — se reproduirait à l'identique "
                "sur retry) : %s",
                submission_id, exc,
            )
            await mark_job_failed(uuid.UUID(submission_id), str(exc))
            return
        except MissingReferenceSolutionError as exc:
            logger.warning(
                "Variante de référence manquante pour au moins une question "
                "de l'exercice, rattachement impossible pour submission_id=%s : %s",
                submission_id, exc,
            )
            await mark_job_failed(uuid.UUID(submission_id), str(exc))
            return
        except DomainError:
            # Repose la soumission en PENDING_OCR avant de relancer pour retry
            # Celery — nouvelle session, l'originale (ouverte dans le nœud du
            # graph) a déjà été rollback/fermée par get_db_context à ce stade.
            async with get_db_context() as db:
                await SQLAlchemySubmissionRepository(db).update_status(
                    uuid.UUID(submission_id), SubmissionStatus.PENDING_OCR,
                )
            raise

        next_node = state_snapshot.next[0] if state_snapshot.next else None
        await sync_job_after_graph_run(uuid.UUID(submission_id), result, next_node)

        if "__interrupt__" in result:
            interrupt_info = result["__interrupt__"][0].value
            logger.info(
                "Pipeline student_evaluation en pause pour submission_id=%s : %s",
                submission_id, interrupt_info.get("reason"),
            )
            return

        logger.info("Pipeline student_evaluation terminé pour submission_id=%s", submission_id)

    asyncio.run(_run())
