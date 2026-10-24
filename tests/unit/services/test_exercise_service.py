import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import (
    ExerciseHasSubmissionsError,
    ExerciseNotDraftError,
    ExerciseNotFoundError,
    ForbiddenError,
    MinimumQuestionCountError,
    NotExerciseOwnerError,
    QuestionNotFoundError,
)
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.repositories.pagination import CursorPage
from app.services.exercise_service import ExerciseService


def _make_exercise(
    exercise_id: uuid.UUID,
    module_id: uuid.UUID,
    professor_id: uuid.UUID,
    title: str = "Examen final",
    status: ExerciseStatus = ExerciseStatus.DRAFT,
) -> Exercise:
    now = datetime.now(timezone.utc)
    return Exercise(
        id=exercise_id,
        module_id=module_id,
        course_id=None,
        created_by_professor_id=professor_id,
        title=title,
        description=None,
        status=status,
        deadline=None,
        created_at=now,
        updated_at=now,
        questions=[],
    )


def _make_service(
    exercise_repo=None,
    module_repo=None,
    user_repo=None,
    clarification_repo=None,
    solution_variant_repo=None,
    submission_repo=None,
) -> ExerciseService:
    clarification_mock = clarification_repo or AsyncMock()
    if clarification_repo is None:
        clarification_mock.list_pending_blocking_by_exercise.return_value = []
    variant_mock = solution_variant_repo or AsyncMock()
    if solution_variant_repo is None:
        variant_mock.list_by_question.return_value = []
    return ExerciseService(
        exercise_repo or AsyncMock(),
        module_repo or AsyncMock(),
        user_repo or AsyncMock(),
        clarification_mock,
        variant_mock,
        submission_repo or AsyncMock(),
    )


def _make_module(module_id: uuid.UUID) -> MagicMock:
    m = MagicMock()
    m.id = module_id
    m.name = "Analyse Numérique"
    return m


def _make_professor(professor_id: uuid.UUID) -> MagicMock:
    p = MagicMock()
    p.id = professor_id
    p.first_name = "Alice"
    p.last_name = "Dupont"
    return p


@pytest.mark.anyio
async def test_get_by_id_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.get_by_id(eid)

    assert result.id == eid
    assert result.title == "Examen final"
    assert result.status == ExerciseStatus.DRAFT
    assert result.module_name == "Analyse Numérique"
    assert result.professor_full_name == "Alice Dupont"
    exercise_repo.get_by_id.assert_awaited_once_with(eid)


@pytest.mark.anyio
async def test_get_by_id_not_found():
    eid = uuid.uuid4()
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = None

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(ExerciseNotFoundError):
        await service.get_by_id(eid)


@pytest.mark.anyio
async def test_create_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)
    questions_data = [{"order": 1, "statement": "Q1", "bareme": {"points": 5}}]

    exercise_repo = AsyncMock()
    exercise_repo.create_with_questions.return_value = exercise

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.create(mid, pid, "  Examen final  ", None, questions_data)

    assert result.title == "Examen final"
    exercise_repo.create_with_questions.assert_awaited_once_with(
        module_id=mid,
        created_by_professor_id=pid,
        title="Examen final",
        description=None,
        questions_data=questions_data,
        sections_data=None,
    )


@pytest.mark.anyio
async def test_publish_success():
    """Publication réussie : complétude ET confirmation (hash à jour) satisfaites."""
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    cid = uuid.uuid4()
    qid = uuid.uuid4()
    deadline = datetime.now(timezone.utc) + timedelta(days=1)

    # Gap fermé (workflow upload-only) : _check_completeness bloque
    # désormais toute publication d'un exercice à 0 question — il en faut
    # une, complète (barème + variante de référence), pour que ce test de
    # succès reste un test de succès.
    bareme = MagicMock(points=Decimal("5.00"), criteria=[{"id": "c1", "label": "Exactitude", "points": 5.0}])
    question = MagicMock(id=qid, order=1, statement="Calculer l'aire", bareme=bareme)
    exercise = _make_exercise(eid, mid, pid)
    exercise.questions = [question]
    published = _make_exercise(eid, mid, pid, status=ExerciseStatus.PUBLISHED_AS_EXAM)
    published.course_id = cid
    published.deadline = deadline

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise
    exercise_repo.publish.return_value = published

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    reference_variant = MagicMock(is_reference=True, content="Solution", structured_content=None, reasoning_summary="Résumé")
    variant_repo = AsyncMock()
    variant_repo.list_by_question.return_value = [reference_variant]

    clarification_repo = AsyncMock()
    clarification_repo.list_pending_blocking_by_exercise.return_value = []

    service = _make_service(
        exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo,
        solution_variant_repo=variant_repo, clarification_repo=clarification_repo,
    )
    # Confirmation valide : hash calculé sur l'état ACTUEL de l'exercice
    # (avec sa question complète), exactement ce que publish() recalculera
    # pour comparer.
    exercise.publication_confirmed_hash = await service._compute_publication_readiness_hash(exercise)

    result = await service.publish(eid, pid, ExerciseStatus.PUBLISHED_AS_EXAM, cid, deadline)

    assert result.status == ExerciseStatus.PUBLISHED_AS_EXAM
    assert result.course_id == cid
    exercise_repo.publish.assert_awaited_once_with(
        exercise_id=eid, status=ExerciseStatus.PUBLISHED_AS_EXAM, course_id=cid, deadline=deadline,
        difficulty_level=None,
    )


@pytest.mark.anyio
async def test_publish_to_library_without_difficulty_level_raises():
    """Câblage Recommendation_Agent (clôture) — verrou distinct, jamais de complétude EXAM/HOMEWORK exigée ici."""
    from app.core.exceptions import MissingDifficultyLevelError

    eid, mid, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)

    with pytest.raises(MissingDifficultyLevelError):
        await service.publish(eid, pid, ExerciseStatus.ARCHIVED_IN_LIBRARY, None, None)
    exercise_repo.publish.assert_not_awaited()


@pytest.mark.anyio
async def test_publish_to_library_with_difficulty_level_success():
    from app.domain.models.assessment.exercise import ExerciseDifficulty

    eid, mid, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)
    archived = _make_exercise(eid, mid, pid, status=ExerciseStatus.ARCHIVED_IN_LIBRARY)
    archived.difficulty_level = ExerciseDifficulty.FACILE

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise
    exercise_repo.publish.return_value = archived

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.publish(
        eid, pid, ExerciseStatus.ARCHIVED_IN_LIBRARY, None, None,
        difficulty_level=ExerciseDifficulty.FACILE,
    )

    assert result.status == ExerciseStatus.ARCHIVED_IN_LIBRARY
    assert result.difficulty_level == ExerciseDifficulty.FACILE
    exercise_repo.publish.assert_awaited_once_with(
        exercise_id=eid, status=ExerciseStatus.ARCHIVED_IN_LIBRARY, course_id=None, deadline=None,
        difficulty_level=ExerciseDifficulty.FACILE,
    )


def _make_complete_question_setup(qid: uuid.UUID):
    """
    Question satisfaisant _check_completeness (barème + variante de
    référence) — factorisé car le gap "0 question" fermé ici (workflow
    upload-only) exige désormais cet état minimal pour tout test de publish()
    qui ne teste PAS spécifiquement la complétude elle-même.
    """
    bareme = MagicMock(points=Decimal("5.00"), criteria=[{"id": "c1", "label": "Exactitude", "points": 5.0}])
    question = MagicMock(id=qid, order=1, statement="Calculer l'aire", bareme=bareme)
    reference_variant = MagicMock(is_reference=True, content="Solution", structured_content=None, reasoning_summary="Résumé")
    variant_repo = AsyncMock()
    variant_repo.list_by_question.return_value = [reference_variant]
    clarification_repo = AsyncMock()
    clarification_repo.list_pending_blocking_by_exercise.return_value = []
    return question, variant_repo, clarification_repo


@pytest.mark.anyio
async def test_publish_without_confirmation_raises():
    """Complétude satisfaite mais aucune confirmation posée -> PublicationNotConfirmedError(stale=False)."""
    from app.core.exceptions import PublicationNotConfirmedError

    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)  # publication_confirmed_hash=None par défaut
    question, variant_repo, clarification_repo = _make_complete_question_setup(qid)
    exercise.questions = [question]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(
        exercise_repo=exercise_repo, solution_variant_repo=variant_repo, clarification_repo=clarification_repo,
    )

    with pytest.raises(PublicationNotConfirmedError) as exc_info:
        await service.publish(eid, pid, ExerciseStatus.PUBLISHED_AS_EXAM, uuid.uuid4(), datetime.now(timezone.utc))

    assert exc_info.value.stale is False
    exercise_repo.publish.assert_not_awaited()


@pytest.mark.anyio
async def test_publish_stale_confirmation_raises():
    """Confirmation posée mais périmée (état modifié depuis) -> PublicationNotConfirmedError(stale=True)."""
    from app.core.exceptions import PublicationNotConfirmedError

    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)
    question, variant_repo, clarification_repo = _make_complete_question_setup(qid)
    exercise.questions = [question]
    exercise.publication_confirmed_hash = "un-hash-qui-ne-correspond-plus-a-rien"

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(
        exercise_repo=exercise_repo, solution_variant_repo=variant_repo, clarification_repo=clarification_repo,
    )

    with pytest.raises(PublicationNotConfirmedError) as exc_info:
        await service.publish(eid, pid, ExerciseStatus.PUBLISHED_AS_EXAM, uuid.uuid4(), datetime.now(timezone.utc))

    assert exc_info.value.stale is True
    exercise_repo.publish.assert_not_awaited()


@pytest.mark.anyio
async def test_confirm_publication_readiness_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid = uuid.uuid4()

    bareme = MagicMock(points=Decimal("5.00"), criteria=[{"id": "c1", "label": "Exactitude", "points": 5.0}])
    question = MagicMock(id=qid, order=1, statement="Calculer l'aire", bareme=bareme)

    exercise = _make_exercise(eid, mid, pid)
    exercise.questions = [question]

    reference_variant = MagicMock(
        is_reference=True, content="Solution de référence", structured_content=None,
        reasoning_summary="Résumé du raisonnement",
    )
    variant_repo = AsyncMock()
    variant_repo.list_by_question.return_value = [reference_variant]

    clarification_repo = AsyncMock()
    clarification_repo.list_pending_blocking_by_exercise.return_value = []

    confirmed_exercise = _make_exercise(eid, mid, pid)
    confirmed_exercise.questions = [question]
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise
    exercise_repo.confirm_publication_readiness.return_value = confirmed_exercise

    service = _make_service(
        exercise_repo=exercise_repo, clarification_repo=clarification_repo, solution_variant_repo=variant_repo,
    )

    result = await service.confirm_publication_readiness(eid, pid)

    assert result.exercise_id == eid
    assert len(result.questions) == 1
    assert result.questions[0].reference_variant_summary == "Résumé du raisonnement"
    exercise_repo.confirm_publication_readiness.assert_awaited_once()
    call_kwargs = exercise_repo.confirm_publication_readiness.await_args.kwargs
    assert call_kwargs["exercise_id"] == eid
    assert call_kwargs["confirmed_hash"]  # non vide


@pytest.mark.anyio
async def test_confirm_publication_readiness_requires_completeness():
    """Ne confirme jamais un état incomplet — même verrou que publish()."""
    from app.core.exceptions import IncompleteExerciseSetupError

    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid = uuid.uuid4()

    question = MagicMock(id=qid, bareme=None)
    exercise = _make_exercise(eid, mid, pid)
    exercise.questions = [question]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)

    with pytest.raises(IncompleteExerciseSetupError):
        await service.confirm_publication_readiness(eid, pid)
    exercise_repo.confirm_publication_readiness.assert_not_awaited()


@pytest.mark.anyio
async def test_publish_exercise_not_found():
    eid = uuid.uuid4()
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = None

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(ExerciseNotFoundError):
        await service.publish(eid, uuid.uuid4(), ExerciseStatus.DRAFT, None, None)


@pytest.mark.anyio
async def test_publish_not_owner_raises():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    other_professor = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(NotExerciseOwnerError):
        await service.publish(eid, other_professor, ExerciseStatus.DRAFT, None, None)
    exercise_repo.publish.assert_not_awaited()


@pytest.mark.anyio
async def test_list_by_course_calls_repository():
    """Le service délègue list_by_course au repository et retourne un CursorPage valide."""
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    cid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)
    exercise.course_id = cid
    page = CursorPage(items=[exercise], next_cursor="next", has_more=True)

    exercise_repo = AsyncMock()
    exercise_repo.list_by_course.return_value = page

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.list_by_course(cid, cursor="cursor", limit=10)

    assert result.has_more is True
    assert result.next_cursor == "next"
    assert len(result.items) == 1
    assert result.items[0].id == eid
    exercise_repo.list_by_course.assert_awaited_once_with(cid, "cursor", 10)


@pytest.mark.anyio
async def test_list_by_module_calls_repository():
    """Le service délègue list_by_module au repository et retourne un CursorPage valide."""
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)
    page = CursorPage(items=[exercise], next_cursor="next", has_more=True)

    exercise_repo = AsyncMock()
    exercise_repo.list_library_by_module.return_value = page

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.list_by_module(mid, cursor="cursor", limit=10)

    assert result.has_more is True
    assert result.next_cursor == "next"
    assert len(result.items) == 1
    assert len(result.items) == 1
    assert result.items[0].id == eid
    exercise_repo.list_library_by_module.assert_awaited_once_with(mid, "cursor", 10, difficulty_level=None)


@pytest.mark.anyio
async def test_list_by_module_with_competency_filters_matching_exercises():
    """
    Navigation de la Library (câblage Recommendation_Agent, Phase 3) — avec
    `competency`, seuls les exercices dont AU MOINS une Question couvre
    réellement cette compétence (via c2pct_scaffold.get_competency_for_
    subquestion) sont retournés, jamais un filtre par ID de sous-question.
    """
    mid, pid = uuid.uuid4(), uuid.uuid4()
    matching_id, other_id = uuid.uuid4(), uuid.uuid4()

    matching = _make_exercise(matching_id, mid, pid, title="Exo aires")
    matching.questions = [Question(
        id=uuid.uuid4(), exercise_id=matching_id, order=1, statement="Q1", covered_subquestions=["3.1"],
    )]
    other = _make_exercise(other_id, mid, pid, title="Exo dérivées")
    other.questions = [Question(
        id=uuid.uuid4(), exercise_id=other_id, order=1, statement="Q1", covered_subquestions=["1.1"],
    )]

    page = CursorPage(items=[matching, other], next_cursor=None, has_more=False)
    exercise_repo = AsyncMock()
    exercise_repo.list_library_by_module.return_value = page

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.list_by_module(mid, competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING)

    assert result.has_more is False
    assert result.next_cursor is None
    assert [item.id for item in result.items] == [matching_id]


@pytest.mark.anyio
async def test_list_by_module_with_competency_walks_all_pages():
    """Le filtre par compétence n'est pas une colonne SQL — il doit parcourir TOUTES les pages, jamais s'arrêter à la première."""
    mid, pid = uuid.uuid4(), uuid.uuid4()
    match_page1_id, match_page2_id = uuid.uuid4(), uuid.uuid4()

    exercise_page1 = _make_exercise(match_page1_id, mid, pid, title="Exo page 1")
    exercise_page1.questions = [Question(
        id=uuid.uuid4(), exercise_id=match_page1_id, order=1, statement="Q1", covered_subquestions=["3.1"],
    )]
    exercise_page2 = _make_exercise(match_page2_id, mid, pid, title="Exo page 2")
    exercise_page2.questions = [Question(
        id=uuid.uuid4(), exercise_id=match_page2_id, order=1, statement="Q1", covered_subquestions=["3.2"],
    )]

    page1 = CursorPage(items=[exercise_page1], next_cursor="cursor2", has_more=True)
    page2 = CursorPage(items=[exercise_page2], next_cursor=None, has_more=False)
    exercise_repo = AsyncMock()
    exercise_repo.list_library_by_module.side_effect = [page1, page2]

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.list_by_module(mid, competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING)

    assert {item.id for item in result.items} == {match_page1_id, match_page2_id}
    assert exercise_repo.list_library_by_module.await_count == 2


@pytest.mark.anyio
async def test_publish_incomplete_exercise_raises():
    """Vérifie que publish vers PUBLISHED lève IncompleteExerciseSetupError si la configuration est incomplète."""
    from app.core.exceptions import IncompleteExerciseSetupError

    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid = uuid.uuid4()

    q_mock = MagicMock()
    q_mock.id = qid
    q_mock.bareme = None  # Barème manquant

    exercise = _make_exercise(eid, mid, pid)
    exercise.questions = [q_mock]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    clarification_repo = AsyncMock()
    clarification_repo.list_pending_blocking_by_exercise.return_value = [MagicMock()]  # Clarification en attente

    variant_repo = AsyncMock()
    variant_repo.list_by_question.return_value = []  # Aucune variante de référence

    service = _make_service(
        exercise_repo=exercise_repo,
        clarification_repo=clarification_repo,
        solution_variant_repo=variant_repo,
    )

    with pytest.raises(IncompleteExerciseSetupError) as exc_info:
        await service.publish(
            exercise_id=eid,
            requesting_professor_id=pid,
            status=ExerciseStatus.PUBLISHED_AS_EXAM,
            course_id=None,
            deadline=None,
        )

    assert "1 question(s) sans barème" in str(exc_info.value)
    assert "1 question(s) sans variante de référence" in str(exc_info.value)
    assert "1 clarification(s) en attente" in str(exc_info.value)


@pytest.mark.anyio
async def test_publish_no_questions_raises():
    """
    Gap fermé (workflow upload-only, cf. ExerciseCreateRequest.questions
    désormais optionnel) : un exercice resté à 0 question (créé pour
    upload OCR ultérieur, jamais suivi d'un dépôt de document) ne doit
    JAMAIS pouvoir être publié — sans cette garde, les 3 autres conditions
    passent trivialement (aucune itération sur une liste vide).
    """
    from app.core.exceptions import IncompleteExerciseSetupError

    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)  # questions=[] par défaut

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)

    with pytest.raises(IncompleteExerciseSetupError) as exc_info:
        await service.publish(
            exercise_id=eid,
            requesting_professor_id=pid,
            status=ExerciseStatus.PUBLISHED_AS_EXAM,
            course_id=None,
            deadline=None,
        )

    assert "aucune question définie" in str(exc_info.value)
    exercise_repo.publish.assert_not_awaited()


@pytest.mark.anyio
async def test_upload_reference_document_uploads_and_triggers_celery(monkeypatch):
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    storage = AsyncMock()
    celery_mock = MagicMock()
    monkeypatch.setattr("app.services.exercise_service.process_exercise_reference_document", celery_mock)

    service = ExerciseService(
        exercise_repo,
        module_repo,
        user_repo,
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        storage_service=storage,
    )

    result = await service.upload_reference_document(
        exercise_id=eid,
        professor_id=pid,
        document_bytes=b"%PDF-1.4",
        mime_type="application/pdf",
    )

    assert result.id == eid
    storage.upload.assert_awaited_once()
    blob_path = storage.upload.await_args.args[1]
    assert blob_path == f"exercises/{eid}/reference.pdf"
    celery_mock.delay.assert_called_once_with(
        exercise_id=str(eid),
        professor_id=str(pid),
        document_path=blob_path,
        mime_type="application/pdf",
    )


@pytest.mark.anyio
async def test_upload_reference_document_rejects_non_draft():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.PUBLISHED_AS_EXAM)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)

    with pytest.raises(ForbiddenError):
        await service.upload_reference_document(
            exercise_id=eid,
            professor_id=pid,
            document_bytes=b"data",
            mime_type="application/pdf",
        )


@pytest.mark.anyio
async def test_upload_reference_document_rejects_non_owner():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)

    with pytest.raises(NotExerciseOwnerError):
        await service.upload_reference_document(
            exercise_id=eid,
            professor_id=uuid.uuid4(),
            document_bytes=b"data",
            mime_type="application/pdf",
        )


@pytest.mark.anyio
async def test_list_by_professor_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)

    exercise_repo = AsyncMock()
    exercise_repo.list_by_professor.return_value = CursorPage(items=[exercise], next_cursor=None, has_more=False)

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.list_by_professor(pid)

    assert len(result.items) == 1
    assert result.items[0].id == eid
    exercise_repo.list_by_professor.assert_awaited_once_with(pid, None, 50)


@pytest.mark.anyio
async def test_delete_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.DRAFT)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    submission_repo = AsyncMock()
    submission_repo.list_by_exercise.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    service = _make_service(exercise_repo=exercise_repo, submission_repo=submission_repo)
    await service.delete(eid, pid)

    submission_repo.list_by_exercise.assert_awaited_once_with(eid, limit=1)
    exercise_repo.delete.assert_awaited_once_with(eid)


@pytest.mark.anyio
async def test_delete_not_found():
    eid = uuid.uuid4()
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = None

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(ExerciseNotFoundError):
        await service.delete(eid, uuid.uuid4())


@pytest.mark.anyio
async def test_delete_rejects_non_owner():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.DRAFT)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(NotExerciseOwnerError):
        await service.delete(eid, uuid.uuid4())


@pytest.mark.anyio
async def test_delete_rejects_non_draft():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.PUBLISHED_AS_EXAM)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(ExerciseNotDraftError):
        await service.delete(eid, pid)


@pytest.mark.anyio
async def test_delete_rejects_when_has_submissions():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.DRAFT)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    submission_repo = AsyncMock()
    submission_repo.list_by_exercise.return_value = CursorPage(
        items=[MagicMock()], next_cursor=None, has_more=False
    )

    service = _make_service(exercise_repo=exercise_repo, submission_repo=submission_repo)
    with pytest.raises(ExerciseHasSubmissionsError):
        await service.delete(eid, pid)

    exercise_repo.delete.assert_not_awaited()


def _make_question(question_id: uuid.UUID, exercise_id: uuid.UUID, order: int = 1) -> Question:
    """
    Bug préexistant corrigé ici (sans rapport avec le chantier upload-only) :
    covered_subquestions a default=list côté SQLAlchemy, mais ce default
    Python ne s'applique qu'au flush() réel — un Question() construit
    directement en mémoire (jamais flushé, comme ici) garde l'attribut à
    None. QuestionRead.covered_subquestions (list[str], default_factory
    seulement si l'attribut est ABSENT) rejette alors ce None à la
    validation. Passé explicitement ici pour refléter l'état réel après
    flush(), jamais une omission côté schéma.
    """
    return Question(
        id=question_id, exercise_id=exercise_id, order=order, statement="Q", bareme=None,
        covered_subquestions=[],
    )


@pytest.mark.anyio
async def test_set_question_bareme_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)
    exercise.questions = [_make_question(qid, eid)]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise
    exercise_repo.set_bareme_for_question.return_value = MagicMock()

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    await service.set_question_bareme(eid, qid, pid, Decimal("10"), [{"label": "C1", "points": 10}])

    exercise_repo.set_bareme_for_question.assert_awaited_once_with(
        question_id=qid, points=Decimal("10"), criteria=[{"label": "C1", "points": 10}]
    )


@pytest.mark.anyio
async def test_set_question_bareme_rejects_unknown_question():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid)
    exercise.questions = []

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(QuestionNotFoundError):
        await service.set_question_bareme(eid, uuid.uuid4(), pid, Decimal("10"), [])


@pytest.mark.anyio
async def test_add_question_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.DRAFT)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    await service.add_question(eid, pid, "Nouvelle question")

    exercise_repo.add_question.assert_awaited_once_with(eid, "Nouvelle question")


@pytest.mark.anyio
async def test_add_question_rejects_non_draft():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.PUBLISHED_AS_EXAM)

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(ExerciseNotDraftError):
        await service.add_question(eid, pid, "Nouvelle question")
    exercise_repo.add_question.assert_not_awaited()


@pytest.mark.anyio
async def test_update_question_statement_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.DRAFT)
    exercise.questions = [_make_question(qid, eid)]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise
    exercise_repo.update_question_statement.return_value = _make_question(qid, eid)

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    await service.update_question_statement(eid, qid, pid, "Statement modifié")

    exercise_repo.update_question_statement.assert_awaited_once_with(qid, "Statement modifié")


@pytest.mark.anyio
async def test_update_question_statement_rejects_unknown_question():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.DRAFT)
    exercise.questions = []

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(QuestionNotFoundError):
        await service.update_question_statement(eid, uuid.uuid4(), pid, "x")


@pytest.mark.anyio
async def test_delete_question_success():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid1 = uuid.uuid4()
    qid2 = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.DRAFT)
    exercise.questions = [_make_question(qid1, eid, order=1), _make_question(qid2, eid, order=2)]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise
    exercise_repo.delete_question.return_value = True

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    await service.delete_question(eid, qid1, pid)

    exercise_repo.delete_question.assert_awaited_once_with(qid1)


@pytest.mark.anyio
async def test_delete_question_rejects_last_question():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    qid = uuid.uuid4()
    exercise = _make_exercise(eid, mid, pid, status=ExerciseStatus.DRAFT)
    exercise.questions = [_make_question(qid, eid)]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    service = _make_service(exercise_repo=exercise_repo)
    with pytest.raises(MinimumQuestionCountError):
        await service.delete_question(eid, qid, pid)
    exercise_repo.delete_question.assert_not_awaited()


@pytest.mark.anyio
async def test_list_assigned_for_student():
    """
    Gap fermé (espace étudiant) : ExerciseRepository.
    list_published_exams_for_student existait déjà mais n'était appelée par
    aucun service — un étudiant n'avait aucun moyen de découvrir les
    examens/devoirs qui lui sont assignés.
    """
    sid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    student_id = uuid.uuid4()
    exercise = _make_exercise(sid, mid, pid, status=ExerciseStatus.PUBLISHED_AS_EXAM)

    exercise_repo = AsyncMock()
    exercise_repo.list_published_exams_for_student.return_value = CursorPage(
        items=[exercise], next_cursor=None, has_more=False
    )

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(exercise_repo=exercise_repo, module_repo=module_repo, user_repo=user_repo)
    result = await service.list_assigned_for_student(student_id)

    assert len(result.items) == 1
    assert result.items[0].id == sid
    exercise_repo.list_published_exams_for_student.assert_awaited_once_with(student_id, None, 50)