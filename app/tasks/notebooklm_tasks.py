"""
Tâche Celery — génération best-effort d'un notebook NotebookLM enrichissant
le feedback d'une recommandation, PUIS des formats de sortie automatiques
(§7 cahier des charges, "Feedback Intelligent" — intégration NotebookLM,
Partie 1/2 : notebook + source ; Partie 2/2 : audio + flashcards
conditionnelles, rattachement des recommandations, événement Kafka séparé).

Dispatchée depuis feedback_node.py (chantier Feedback_Agent — déplacé
depuis recommendation_node.py, cf. son docstring) : feedback_text est
désormais transmis en plus de competency_lines_data/recommendations_data,
et devient la source principale du notebook côté NotebookLMService (repli
sur l'ancien contournement déterministe si absent, cf. sa docstring).

Détachée du graph LangGraph — jamais appelée depuis un nœud de façon
synchrone (cf. docstring feedback_node.py) : la génération NotebookLM peut
prendre plusieurs minutes au total (notebook + audio + flashcards, appels
réseau réels vers un service tiers non garanti), le nœud du graph ne doit
jamais l'attendre. Câblée en `.delay()` fire-and-forget juste après que
generate_recommendations() a persisté son résultat — le pipeline principal
(note, recommandations, notification Kafka recommendation-generated.v1)
est déjà entièrement terminé au moment où cette tâche s'exécute.

Queue LLM (app/core/broker.py::CeleryQueue.LLM mentionne déjà explicitement
"recommendation" dans son commentaire d'intention).

AUCUN retry automatique, volontairement — décision distincte des autres
tâches de ce projet (qui utilisent DEFAULT_RETRY_POLICY) : marteler un
point d'accès Google non documenté après un premier échec risquerait de
signaler le compte comme abusif, contrairement à un retry légitime contre
notre propre infrastructure. NotebookLMService ne lève de toute façon
jamais d'exception (best-effort interne, cf. son docstring) — il n'y a
donc rien à intercepter ici pour un retry côté Celery.

Enchaînement (Partie 2/2) — chaque étape APRÈS la création du notebook est
indépendamment isolée (son propre try/except) : l'échec de l'audio ne doit
JAMAIS empêcher la tentative des flashcards, ni inversement.
  1. Notebook + source (Partie 1/2) — si échec, rien d'autre n'est tenté
     (pas de notebook = rien à enrichir), aucune ligne StudentNotebook créée.
  2. Rattachement des RecommendedExercise déjà persistées à ce notebook
     (cf. RecommendedExerciseRepository.link_to_notebook).
  3. Audio Overview — toujours tenté.
  4. Flashcards — UNIQUEMENT si au moins une compétence de cette génération
     a des weaknesses/identified_difficulties réelles (jamais de flashcards
     vides/génériques, cf. contrainte explicite du ticket).
  5. Événement Kafka notebooklm-enrichment-completed.v1 (séparé de
     recommendation-generated.v1, cf. docstring event_schemas.py) — publié
     une fois les étapes 3/4 tentées, jamais avant.

Video Overview volontairement ABSENTE d'ici — jamais générée
automatiquement, uniquement à la demande explicite de l'étudiant via
generate_video_overview_task (cf. ce module), déclenchée par l'endpoint
POST .../generate-video.
"""
import asyncio
import logging
import uuid

from app.core.broker import celery_app, CeleryQueue
from app.core.database import engine, get_db_context
from app.infra_services.storage_service import storage_service
from app.domain.models.assessment.student_notebook import GenerationStatus, VideoOverviewStatus
from app.domain.repositories.recommended_exercise_repository import (
    SQLAlchemyRecommendedExerciseRepository,
)
from app.domain.repositories.student_notebook_repository import (
    SQLAlchemyStudentNotebookRepository,
)
from app.domain.schemas.event_schemas import NotebookLMEnrichmentCompletedPayload
from app.services.event_publisher_service import EventPublisherService, publish_notification_best_effort
from app.services.notebooklm_service import NotebookLMService

logger = logging.getLogger(__name__)


def _has_real_weakness_data(competency_lines_data: list[dict]) -> bool:
    """Jamais de flashcards vides/génériques — au moins une weakness/difficulty réelle sur AU MOINS une compétence."""
    return any(
        line.get("weaknesses") or line.get("identified_difficulties")
        for line in competency_lines_data
    )


@celery_app.task(queue=CeleryQueue.LLM, time_limit=750, soft_time_limit=720)
def generate_notebook_for_recommendations_task(
    student_id: str,
    module_id: str,
    submission_id: str | None,
    competency_lines_data: list[dict],
    recommendations_data: list[dict],
    feedback_text: str | None = None,
) -> None:
    async def _run() -> None:
        # cf. app/tasks/exercise_tasks.py::_run pour le détail — `engine`
        # (pool asyncpg, utilisé indirectement via NotebookLMService) doit
        # être disposé avant tout usage dans une NOUVELLE boucle asyncio.
        await engine.dispose()
        # cf. app/tasks/exercise_tasks.py::_run — même correctif pour le
        # deuxième singleton process-wide, storage_service (client Azure Blob).
        await storage_service.close()
        service = NotebookLMService()
        handle = await service.create_notebook_for_feedback(
            student_id=uuid.UUID(student_id),
            competency_lines=competency_lines_data,
            recommendations=recommendations_data,
            feedback_text=feedback_text,
        )
        if handle is None:
            # Déjà loggé en WARNING par le service (échec réel ou intégration
            # non configurée) — rien de plus à faire, best-effort.
            return

        async with get_db_context() as db:
            notebook_record = await SQLAlchemyStudentNotebookRepository(db).create(
                student_id=uuid.UUID(student_id),
                module_id=uuid.UUID(module_id),
                submission_id=uuid.UUID(submission_id) if submission_id else None,
                notebook_id=handle.notebook_id,
            )
            await SQLAlchemyRecommendedExerciseRepository(db).link_to_notebook(
                student_id=uuid.UUID(student_id),
                module_id=uuid.UUID(module_id),
                submission_id=uuid.UUID(submission_id) if submission_id else None,
                student_notebook_id=notebook_record.id,
            )
        logger.info(
            "Notebook NotebookLM créé et rattaché pour student_id=%s : %s",
            student_id, handle.notebook_id,
        )

        audio_generated = False
        try:
            audio_blob_path = f"notebooklm/audio/{notebook_record.id}.mp3"
            audio_path = await service.generate_audio_overview(handle.notebook_id, audio_blob_path)
            if audio_path is not None:
                async with get_db_context() as db:
                    await SQLAlchemyStudentNotebookRepository(db).update_audio_overview_path(
                        notebook_record.id, audio_path,
                    )
                audio_generated = True
        except Exception:
            logger.warning(
                "Échec isolé de la génération audio pour notebook_id=%s — "
                "n'affecte pas les flashcards.", handle.notebook_id, exc_info=True,
            )

        flashcards_generated = False
        if _has_real_weakness_data(competency_lines_data):
            try:
                flashcards_blob_path = f"notebooklm/flashcards/{notebook_record.id}.json"
                flashcards_path = await service.generate_flashcards(handle.notebook_id, flashcards_blob_path)
                if flashcards_path is not None:
                    async with get_db_context() as db:
                        await SQLAlchemyStudentNotebookRepository(db).update_flashcards_path(
                            notebook_record.id, flashcards_path,
                        )
                    flashcards_generated = True
            except Exception:
                logger.warning(
                    "Échec isolé de la génération flashcards pour notebook_id=%s — "
                    "n'affecte pas l'audio.", handle.notebook_id, exc_info=True,
                )
        else:
            logger.info(
                "Aucune weakness/identified_difficulty réelle pour student_id=%s — "
                "flashcards volontairement sautées (jamais de flashcards génériques).",
                student_id,
            )

        events = EventPublisherService()
        await publish_notification_best_effort(
            events.publish_notebooklm_enrichment_completed(
                NotebookLMEnrichmentCompletedPayload(
                    student_id=uuid.UUID(student_id), module_id=uuid.UUID(module_id),
                    submission_id=uuid.UUID(submission_id) if submission_id else None,
                    notebook_id=handle.notebook_id,
                    audio_generated=audio_generated, flashcards_generated=flashcards_generated,
                )
            )
        )

    asyncio.run(_run())


@celery_app.task(queue=CeleryQueue.LLM, time_limit=750, soft_time_limit=720)
def generate_video_overview_task(student_notebook_id: str, notebook_id: str) -> None:
    """
    Video Overview À LA DEMANDE UNIQUEMENT — déclenchée exclusivement par
    POST /students/{id}/recommendations/{id}/generate-video (cf. son
    docstring pour le contrôle d'accès self + la déduplication). Jamais
    appelée automatiquement, jamais depuis generate_notebook_for_
    recommendations_task ci-dessus.

    student_notebook_id : id INTERNE (uuid) de la ligne StudentNotebook à
    mettre à jour — jamais recherché à nouveau ici (déjà résolu et vérifié
    par l'endpoint avant dispatch, cf. VideoOverviewStatus.PENDING déjà
    posé par l'endpoint lui-même AVANT ce `.delay()`, pas par cette tâche).
    """
    async def _run() -> None:
        # cf. app/tasks/exercise_tasks.py::_run pour le détail — `engine`
        # (pool asyncpg, utilisé indirectement via NotebookLMService) doit
        # être disposé avant tout usage dans une NOUVELLE boucle asyncio.
        await engine.dispose()
        # cf. app/tasks/exercise_tasks.py::_run — même correctif pour le
        # deuxième singleton process-wide, storage_service (client Azure Blob).
        await storage_service.close()
        service = NotebookLMService()
        blob_path = f"notebooklm/video/{student_notebook_id}.mp4"
        try:
            video_path = await service.generate_video_overview(notebook_id, blob_path)
        except Exception:
            video_path = None
            logger.warning(
                "Échec isolé de la génération vidéo pour notebook_id=%s.", notebook_id, exc_info=True,
            )

        async with get_db_context() as db:
            repo = SQLAlchemyStudentNotebookRepository(db)
            if video_path is not None:
                await repo.update_video_overview_status(
                    uuid.UUID(student_notebook_id), VideoOverviewStatus.READY, path=video_path,
                )
                logger.info(
                    "Video Overview prête pour student_notebook_id=%s.", student_notebook_id,
                )
            else:
                # FAILED — jamais bloqué sur PENDING indéfiniment après un
                # échec réel, et désormais distinguable d'un "jamais
                # demandé" (chantier "régénération NotebookLM" — avant ce
                # chantier, repli sur NOT_REQUESTED, cf. docstring modèle
                # StudentNotebook) : l'étudiant peut redemander la
                # génération (READY/FAILED redéclenchent tous les deux
                # désormais, cf. RecommendationService.request_video_overview).
                await repo.update_video_overview_status(
                    uuid.UUID(student_notebook_id), VideoOverviewStatus.FAILED,
                )

    asyncio.run(_run())


@celery_app.task(queue=CeleryQueue.LLM, time_limit=750, soft_time_limit=720)
def regenerate_audio_overview_task(student_notebook_id: str, notebook_id: str) -> None:
    """
    Régénération Audio Overview À LA DEMANDE (chantier "régénération
    NotebookLM") — déclenchée exclusivement par POST .../regenerate-audio
    (cf. RecommendationService.regenerate_audio_overview pour le contrôle
    d'accès self + le dédoublonnage PENDING). Réutilise le MÊME blob_path
    que la génération initiale (notebooklm/audio/{student_notebook_id}.mp3)
    — StorageService.upload(overwrite=True) remplace proprement l'ancien
    fichier, jamais une nouvelle version côté stockage (cf. docstring
    modèle StudentNotebook). Best-effort : un échec passe le statut à
    FAILED, ne relance jamais d'exception (même discipline que le reste de
    ce module).
    """
    async def _run() -> None:
        await engine.dispose()
        await storage_service.close()
        service = NotebookLMService()
        blob_path = f"notebooklm/audio/{student_notebook_id}.mp3"
        try:
            audio_path = await service.generate_audio_overview(notebook_id, blob_path)
        except Exception:
            audio_path = None
            logger.warning(
                "Échec de la régénération audio pour notebook_id=%s.", notebook_id, exc_info=True,
            )

        async with get_db_context() as db:
            repo = SQLAlchemyStudentNotebookRepository(db)
            if audio_path is not None:
                await repo.update_audio_overview_path(uuid.UUID(student_notebook_id), audio_path)
                logger.info("Audio Overview régénéré pour student_notebook_id=%s.", student_notebook_id)
            else:
                await repo.update_audio_overview_status(uuid.UUID(student_notebook_id), GenerationStatus.FAILED)

    asyncio.run(_run())


@celery_app.task(queue=CeleryQueue.LLM, time_limit=750, soft_time_limit=720)
def regenerate_flashcards_task(student_notebook_id: str, notebook_id: str) -> None:
    """
    Régénération Flashcards À LA DEMANDE (chantier "régénération
    NotebookLM") — déclenchée exclusivement par POST .../regenerate-
    flashcards. L'ÉLIGIBILITÉ (au moins une weakness/identified_difficulty
    réelle sur le profil ACTUEL) est déjà vérifiée par le service AVANT
    dispatch (cf. RecommendationService.regenerate_flashcards,
    FlashcardsNotEligibleError) — cette tâche génère inconditionnellement
    une fois dispatchée, jamais de second contrôle métier ici (même
    principe "agent/service décide, tâche exécute" déjà appliqué ailleurs
    dans ce projet). Réutilise le même blob_path que la génération
    initiale (overwrite=True, cf. docstring modèle StudentNotebook).
    """
    async def _run() -> None:
        await engine.dispose()
        await storage_service.close()
        service = NotebookLMService()
        blob_path = f"notebooklm/flashcards/{student_notebook_id}.json"
        try:
            flashcards_path = await service.generate_flashcards(notebook_id, blob_path)
        except Exception:
            flashcards_path = None
            logger.warning(
                "Échec de la régénération flashcards pour notebook_id=%s.", notebook_id, exc_info=True,
            )

        async with get_db_context() as db:
            repo = SQLAlchemyStudentNotebookRepository(db)
            if flashcards_path is not None:
                await repo.update_flashcards_path(uuid.UUID(student_notebook_id), flashcards_path)
                logger.info("Flashcards régénérées pour student_notebook_id=%s.", student_notebook_id)
            else:
                await repo.update_flashcards_status(uuid.UUID(student_notebook_id), GenerationStatus.FAILED)

    asyncio.run(_run())
