"""
Tâche Celery déclenchée directement par l'endpoint HTTP de dépôt de
contestation (extraction_service.contest_extraction) — un .delay(...)
immédiat, INCHANGÉ (double point d'entrée assumé, cf. contestation_
verification_node.py et le plan validé en conversation : ce chemin direct
reste utilisable tel quel même pour une soumission jamais passée par le
graph).

Pipeline :
  1. Charge tous les blocs PENDING_VERIFICATION de la soumission.
  2. ContestationVerificationService.process_pending_contestations().
  3. Persistance déjà faite par le service lui-même.
  4. AJOUT (câblage LangGraph) : si un thread de graph est actuellement en
     pause exactement à await_student_verification_node pour cette
     soumission, le reprend (job_tasks.py::process_job_resumed) pour que le
     résultat de CE traitement soit reflété dans le thread checkpointé —
     jamais l'inverse (ce traitement direct ne dépend JAMAIS de l'existence
     d'un tel thread, cf. le if ci-dessous : silencieux si absent).
"""
import asyncio
import logging
import uuid

from app.agents.context import AgentExecutionContext
from app.agents.contestation_verification_exceptions import (
    AlreadyResolvedContestationError,
    FusionGroupNotFoundError,
    StructureElementNotFoundError,
)
from app.agents.question_attachment_exceptions import MissingReferenceSolutionError
from app.core.broker import celery_app, CeleryQueue, DEFAULT_RETRY_POLICY
from app.core.database import engine, get_db_context
from app.infra_services.storage_service import storage_service
from app.domain.models.system_infrastructure.job import JobStatus
from app.domain.repositories.agent_decision_log_repository import (
    SQLAlchemyAgentDecisionLogRepository,
)
from app.domain.repositories.correction_arbitration_repository import (
    SQLAlchemyCorrectionArbitrationRepository,
)
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.extraction_correction_repository import (
    SQLAlchemyExtractionCorrectionRepository,
)
from app.domain.repositories.integrity_alert_repository import SQLAlchemyIntegrityAlertRepository
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.services.contestation_verification_service import ContestationVerificationService
from app.tasks.job_tasks import resume_thread

logger = logging.getLogger(__name__)


# Mêmes états terminaux déterministes que process_submission_created exclut
# déjà du retry (submission_tasks.py) : se reproduiraient à l'identique, un
# retry Celery ne peut rien y changer. Les erreurs fournisseur LLM transitoires
# (VisionProviderError et consorts) restent volontairement incluses dans le
# retry générique — gérées à l'intérieur de l'agent pour le fallback fournisseur,
# mais un échec total de la chaîne mérite un nouveau passage plus tard.
@celery_app.task(
    bind=True,
    queue=CeleryQueue.LLM,
    autoretry_for=(Exception,),
    dont_autoretry_for=(
        AlreadyResolvedContestationError,
        FusionGroupNotFoundError,
        StructureElementNotFoundError,
        MissingReferenceSolutionError,
        ValueError,
    ),
    # cf. submission_tasks.py::process_submission_created pour le détail du
    # bug réel corrigé (blocage silencieux sans limite de temps) — même
    # correctif, seuil plus court : cette tâche relit des blocs déjà extraits
    # (pas d'OCR), charge de travail structurellement plus légère.
    soft_time_limit=900,
    time_limit=960,
    **DEFAULT_RETRY_POLICY,
)
def process_contestation_verification(self, submission_id: str) -> None:
    """
    Point d'entrée : traite TOUS les blocs PENDING_VERIFICATION d'une
    soumission, pas seulement celui qui vient d'être contesté (§2 étape 4 —
    plusieurs blocs contestés sur une même soumission sont traités,
    indépendamment, dans le même passage).
    """
    logger.info(
        "Démarrage du traitement des contestations", extra={"submission_id": submission_id},
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
            submission_repo = SQLAlchemySubmissionRepository(db)
            # Verrou consultatif AVANT toute lecture/décision — même clé que
            # ExtractionService.confirm_submission (cf. docstring
            # SubmissionRepositoryProtocol.acquire_advisory_lock), pour
            # sérialiser cette tâche avec une confirmation étudiante
            # concurrente sur le MÊME thread LangGraph (await_student_
            # verification_node ne peut recevoir qu'un seul resume() —
            # bug réel corrigé 2026-09-06, arbitrage créé après coup
            # restait orphelin sans ce verrou).
            await submission_repo.acquire_advisory_lock(uuid.UUID(submission_id))

            submission = await submission_repo.get_by_id(uuid.UUID(submission_id))
            if submission is None:
                logger.warning(
                    "Soumission introuvable pour submission_id=%s — abandon", submission_id,
                )
                return

            service = ContestationVerificationService(
                extraction_correction_repo=SQLAlchemyExtractionCorrectionRepository(db),
                correction_arbitration_repo=SQLAlchemyCorrectionArbitrationRepository(db),
                submission_repo=submission_repo,
                exercise_repo=SQLAlchemyExerciseRepository(db),
                solution_variant_repo=SQLAlchemySolutionVariantRepository(db),
                decision_log_repo=SQLAlchemyAgentDecisionLogRepository(db),
                integrity_alert_repo=SQLAlchemyIntegrityAlertRepository(db),
            )
            context = AgentExecutionContext(
                trace_id=submission_id,
                flow_type="student_evaluation",
                submission_id=submission.id,
                exercise_id=submission.exercise_id,
            )
            result = await service.process_pending_contestations(submission.id, context)

            job_repo = SQLAlchemyJobRepository(db)
            job = await job_repo.get_active_job_for_thread(submission.id)
            should_resume = (
                job is not None
                and job.status == JobStatus.INTERRUPTED
                and job.current_node == "await_student_verification_node"
            )

        # await direct (jamais process_job_resumed appelé comme un simple
        # callable ici) : _run() tourne déjà dans un asyncio.run() propre à
        # CETTE tâche — imbriquer un second asyncio.run() (celui de
        # process_job_resumed) plante avec "cannot be called from a running
        # event loop", constaté à l'écriture du test d'intégration. resume_thread()
        # est la même logique, nue, faite pour cet appel-ci.
        if should_resume:
            await resume_thread(thread_id=submission_id, resume_value="contestation_pending")

    asyncio.run(_run())

    logger.info(
        "Traitement des contestations terminé pour submission_id=%s", submission_id,
    )
