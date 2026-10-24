import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    ExerciseNotFoundError,
    ForbiddenError,
    InvalidRelevanceScoreError,
    SubmissionNotFoundError,
)
from app.domain.models.assessment.recommended_exercise import (
    RecommendationCategory,
    RecommendationStatus,
    RecommendedExercise,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.services.recommendation_service import RecommendationService

DAP = C2PCTSkillCode.DATA_AND_PLANNING


def _make_recommendation(
    rec_id: uuid.UUID, student_id: uuid.UUID, module_id: uuid.UUID,
    submission_id: uuid.UUID, exercise_id: uuid.UUID,
) -> RecommendedExercise:
    now = datetime.now(timezone.utc)
    return RecommendedExercise(
        id=rec_id,
        student_id=student_id,
        module_id=module_id,
        competency_code=DAP,
        category=RecommendationCategory.REMEDIATION,
        status=RecommendationStatus.ACTIVE,
        submission_id=submission_id,
        exercise_id=exercise_id,
        reason="Revoir les bases",
        relevance_score=Decimal("0.85"),
        created_at=now,
        updated_at=now,
    )


def _make_exercise(exercise_id: uuid.UUID, module_id: uuid.UUID | None = None, difficulty_level=None) -> MagicMock:
    e = MagicMock()
    e.id = exercise_id
    e.title = "Exercice de remédiation"
    e.module_id = module_id or uuid.uuid4()
    # Explicite — un MagicMock() non configuré est truthy par défaut et
    # .value renverrait un autre MagicMock, jamais une vraie str (casserait
    # la validation Pydantic de RecommendedExerciseRead.difficulty_level).
    e.difficulty_level = difficulty_level
    return e


def _make_submission(submission_id: uuid.UUID, student_id: uuid.UUID | None = None) -> MagicMock:
    s = MagicMock()
    s.id = submission_id
    s.student_id = student_id or uuid.uuid4()
    return s


def _make_service(
    rec_repo=None, exercise_repo=None, submission_repo=None, evaluation_repo=None, student_notebook_repo=None,
    profile_repo=None, competency_assessment_service=None,
) -> RecommendationService:
    if profile_repo is None:
        profile_repo = AsyncMock()
        # Défaut "aucun profil trouvé" — un AsyncMock() non configuré
        # renverrait un MagicMock truthy pour get_profile(...), et
        # profile.is_persistent_weakness casserait alors la validation
        # Pydantic de RecommendedExerciseRead (bool attendu).
        profile_repo.get_profile.return_value = None
    return RecommendationService(
        recommendation_repo=rec_repo or AsyncMock(),
        exercise_repo=exercise_repo or AsyncMock(),
        submission_repo=submission_repo or AsyncMock(),
        evaluation_repo=evaluation_repo or AsyncMock(),
        student_notebook_repo=student_notebook_repo or AsyncMock(),
        profile_repo=profile_repo,
        competency_assessment_service=competency_assessment_service or AsyncMock(),
    )


@pytest.mark.anyio
async def test_create_recommendation_success():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id, professor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)

    rec_repo = AsyncMock()
    rec_repo.create.return_value = rec

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid, module_id)
    exercise_repo.exists_professor_exercise_in_module.return_value = True

    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = _make_submission(sid, student_id)

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo, submission_repo=submission_repo)
    result = await service.create_recommendation(sid, eid, DAP, "Revoir les bases", Decimal("0.85"), professor_id)

    assert result.id == rid
    assert result.exercise_id == eid
    assert result.exercise_title == "Exercice de remédiation"
    assert result.relevance_score == Decimal("0.85")
    exercise_repo.exists_professor_exercise_in_module.assert_awaited_once_with(
        professor_id=professor_id, module_id=module_id,
    )
    rec_repo.create.assert_awaited_once_with(
        student_id=student_id,
        module_id=module_id,
        competency_code=DAP,
        category=RecommendationCategory.REMEDIATION,
        submission_id=sid,
        exercise_id=eid,
        reason="Revoir les bases",
        relevance_score=Decimal("0.85"),
    )


@pytest.mark.anyio
async def test_create_recommendation_submission_not_found():
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = None
    service = _make_service(submission_repo=submission_repo)

    with pytest.raises(SubmissionNotFoundError):
        await service.create_recommendation(
            uuid.uuid4(), uuid.uuid4(), DAP, "Raison", Decimal("0.5"), uuid.uuid4(),
        )


@pytest.mark.anyio
async def test_create_recommendation_exercise_not_found():
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = _make_submission(uuid.uuid4())
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = None
    service = _make_service(submission_repo=submission_repo, exercise_repo=exercise_repo)

    with pytest.raises(ExerciseNotFoundError):
        await service.create_recommendation(
            uuid.uuid4(), uuid.uuid4(), DAP, "Raison", Decimal("0.5"), uuid.uuid4(),
        )


@pytest.mark.anyio
async def test_create_recommendation_professor_without_exercise_in_module_forbidden():
    """Fermeture de la faille d'accès (Phase 3) — coeur du correctif."""
    sid, eid, professor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = _make_submission(sid)
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid)
    exercise_repo.exists_professor_exercise_in_module.return_value = False

    service = _make_service(submission_repo=submission_repo, exercise_repo=exercise_repo)

    with pytest.raises(ForbiddenError):
        await service.create_recommendation(sid, eid, DAP, "Raison", Decimal("0.5"), professor_id)


@pytest.mark.anyio
async def test_create_recommendation_score_too_high_raises():
    service = _make_service()
    with pytest.raises(InvalidRelevanceScoreError):
        await service.create_recommendation(
            uuid.uuid4(), uuid.uuid4(), DAP, "Raison", Decimal("1.1"), uuid.uuid4(),
        )


@pytest.mark.anyio
async def test_create_recommendation_score_negative_raises():
    service = _make_service()
    with pytest.raises(InvalidRelevanceScoreError):
        await service.create_recommendation(
            uuid.uuid4(), uuid.uuid4(), DAP, "Raison", Decimal("-0.1"), uuid.uuid4(),
        )


@pytest.mark.anyio
async def test_create_recommendation_score_boundary_zero_ok():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id, professor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    rec.relevance_score = Decimal("0")

    rec_repo = AsyncMock()
    rec_repo.create.return_value = rec
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid, module_id)
    exercise_repo.exists_professor_exercise_in_module.return_value = True
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = _make_submission(sid, student_id)

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo, submission_repo=submission_repo)
    result = await service.create_recommendation(sid, eid, DAP, "Raison", Decimal("0"), professor_id)

    assert result.relevance_score == Decimal("0")


@pytest.mark.anyio
async def test_create_recommendation_score_boundary_one_ok():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id, professor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    rec.relevance_score = Decimal("1")

    rec_repo = AsyncMock()
    rec_repo.create.return_value = rec
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid, module_id)
    exercise_repo.exists_professor_exercise_in_module.return_value = True
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = _make_submission(sid, student_id)

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo, submission_repo=submission_repo)
    result = await service.create_recommendation(sid, eid, DAP, "Raison", Decimal("1"), professor_id)

    assert result.relevance_score == Decimal("1")


@pytest.mark.anyio
async def test_get_student_dashboard_success():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)

    rec_repo = AsyncMock()
    rec_repo.list_active_by_student.return_value = [rec]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid)

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo)
    result = await service.get_student_dashboard(student_id)

    assert len(result) == 1
    assert result[0].exercise_title == "Exercice de remédiation"
    rec_repo.list_active_by_student.assert_awaited_once_with(student_id)


@pytest.mark.anyio
async def test_get_student_dashboard_notebooklm_fields_default_when_no_notebook_linked():
    """
    Câblage NotebookLM (§7, Partie 2/2) — student_notebook_id=None (jamais
    rattaché, ex. intégration désactivée ou échec best-effort) : toutes les
    nouvelles références restent None/not_requested, jamais une exception,
    jamais une valeur inventée.
    """
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    assert rec.student_notebook_id is None  # précondition du test

    rec_repo = AsyncMock()
    rec_repo.list_active_by_student.return_value = [rec]
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid)
    notebook_repo = AsyncMock()

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo, student_notebook_repo=notebook_repo)
    result = await service.get_student_dashboard(student_id)

    assert result[0].audio_overview_url is None
    assert result[0].flashcards_url is None
    assert result[0].video_overview_url is None
    assert result[0].notebook_chat_url is None
    assert result[0].video_overview_status == "not_requested"
    notebook_repo.get_by_id.assert_not_awaited()  # jamais interrogé si rien n'est rattaché


@pytest.mark.anyio
async def test_get_student_dashboard_includes_difficulty_level():
    """Clôture — difficulty_level aplati depuis Exercise, champ structuré exploitable (pas seulement dans `reason`)."""
    from app.domain.models.assessment.exercise import ExerciseDifficulty

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)

    rec_repo = AsyncMock()
    rec_repo.list_active_by_student.return_value = [rec]
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid, difficulty_level=ExerciseDifficulty.INTERMEDIAIRE)

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo)
    result = await service.get_student_dashboard(student_id)

    assert result[0].difficulty_level == "intermediaire"


@pytest.mark.anyio
async def test_get_student_dashboard_difficulty_level_none_when_exercise_never_had_one():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)

    rec_repo = AsyncMock()
    rec_repo.list_active_by_student.return_value = [rec]
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid)  # difficulty_level=None par défaut

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo)
    result = await service.get_student_dashboard(student_id)

    assert result[0].difficulty_level is None


@pytest.mark.anyio
async def test_get_student_dashboard_exercise_unknown():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)

    rec_repo = AsyncMock()
    rec_repo.list_active_by_student.return_value = [rec]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = None

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo)
    result = await service.get_student_dashboard(student_id)

    assert result[0].exercise_title == "Unknown"


@pytest.mark.anyio
async def test_get_student_dashboard_empty():
    sid = uuid.uuid4()
    rec_repo = AsyncMock()
    rec_repo.list_active_by_student.return_value = []

    service = _make_service(rec_repo=rec_repo)
    result = await service.get_student_dashboard(sid)

    assert result == []


# ---------------------------------------------------------------------------
# Traçabilité professeur (clôture du chantier Recommendation_Agent) —
# get_student_dashboard_for_module() / get_student_dashboard_as_professor(),
# même couple self/professeur que CompetencyAssessmentService.get_report/
# get_report_as_professor.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_student_dashboard_for_module_success():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)

    rec_repo = AsyncMock()
    rec_repo.list_active_by_student_and_module.return_value = [rec]
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid)

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo)
    result = await service.get_student_dashboard_for_module(student_id, module_id)

    assert len(result) == 1
    assert result[0].id == rid
    rec_repo.list_active_by_student_and_module.assert_awaited_once_with(
        student_id=student_id, module_id=module_id,
    )


@pytest.mark.anyio
async def test_get_student_dashboard_as_professor_success():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id, professor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)

    rec_repo = AsyncMock()
    rec_repo.list_active_by_student_and_module.return_value = [rec]
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = _make_exercise(eid)
    exercise_repo.exists_professor_exercise_in_module.return_value = True

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo)
    result = await service.get_student_dashboard_as_professor(professor_id, student_id, module_id)

    assert len(result) == 1
    exercise_repo.exists_professor_exercise_in_module.assert_awaited_once_with(
        professor_id=professor_id, module_id=module_id,
    )


@pytest.mark.anyio
async def test_get_student_dashboard_as_professor_without_exercise_in_module_forbidden():
    student_id, module_id, professor_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    exercise_repo = AsyncMock()
    exercise_repo.exists_professor_exercise_in_module.return_value = False
    rec_repo = AsyncMock()

    service = _make_service(rec_repo=rec_repo, exercise_repo=exercise_repo)

    with pytest.raises(ForbiddenError):
        await service.get_student_dashboard_as_professor(professor_id, student_id, module_id)
    rec_repo.list_active_by_student_and_module.assert_not_awaited()


# ---------------------------------------------------------------------------
# Câblage NotebookLM (§7, Partie 2/2) — request_video_overview/ask_notebook_
# chat, réservés à l'étudiant propriétaire de la recommandation, jamais un
# professeur (cf. contrainte explicite du ticket).
# ---------------------------------------------------------------------------

def _make_notebook(
    notebook_id_str="nb-1", video_status=None, video_path=None,
    audio_status=None, audio_path=None, flashcards_status=None, flashcards_path=None,
):
    from app.domain.models.assessment.student_notebook import (
        GenerationStatus,
        StudentNotebook,
        VideoOverviewStatus,
    )

    nb = MagicMock(spec=StudentNotebook)
    nb.id = uuid.uuid4()
    nb.notebook_id = notebook_id_str
    nb.video_overview_status = video_status or VideoOverviewStatus.NOT_REQUESTED
    nb.video_overview_path = video_path
    nb.audio_overview_status = audio_status or GenerationStatus.NOT_REQUESTED
    nb.audio_overview_path = audio_path
    nb.flashcards_status = flashcards_status or GenerationStatus.NOT_REQUESTED
    nb.flashcards_path = flashcards_path
    return nb


@pytest.mark.anyio
async def test_request_video_overview_recommendation_not_found_raises():
    from app.core.exceptions import RecommendationNotFoundError

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = None
    service = _make_service(rec_repo=rec_repo)

    with pytest.raises(RecommendationNotFoundError):
        await service.request_video_overview(uuid.uuid4(), uuid.uuid4())


@pytest.mark.anyio
async def test_request_video_overview_forbidden_for_another_student():
    """Réservé à l'étudiant propriétaire — jamais un tiers, y compris un autre étudiant."""
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    module_id = uuid.uuid4()
    rec = _make_recommendation(rid, uuid.uuid4(), module_id, sid, eid)  # owner = un AUTRE student_id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    service = _make_service(rec_repo=rec_repo)

    with pytest.raises(ForbiddenError):
        await service.request_video_overview(uuid.uuid4(), rid)  # requesting_student_id != rec.student_id


@pytest.mark.anyio
async def test_request_video_overview_no_notebook_raises_not_found():
    from app.core.exceptions import NotebookNotFoundError

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    rec.student_notebook_id = None  # jamais rattaché

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    service = _make_service(rec_repo=rec_repo)

    with pytest.raises(NotebookNotFoundError):
        await service.request_video_overview(student_id, rid)


@pytest.mark.anyio
async def test_request_video_overview_first_call_dispatches_task_and_sets_pending():
    from app.domain.models.assessment.student_notebook import VideoOverviewStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(video_status=VideoOverviewStatus.NOT_REQUESTED)
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook
    service = _make_service(rec_repo=rec_repo, student_notebook_repo=notebook_repo)

    with patch("app.tasks.notebooklm_tasks.generate_video_overview_task.delay") as mock_delay:
        result = await service.request_video_overview(student_id, rid)

    notebook_repo.update_video_overview_status.assert_awaited_once_with(notebook.id, VideoOverviewStatus.PENDING)
    mock_delay.assert_called_once_with(student_notebook_id=str(notebook.id), notebook_id=notebook.notebook_id)
    assert result["video_overview_status"] == "pending"
    assert result["video_overview_url"] is None


@pytest.mark.anyio
async def test_request_video_overview_already_pending_never_redispatches():
    """Déduplication — un second appel pendant que la génération est déjà en cours ne redéclenche rien."""
    from app.domain.models.assessment.student_notebook import VideoOverviewStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(video_status=VideoOverviewStatus.PENDING)
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook
    service = _make_service(rec_repo=rec_repo, student_notebook_repo=notebook_repo)

    with patch("app.tasks.notebooklm_tasks.generate_video_overview_task.delay") as mock_delay:
        result = await service.request_video_overview(student_id, rid)

    mock_delay.assert_not_called()
    notebook_repo.update_video_overview_status.assert_not_awaited()
    assert result["video_overview_status"] == "pending"


@pytest.mark.anyio
async def test_request_video_overview_already_ready_redispatches_regeneration():
    """
    Chantier "régénération NotebookLM" — comportement changé : READY
    redéclenche désormais une vraie régénération (avant, READY renvoyait
    simplement l'état existant sans jamais pouvoir régénérer).
    """
    from app.domain.models.assessment.student_notebook import VideoOverviewStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(video_status=VideoOverviewStatus.READY, video_path="notebooklm/video/x.mp4")
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook
    service = _make_service(rec_repo=rec_repo, student_notebook_repo=notebook_repo)

    with patch("app.tasks.notebooklm_tasks.generate_video_overview_task.delay") as mock_delay:
        result = await service.request_video_overview(student_id, rid)

    mock_delay.assert_called_once_with(student_notebook_id=str(notebook.id), notebook_id=notebook.notebook_id)
    notebook_repo.update_video_overview_status.assert_awaited_once_with(notebook.id, VideoOverviewStatus.PENDING)
    assert result["video_overview_status"] == "pending"
    assert result["video_overview_url"] is None


@pytest.mark.anyio
async def test_request_video_overview_failed_redispatches_regeneration():
    from app.domain.models.assessment.student_notebook import VideoOverviewStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(video_status=VideoOverviewStatus.FAILED)
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook
    service = _make_service(rec_repo=rec_repo, student_notebook_repo=notebook_repo)

    with patch("app.tasks.notebooklm_tasks.generate_video_overview_task.delay") as mock_delay:
        result = await service.request_video_overview(student_id, rid)

    mock_delay.assert_called_once()
    assert result["video_overview_status"] == "pending"


# ---------------------------------------------------------------------------
# Régénération audio/flashcards (chantier "régénération NotebookLM") — même
# contrat de dédoublonnage (PENDING uniquement) que request_video_overview
# ci-dessus, plus une revérification d'éligibilité pour les flashcards.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_regenerate_audio_overview_first_call_dispatches_task_and_sets_pending():
    from app.domain.models.assessment.student_notebook import GenerationStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(audio_status=GenerationStatus.READY, audio_path="notebooklm/audio/old.mp3")
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook
    service = _make_service(rec_repo=rec_repo, student_notebook_repo=notebook_repo)

    with patch("app.tasks.notebooklm_tasks.regenerate_audio_overview_task.delay") as mock_delay:
        result = await service.regenerate_audio_overview(student_id, rid)

    notebook_repo.update_audio_overview_status.assert_awaited_once_with(notebook.id, GenerationStatus.PENDING)
    mock_delay.assert_called_once_with(student_notebook_id=str(notebook.id), notebook_id=notebook.notebook_id)
    assert result["audio_overview_status"] == "pending"
    assert result["audio_overview_url"] is None


@pytest.mark.anyio
async def test_regenerate_audio_overview_already_pending_never_redispatches():
    from app.domain.models.assessment.student_notebook import GenerationStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(audio_status=GenerationStatus.PENDING)
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook
    service = _make_service(rec_repo=rec_repo, student_notebook_repo=notebook_repo)

    with patch("app.tasks.notebooklm_tasks.regenerate_audio_overview_task.delay") as mock_delay:
        result = await service.regenerate_audio_overview(student_id, rid)

    mock_delay.assert_not_called()
    notebook_repo.update_audio_overview_status.assert_not_awaited()
    assert result["audio_overview_status"] == "pending"


@pytest.mark.anyio
async def test_regenerate_audio_overview_no_notebook_raises_not_found():
    from app.core.exceptions import NotebookNotFoundError

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    rec.student_notebook_id = None

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    service = _make_service(rec_repo=rec_repo)

    with pytest.raises(NotebookNotFoundError):
        await service.regenerate_audio_overview(student_id, rid)


@pytest.mark.anyio
async def test_regenerate_flashcards_no_real_weakness_raises_not_eligible():
    from app.core.exceptions import FlashcardsNotEligibleError
    from app.domain.models.assessment.student_notebook import GenerationStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(flashcards_status=GenerationStatus.NOT_REQUESTED)
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook

    line_without_weakness = MagicMock(weaknesses=[], identified_difficulties=[])
    competency_service = AsyncMock()
    competency_service.get_report.return_value = MagicMock(lines=[line_without_weakness])

    service = _make_service(
        rec_repo=rec_repo, student_notebook_repo=notebook_repo,
        competency_assessment_service=competency_service,
    )

    with patch("app.tasks.notebooklm_tasks.regenerate_flashcards_task.delay") as mock_delay:
        with pytest.raises(FlashcardsNotEligibleError):
            await service.regenerate_flashcards(student_id, rid)

    mock_delay.assert_not_called()


@pytest.mark.anyio
async def test_regenerate_flashcards_with_real_weakness_dispatches_task():
    from app.domain.models.assessment.student_notebook import GenerationStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(flashcards_status=GenerationStatus.FAILED)
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook

    line_with_weakness = MagicMock(weaknesses=["1.1 (Analyse)"], identified_difficulties=[])
    competency_service = AsyncMock()
    competency_service.get_report.return_value = MagicMock(lines=[line_with_weakness])

    service = _make_service(
        rec_repo=rec_repo, student_notebook_repo=notebook_repo,
        competency_assessment_service=competency_service,
    )

    with patch("app.tasks.notebooklm_tasks.regenerate_flashcards_task.delay") as mock_delay:
        result = await service.regenerate_flashcards(student_id, rid)

    notebook_repo.update_flashcards_status.assert_awaited_once_with(notebook.id, GenerationStatus.PENDING)
    mock_delay.assert_called_once_with(student_notebook_id=str(notebook.id), notebook_id=notebook.notebook_id)
    assert result["flashcards_status"] == "pending"


@pytest.mark.anyio
async def test_regenerate_flashcards_already_pending_never_rechecks_eligibility():
    """Dédoublonnage PENDING court-circuite AVANT la revérification d'éligibilité — jamais un appel get_report inutile."""
    from app.domain.models.assessment.student_notebook import GenerationStatus

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook(flashcards_status=GenerationStatus.PENDING)
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook
    competency_service = AsyncMock()

    service = _make_service(
        rec_repo=rec_repo, student_notebook_repo=notebook_repo,
        competency_assessment_service=competency_service,
    )

    with patch("app.tasks.notebooklm_tasks.regenerate_flashcards_task.delay") as mock_delay:
        result = await service.regenerate_flashcards(student_id, rid)

    competency_service.get_report.assert_not_awaited()
    mock_delay.assert_not_called()
    assert result["flashcards_status"] == "pending"


@pytest.mark.anyio
async def test_ask_notebook_chat_forbidden_for_another_student():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    module_id = uuid.uuid4()
    rec = _make_recommendation(rid, uuid.uuid4(), module_id, sid, eid)

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    service = _make_service(rec_repo=rec_repo)

    with pytest.raises(ForbiddenError):
        await service.ask_notebook_chat(uuid.uuid4(), rid, "Une question ?")


@pytest.mark.anyio
async def test_ask_notebook_chat_no_notebook_raises_not_found():
    from app.core.exceptions import NotebookNotFoundError

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    rec.student_notebook_id = None

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    service = _make_service(rec_repo=rec_repo)

    with pytest.raises(NotebookNotFoundError):
        await service.ask_notebook_chat(student_id, rid, "Une question ?")


@pytest.mark.anyio
async def test_ask_notebook_chat_success_returns_answer():
    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook()
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook

    notebooklm_service = AsyncMock()
    notebooklm_service.ask_chat.return_value = "Réponse."

    service = _make_service(rec_repo=rec_repo, student_notebook_repo=notebook_repo)
    service._notebooklm = notebooklm_service

    result = await service.ask_notebook_chat(student_id, rid, "Pourquoi ma maîtrise est-elle faible ?")

    assert result == "Réponse."
    notebooklm_service.ask_chat.assert_awaited_once_with(notebook.notebook_id, "Pourquoi ma maîtrise est-elle faible ?")


@pytest.mark.anyio
async def test_ask_notebook_chat_failure_raises_service_unavailable():
    from app.core.exceptions import NotebookLMUnavailableError

    rid, sid, eid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    student_id, module_id = uuid.uuid4(), uuid.uuid4()
    rec = _make_recommendation(rid, student_id, module_id, sid, eid)
    notebook = _make_notebook()
    rec.student_notebook_id = notebook.id

    rec_repo = AsyncMock()
    rec_repo.get_by_id.return_value = rec
    notebook_repo = AsyncMock()
    notebook_repo.get_by_id.return_value = notebook

    notebooklm_service = AsyncMock()
    notebooklm_service.ask_chat.return_value = None  # échec réel côté service (jamais une exception)

    service = _make_service(rec_repo=rec_repo, student_notebook_repo=notebook_repo)
    service._notebooklm = notebooklm_service

    with pytest.raises(NotebookLMUnavailableError):
        await service.ask_notebook_chat(student_id, rid, "Question ?")
