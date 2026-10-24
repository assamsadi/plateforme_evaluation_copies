"""
Tests unitaires — notebooklm_tasks.py (§7, "Feedback Intelligent", Partie
2/2). Même pattern que test_submission_tasks.py : ces tâches appellent
`asyncio.run(_run())` en interne (conçu pour un worker Celery sans event
loop existant) — mocké ici via un side_effect qui exécute la coroutine sur
une NOUVELLE boucle dédiée (jamais la boucle déjà active de pytest-anyio,
qui lèverait "asyncio.run() cannot be called from a running event loop").

DB entièrement mockée ici (repositories mockés en classe) — la persistance
RÉELLE est déjà couverte par les tests dédiés des repositories
(test_student_notebook_repository.py, test_recommended_exercise_repository.py) ;
ce fichier vérifie l'ORCHESTRATION (quel format est tenté, isolation des
échecs, contenu du payload Kafka), pas la couche SQL.

Couvre :
  1. Succès complet — audio + flashcards générés (weaknesses réelles),
     rattachement des recommandations, événement Kafka avec les deux flags.
  2. Flashcards jamais générées sans weakness/identified_difficulty réelle.
  3. Isolation — échec audio n'empêche pas la tentative des flashcards.
  4. Échec de la création du notebook -> rien d'autre n'est tenté.
  5. generate_video_overview_task : succès -> READY + path ; échec -> FAILED
     (jamais bloqué sur PENDING).
  6. regenerate_audio_overview_task / regenerate_flashcards_task (chantier
     "régénération NotebookLM") : mêmes contrats succès/échec que la vidéo,
     même blob_path que la génération initiale (overwrite).
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.notebooklm_service import NotebookHandle
from app.tasks.notebooklm_tasks import (
    generate_notebook_for_recommendations_task,
    generate_video_overview_task,
)


def _run_asyncio_run_side_effect(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_db_context(mock_db_ctx):
    mock_db = MagicMock()
    mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_db


def _competency_line_with_weakness():
    return {
        "competency": "data_and_planning", "mastery_level": "20.00", "confidence_level": "0.40",
        "is_persistent_weakness": True, "identified_difficulties": ["Confond les bornes."],
        "weaknesses": ["1.1 (Analyse)"], "strengths": [],
    }


def _competency_line_without_weakness():
    return {
        "competency": "data_and_planning", "mastery_level": "95.00", "confidence_level": "0.90",
        "is_persistent_weakness": False, "identified_difficulties": [], "weaknesses": [], "strengths": ["Tout maîtrisé"],
    }


def _base_kwargs(**overrides):
    payload = {
        "student_id": str(uuid.uuid4()), "module_id": str(uuid.uuid4()), "submission_id": None,
        "competency_lines_data": [_competency_line_with_weakness()], "recommendations_data": [],
    }
    payload.update(overrides)
    return payload


@patch("app.tasks.notebooklm_tasks.EventPublisherService")
@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyRecommendedExerciseRepository")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_full_success_generates_audio_and_flashcards(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_rec_repo_cls,
    mock_service_cls, mock_events_cls,
):
    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect

    notebook_record = MagicMock(id=uuid.uuid4())
    mock_notebook_repo_cls.return_value.create = AsyncMock(return_value=notebook_record)
    mock_notebook_repo_cls.return_value.update_audio_overview_path = AsyncMock()
    mock_notebook_repo_cls.return_value.update_flashcards_path = AsyncMock()
    mock_rec_repo_cls.return_value.link_to_notebook = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.create_notebook_for_feedback = AsyncMock(
        return_value=NotebookHandle(notebook_id="nb-1", title="t")
    )
    mock_service.generate_audio_overview = AsyncMock(return_value="notebooklm/audio/x.mp3")
    mock_service.generate_flashcards = AsyncMock(return_value="notebooklm/flashcards/x.json")

    mock_events = mock_events_cls.return_value
    mock_events.publish_notebooklm_enrichment_completed = AsyncMock(return_value="evt-1")

    generate_notebook_for_recommendations_task(**_base_kwargs())

    mock_rec_repo_cls.return_value.link_to_notebook.assert_awaited_once()
    mock_notebook_repo_cls.return_value.update_audio_overview_path.assert_awaited_once_with(
        notebook_record.id, "notebooklm/audio/x.mp3",
    )
    mock_notebook_repo_cls.return_value.update_flashcards_path.assert_awaited_once_with(
        notebook_record.id, "notebooklm/flashcards/x.json",
    )
    mock_events.publish_notebooklm_enrichment_completed.assert_awaited_once()
    payload = mock_events.publish_notebooklm_enrichment_completed.await_args.args[0]
    assert payload.audio_generated is True
    assert payload.flashcards_generated is True
    # Vidéo jamais automatique — même dans le chemin de succès complet,
    # generate_video_overview n'est ni défini ni appelé sur ce mock
    # (aucune méthode de ce nom n'existe sur NotebookLMService en dehors
    # de generate_video_overview, réservée à generate_video_overview_task,
    # jamais appelée par cette tâche — cf. test dédié ci-dessous).
    assert not hasattr(mock_service, "generate_video_overview") or not mock_service.generate_video_overview.called


@patch("app.tasks.notebooklm_tasks.EventPublisherService")
@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyRecommendedExerciseRepository")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_feedback_text_passed_through_to_service(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_rec_repo_cls,
    mock_service_cls, mock_events_cls,
):
    """
    Chantier Feedback_Agent (§7) — feedback_text reçu par la tâche (déplacée
    depuis recommendation_node.py vers feedback_node.py, cf. docstring
    module) doit être transmis tel quel à NotebookLMService.create_notebook_
    for_feedback, jamais oublié/tronqué à cette frontière Celery.
    """
    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect

    notebook_record = MagicMock(id=uuid.uuid4())
    mock_notebook_repo_cls.return_value.create = AsyncMock(return_value=notebook_record)
    mock_rec_repo_cls.return_value.link_to_notebook = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.create_notebook_for_feedback = AsyncMock(
        return_value=NotebookHandle(notebook_id="nb-1", title="t")
    )
    mock_service.generate_audio_overview = AsyncMock(return_value=None)

    mock_events = mock_events_cls.return_value
    mock_events.publish_notebooklm_enrichment_completed = AsyncMock(return_value="evt-1")

    socratic_text = "Relis ta boucle : à quel moment vérifies-tu la condition d'arrêt ?"
    generate_notebook_for_recommendations_task(
        **_base_kwargs(feedback_text=socratic_text, competency_lines_data=[_competency_line_without_weakness()]),
    )

    mock_service.create_notebook_for_feedback.assert_awaited_once()
    call_kwargs = mock_service.create_notebook_for_feedback.await_args.kwargs
    assert call_kwargs["feedback_text"] == socratic_text


@patch("app.tasks.notebooklm_tasks.EventPublisherService")
@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyRecommendedExerciseRepository")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_video_overview_never_generated_automatically(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_rec_repo_cls,
    mock_service_cls, mock_events_cls,
):
    """
    Contrainte non négociable du ticket — la tâche déclenchée après chaque
    génération de recommandations (Partie 1/2 + audio/flashcards) ne doit
    JAMAIS déclencher generate_video_overview_task, quel que soit le succès
    ou l'échec des autres formats. Seul l'endpoint dédié le fait.
    """
    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect

    notebook_record = MagicMock(id=uuid.uuid4())
    mock_notebook_repo_cls.return_value.create = AsyncMock(return_value=notebook_record)
    mock_notebook_repo_cls.return_value.update_audio_overview_path = AsyncMock()
    mock_notebook_repo_cls.return_value.update_flashcards_path = AsyncMock()
    mock_rec_repo_cls.return_value.link_to_notebook = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.create_notebook_for_feedback = AsyncMock(
        return_value=NotebookHandle(notebook_id="nb-1", title="t")
    )
    mock_service.generate_audio_overview = AsyncMock(return_value="notebooklm/audio/x.mp3")
    mock_service.generate_flashcards = AsyncMock(return_value="notebooklm/flashcards/x.json")
    mock_service.generate_video_overview = AsyncMock()  # présent sur le vrai service, jamais appelé ici

    mock_events_cls.return_value.publish_notebooklm_enrichment_completed = AsyncMock(return_value="evt-1")

    with patch("app.tasks.notebooklm_tasks.generate_video_overview_task") as mock_video_task:
        generate_notebook_for_recommendations_task(**_base_kwargs())

        mock_video_task.delay.assert_not_called()
    mock_service.generate_video_overview.assert_not_awaited()


@patch("app.tasks.notebooklm_tasks.EventPublisherService")
@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyRecommendedExerciseRepository")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_flashcards_never_generated_without_real_weakness_data(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_rec_repo_cls,
    mock_service_cls, mock_events_cls,
):
    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect

    notebook_record = MagicMock(id=uuid.uuid4())
    mock_notebook_repo_cls.return_value.create = AsyncMock(return_value=notebook_record)
    mock_notebook_repo_cls.return_value.update_audio_overview_path = AsyncMock()
    mock_rec_repo_cls.return_value.link_to_notebook = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.create_notebook_for_feedback = AsyncMock(
        return_value=NotebookHandle(notebook_id="nb-2", title="t")
    )
    mock_service.generate_audio_overview = AsyncMock(return_value="notebooklm/audio/y.mp3")
    mock_service.generate_flashcards = AsyncMock(return_value="notebooklm/flashcards/y.json")

    mock_events = mock_events_cls.return_value
    mock_events.publish_notebooklm_enrichment_completed = AsyncMock(return_value="evt-2")

    generate_notebook_for_recommendations_task(
        **_base_kwargs(competency_lines_data=[_competency_line_without_weakness()])
    )

    mock_service.generate_flashcards.assert_not_awaited()
    payload = mock_events.publish_notebooklm_enrichment_completed.await_args.args[0]
    assert payload.flashcards_generated is False
    assert payload.audio_generated is True


@patch("app.tasks.notebooklm_tasks.EventPublisherService")
@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyRecommendedExerciseRepository")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_audio_failure_does_not_prevent_flashcards_attempt(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_rec_repo_cls,
    mock_service_cls, mock_events_cls,
):
    """Isolation — échec audio (exception réelle) n'empêche PAS la tentative des flashcards."""
    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect

    notebook_record = MagicMock(id=uuid.uuid4())
    mock_notebook_repo_cls.return_value.create = AsyncMock(return_value=notebook_record)
    mock_notebook_repo_cls.return_value.update_flashcards_path = AsyncMock()
    mock_rec_repo_cls.return_value.link_to_notebook = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.create_notebook_for_feedback = AsyncMock(
        return_value=NotebookHandle(notebook_id="nb-3", title="t")
    )
    mock_service.generate_audio_overview = AsyncMock(side_effect=RuntimeError("panne audio simulée"))
    mock_service.generate_flashcards = AsyncMock(return_value="notebooklm/flashcards/z.json")

    mock_events = mock_events_cls.return_value
    mock_events.publish_notebooklm_enrichment_completed = AsyncMock(return_value="evt-3")

    generate_notebook_for_recommendations_task(**_base_kwargs())

    mock_service.generate_flashcards.assert_awaited_once()
    payload = mock_events.publish_notebooklm_enrichment_completed.await_args.args[0]
    assert payload.audio_generated is False
    assert payload.flashcards_generated is True


@patch("app.tasks.notebooklm_tasks.EventPublisherService")
@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyRecommendedExerciseRepository")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_notebook_creation_failure_skips_everything_else(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_rec_repo_cls,
    mock_service_cls, mock_events_cls,
):
    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect

    mock_service = mock_service_cls.return_value
    mock_service.create_notebook_for_feedback = AsyncMock(return_value=None)
    mock_service.generate_audio_overview = AsyncMock()
    mock_service.generate_flashcards = AsyncMock()

    mock_events = mock_events_cls.return_value
    mock_events.publish_notebooklm_enrichment_completed = AsyncMock()

    generate_notebook_for_recommendations_task(**_base_kwargs())

    mock_notebook_repo_cls.return_value.create.assert_not_called()
    mock_rec_repo_cls.return_value.link_to_notebook.assert_not_called()
    mock_service.generate_audio_overview.assert_not_awaited()
    mock_service.generate_flashcards.assert_not_awaited()
    mock_events.publish_notebooklm_enrichment_completed.assert_not_awaited()


@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_generate_video_overview_task_success(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_service_cls,
):
    from app.domain.models.assessment.student_notebook import VideoOverviewStatus

    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect
    mock_notebook_repo_cls.return_value.update_video_overview_status = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.generate_video_overview = AsyncMock(return_value="notebooklm/video/x.mp4")

    notebook_record_id = str(uuid.uuid4())
    generate_video_overview_task(student_notebook_id=notebook_record_id, notebook_id="nb-video")

    mock_notebook_repo_cls.return_value.update_video_overview_status.assert_awaited_once_with(
        uuid.UUID(notebook_record_id), VideoOverviewStatus.READY, path="notebooklm/video/x.mp4",
    )


@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_generate_video_overview_task_failure_sets_failed(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_service_cls,
):
    """
    Chantier "régénération NotebookLM" — un échec réel passe désormais à
    FAILED (distinguable d'un "jamais demandé"), plus un repli silencieux
    sur NOT_REQUESTED (cf. docstring modèle StudentNotebook) : permet à
    request_video_overview de redéclencher une régénération réelle.
    """
    from app.domain.models.assessment.student_notebook import VideoOverviewStatus

    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect
    mock_notebook_repo_cls.return_value.update_video_overview_status = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.generate_video_overview = AsyncMock(return_value=None)

    notebook_record_id = str(uuid.uuid4())
    generate_video_overview_task(student_notebook_id=notebook_record_id, notebook_id="nb-video-2")

    mock_notebook_repo_cls.return_value.update_video_overview_status.assert_awaited_once_with(
        uuid.UUID(notebook_record_id), VideoOverviewStatus.FAILED,
    )


@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_regenerate_audio_overview_task_success(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_service_cls,
):
    from app.tasks.notebooklm_tasks import regenerate_audio_overview_task

    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect
    mock_notebook_repo_cls.return_value.update_audio_overview_path = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.generate_audio_overview = AsyncMock(return_value="notebooklm/audio/regen.mp3")

    notebook_record_id = str(uuid.uuid4())
    regenerate_audio_overview_task(student_notebook_id=notebook_record_id, notebook_id="nb-audio")

    mock_service.generate_audio_overview.assert_awaited_once_with(
        "nb-audio", f"notebooklm/audio/{notebook_record_id}.mp3",
    )
    mock_notebook_repo_cls.return_value.update_audio_overview_path.assert_awaited_once_with(
        uuid.UUID(notebook_record_id), "notebooklm/audio/regen.mp3",
    )


@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_regenerate_audio_overview_task_failure_sets_failed(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_service_cls,
):
    from app.domain.models.assessment.student_notebook import GenerationStatus
    from app.tasks.notebooklm_tasks import regenerate_audio_overview_task

    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect
    mock_notebook_repo_cls.return_value.update_audio_overview_status = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.generate_audio_overview = AsyncMock(side_effect=RuntimeError("panne simulée"))

    notebook_record_id = str(uuid.uuid4())
    regenerate_audio_overview_task(student_notebook_id=notebook_record_id, notebook_id="nb-audio-2")

    mock_notebook_repo_cls.return_value.update_audio_overview_status.assert_awaited_once_with(
        uuid.UUID(notebook_record_id), GenerationStatus.FAILED,
    )


@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_regenerate_flashcards_task_success(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_service_cls,
):
    from app.tasks.notebooklm_tasks import regenerate_flashcards_task

    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect
    mock_notebook_repo_cls.return_value.update_flashcards_path = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.generate_flashcards = AsyncMock(return_value="notebooklm/flashcards/regen.json")

    notebook_record_id = str(uuid.uuid4())
    regenerate_flashcards_task(student_notebook_id=notebook_record_id, notebook_id="nb-flash")

    mock_notebook_repo_cls.return_value.update_flashcards_path.assert_awaited_once_with(
        uuid.UUID(notebook_record_id), "notebooklm/flashcards/regen.json",
    )


@patch("app.tasks.notebooklm_tasks.NotebookLMService")
@patch("app.tasks.notebooklm_tasks.SQLAlchemyStudentNotebookRepository")
@patch("app.tasks.notebooklm_tasks.asyncio.run")
@patch("app.tasks.notebooklm_tasks.get_db_context")
def test_regenerate_flashcards_task_failure_sets_failed(
    mock_db_ctx, mock_asyncio_run, mock_notebook_repo_cls, mock_service_cls,
):
    from app.domain.models.assessment.student_notebook import GenerationStatus
    from app.tasks.notebooklm_tasks import regenerate_flashcards_task

    _mock_db_context(mock_db_ctx)
    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect
    mock_notebook_repo_cls.return_value.update_flashcards_status = AsyncMock()

    mock_service = mock_service_cls.return_value
    mock_service.generate_flashcards = AsyncMock(return_value=None)

    notebook_record_id = str(uuid.uuid4())
    regenerate_flashcards_task(student_notebook_id=notebook_record_id, notebook_id="nb-flash-2")

    mock_notebook_repo_cls.return_value.update_flashcards_status.assert_awaited_once_with(
        uuid.UUID(notebook_record_id), GenerationStatus.FAILED,
    )
