"""
Tâche Celery déclenchée par ArbitrationService.resolve_correction() (câblage
teacher_arbitration_node, 2026-08-18) — UNIQUEMENT quand plus aucune
CorrectionArbitration PENDING ne reste sur la soumission (vérifié côté
service via CorrectionArbitrationRepository.has_pending_for_submission(),
jamais revérifié ici). Même structure que process_contestation_verification
(contestation_tasks.py) : vérifie qu'un Job actif existe exactement à
teacher_arbitration_node pour cette soumission avant de reprendre — un
thread jamais passé par le graph compilé (chemin direct historique) n'a
simplement aucun Job à reprendre, silencieux dans ce cas (jamais une erreur).
"""
import asyncio
import logging
import uuid

from app.core.broker import celery_app, CeleryQueue, DEFAULT_RETRY_POLICY
from app.core.database import engine, get_db_context
from app.infra_services.storage_service import storage_service
from app.domain.models.system_infrastructure.job import JobStatus
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.tasks.job_tasks import resume_thread

logger = logging.getLogger(__name__)

RESUME_ARBITRATION_RESOLVED = "arbitration_resolved"


@celery_app.task(
    bind=True,
    queue=CeleryQueue.MAINTENANCE,
    autoretry_for=(Exception,),
    # cf. submission_tasks.py::process_submission_created pour le détail du
    # bug réel corrigé — reprend student_evaluation, même ordre de grandeur.
    soft_time_limit=1800,
    time_limit=1860,
    **DEFAULT_RETRY_POLICY,
)
def process_arbitration_resolved(self, submission_id: str) -> None:
    logger.info(
        "Vérification de reprise après résolution d'arbitrage", extra={"submission_id": submission_id},
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
            job_repo = SQLAlchemyJobRepository(db)
            job = await job_repo.get_active_job_for_thread(uuid.UUID(submission_id))
            should_resume = (
                job is not None
                and job.status == JobStatus.INTERRUPTED
                and job.current_node == "teacher_arbitration_node"
            )

        if should_resume:
            await resume_thread(thread_id=submission_id, resume_value=RESUME_ARBITRATION_RESOLVED)

    asyncio.run(_run())

    logger.info(
        "Vérification de reprise après arbitrage terminée pour submission_id=%s", submission_id,
    )
