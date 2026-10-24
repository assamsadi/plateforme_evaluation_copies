"""
Tâche Celery — déclencheur guidé (2.3) de Solution_Variant_Generation_Agent.

Traitement en arrière-plan du point de vue du professeur (job en tâche de
fond, notification quand prêt, cf. audit Solution_Variant_Generation_Agent
§1c/§2.3) — contrairement au déclencheur 2.2, aucune copie d'étudiant n'est
en attente ici, donc PAS de passage par pipeline_graph.py/interrupt() : un
simple job Celery direct sur SolutionVariantGenerationService suffit, comme
documenté dans la spec ("aucune copie d'étudiant en attente ici, pas besoin
du mécanisme de pause du point 2.2").

Queue LLM (app/core/broker.py::CeleryQueue.LLM mentionne déjà explicitement
"variant_generation" dans son commentaire d'intention).
"""
import asyncio
import logging
import uuid

from app.agents.solution_variant_generation_exceptions import (
    ExerciseAlreadyPublishedError,
    SolutionVariantGenerationError,
)
from app.core.broker import celery_app, CeleryQueue, DEFAULT_RETRY_POLICY
from app.core.database import engine, get_db_context
from app.infra_services.storage_service import storage_service
from app.services.solution_variant_generation_service import SolutionVariantGenerationService

logger = logging.getLogger(__name__)


# ExerciseAlreadyPublishedError n'est en réalité jamais levée sur ce chemin
# (2.3 = "guided" est explicitement exclu du blocage post-publication, cf.
# SolutionVariantGenerationService.generate_variants_for_question) — exclue
# du retry Celery par cohérence défensive avec les autres tâches de ce
# projet malgré tout, au cas où la garde évoluerait un jour.
@celery_app.task(
    bind=True,
    queue=CeleryQueue.LLM,
    autoretry_for=(Exception,),
    dont_autoretry_for=(
        ExerciseAlreadyPublishedError,
        SolutionVariantGenerationError,
    ),
    **DEFAULT_RETRY_POLICY,
)
def generate_guided_variant_task(
    self,
    question_id: str,
    professor_id: str,
    method_hint: str | None,
    concept_hint: list[str] | None,
) -> None:
    """Point d'entrée du déclencheur guidé (2.3)."""
    logger.info(
        "Démarrage génération guidée de variante",
        extra={"question_id": question_id, "professor_id": professor_id},
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
            service = SolutionVariantGenerationService(db)
            try:
                await service.generate_guided_variant_and_notify(
                    question_id=uuid.UUID(question_id),
                    professor_id=uuid.UUID(professor_id),
                    method_hint=method_hint,
                    concept_hint=concept_hint,
                    trace_id=question_id,
                )
            except (ExerciseAlreadyPublishedError, SolutionVariantGenerationError) as exc:
                logger.warning(
                    "Génération guidée refusée pour question_id=%s : %s", question_id, exc,
                )
                return

    asyncio.run(_run())
