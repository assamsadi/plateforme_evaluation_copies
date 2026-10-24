import uuid
from unittest.mock import MagicMock

import pytest

from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.repositories.pagination import CursorPage


def _make_exercise_read():
    return {
        "id": str(uuid.uuid4()),
        "module_id": str(uuid.uuid4()),
        "module_name": "Analyse",
        "course_id": None,
        "created_by_professor_id": str(uuid.uuid4()),
        "professor_full_name": "Bob Martin",
        "title": "Examen final",
        "description": "Examen de fin de semestre",
        "status": ExerciseStatus.DRAFT.value,
        "deadline": None,
        "difficulty_level": None,
        "questions": [],
    }


def _make_submission_read():
    return {
        "id": str(uuid.uuid4()),
        "exercise_id": str(uuid.uuid4()),
        "exercise_title": "Examen final",
        "student_id": str(uuid.uuid4()),
        "student_full_name": "Alice Dupont",
        "attempt_number": 1,
        "status": SubmissionStatus.PENDING_OCR.value,
        "created_at": "2024-01-01T00:00:00Z",
    }


def _make_submission_summary_read():
    return {
        "id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "student_full_name": "Alice Dupont",
        "attempt_number": 1,
        "status": SubmissionStatus.EVALUATED.value,
        "total_score": "14.50",
        "created_at": "2024-01-01T00:00:00Z",
    }


# --- Exercise Router ---

@pytest.mark.anyio
async def test_get_exercise_success(admin_client, mock_exercise_service):
    mock_exercise_service.get_by_id.return_value = _make_exercise_read()
    response = await admin_client.get(f"/api/v1/exercises/{uuid.uuid4()}")
    assert response.status_code == 200
    mock_exercise_service.get_by_id.assert_awaited_once()


@pytest.mark.anyio
async def test_delete_exercise_success(professor_client, mock_exercise_service):
    mock_exercise_service.delete.return_value = None
    exercise_id = uuid.uuid4()
    response = await professor_client.delete(f"/api/v1/exercises/{exercise_id}")
    assert response.status_code == 204
    mock_exercise_service.delete.assert_awaited_once_with(
        exercise_id, "00000000-0000-4000-a000-000000000002"
    )


@pytest.mark.anyio
async def test_delete_exercise_requires_professor(student_client, mock_exercise_service):
    response = await student_client.delete(f"/api/v1/exercises/{uuid.uuid4()}")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_list_exercise_submissions_success(professor_client, mock_evaluation_service):
    mock_evaluation_service.list_by_exercise_for_professor.return_value = CursorPage(
        items=[_make_submission_summary_read()], next_cursor=None, has_more=False
    )
    exercise_id = uuid.uuid4()
    response = await professor_client.get(f"/api/v1/exercises/{exercise_id}/submissions")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    mock_evaluation_service.list_by_exercise_for_professor.assert_awaited_once_with(
        exercise_id=exercise_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
        cursor=None,
        limit=50,
    )


@pytest.mark.anyio
async def test_list_exercise_submissions_requires_professor(student_client, mock_evaluation_service):
    response = await student_client.get(f"/api/v1/exercises/{uuid.uuid4()}/submissions")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_list_my_exercises(professor_client, mock_exercise_service):
    mock_exercise_service.list_by_professor.return_value = CursorPage(
        items=[_make_exercise_read()], next_cursor=None, has_more=False
    )
    response = await professor_client.get("/api/v1/exercises/mine")
    assert response.status_code == 200
    mock_exercise_service.list_by_professor.assert_awaited_once_with(
        "00000000-0000-4000-a000-000000000002", cursor=None, limit=50
    )


@pytest.mark.anyio
async def test_list_exercise_correction_blocks(professor_client, mock_document_structuring_service):
    exercise_id = uuid.uuid4()
    mock_document_structuring_service.list_blocks_for_exercise.return_value = []
    response = await professor_client.get(f"/api/v1/exercises/{exercise_id}/correction-blocks")
    assert response.status_code == 200
    mock_document_structuring_service.list_blocks_for_exercise.assert_awaited_once_with(
        exercise_id=exercise_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
    )


@pytest.mark.anyio
async def test_list_exercises_by_course(admin_client, mock_exercise_service):
    mock_exercise_service.list_by_course.return_value = CursorPage(
        items=[_make_exercise_read()], next_cursor=None, has_more=False
    )
    response = await admin_client.get(f"/api/v1/courses/{uuid.uuid4()}/exercises")
    assert response.status_code == 200
    mock_exercise_service.list_by_course.assert_awaited_once()


@pytest.mark.anyio
async def test_list_module_library(admin_client, mock_exercise_service):
    """
    Navigation de la Library (câblage Recommendation_Agent, Phase 3) —
    accessible à tout utilisateur authentifié, même contrôle d'accès que
    GET /courses/{id}/exercises (ExerciseRead n'expose aucun détail de
    correction, cf. docstring ExerciseService).
    """
    module_id = uuid.uuid4()
    mock_exercise_service.list_by_module.return_value = CursorPage(
        items=[_make_exercise_read()], next_cursor=None, has_more=False
    )
    response = await admin_client.get(
        f"/api/v1/modules/{module_id}/library?competency=algorithmic_structuring"
    )
    assert response.status_code == 200
    mock_exercise_service.list_by_module.assert_awaited_once_with(
        module_id=module_id, competency="algorithmic_structuring", difficulty=None, cursor=None, limit=50,
    )


@pytest.mark.anyio
async def test_list_module_library_without_competency_filter(admin_client, mock_exercise_service):
    module_id = uuid.uuid4()
    mock_exercise_service.list_by_module.return_value = CursorPage(
        items=[_make_exercise_read()], next_cursor="next", has_more=True
    )
    response = await admin_client.get(f"/api/v1/modules/{module_id}/library")
    assert response.status_code == 200
    mock_exercise_service.list_by_module.assert_awaited_once_with(
        module_id=module_id, competency=None, difficulty=None, cursor=None, limit=50,
    )


@pytest.mark.anyio
async def test_list_module_library_with_difficulty_filter(admin_client, mock_exercise_service):
    """Clôture — filtre `difficulty` combinable avec `competency`, poussé au SQL (cf. docstring repository)."""
    module_id = uuid.uuid4()
    mock_exercise_service.list_by_module.return_value = CursorPage(
        items=[_make_exercise_read()], next_cursor=None, has_more=False
    )
    response = await admin_client.get(f"/api/v1/modules/{module_id}/library?difficulty=facile")
    assert response.status_code == 200
    mock_exercise_service.list_by_module.assert_awaited_once_with(
        module_id=module_id, competency=None, difficulty="facile", cursor=None, limit=50,
    )


@pytest.mark.anyio
async def test_create_exercise_success(professor_client, mock_exercise_service):
    mock_exercise_service.create.return_value = _make_exercise_read()
    payload = {
        "module_id": str(uuid.uuid4()),
        "title": "Examen final",
        "description": "Examen de fin de semestre",
        "questions": [
            {
                "order": 1,
                "statement": "Résoudre l'équation x+2=5",
                "bareme": {"points": 10, "criteria": []},
            }
        ],
    }
    response = await professor_client.post("/api/v1/exercises", json=payload)
    assert response.status_code == 201
    mock_exercise_service.create.assert_awaited_once()


@pytest.mark.anyio
async def test_create_exercise_requires_professor(student_client, mock_exercise_service):
    payload = {
        "module_id": str(uuid.uuid4()),
        "title": "Examen",
        "description": "Desc",
        "questions": [
            {"order": 1, "statement": "Question 1", "bareme": {"points": 10}}
        ],
    }
    response = await student_client.post("/api/v1/exercises", json=payload)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_create_exercise_empty_questions_accepted(professor_client, mock_exercise_service):
    """
    Décision produit : la création n'exige plus min_length=1 sur questions —
    le formulaire ne collecte plus que module/titre/description, le
    remplissage se fait exclusivement via dépôt de document de référence
    (OCR, ExerciseRepository.add_structure). ExerciseService._check_
    completeness bloque désormais la publication tant qu'aucune question
    n'existe (cf. test dédié dans test_exercise_service.py), jamais ici
    à la création.
    """
    mock_exercise_service.create.return_value = _make_exercise_read()
    payload = {
        "module_id": str(uuid.uuid4()),
        "title": "Examen",
        "description": "Desc",
        "questions": [],
    }
    response = await professor_client.post("/api/v1/exercises", json=payload)
    assert response.status_code == 201
    mock_exercise_service.create.assert_awaited_once()


@pytest.mark.anyio
async def test_publish_exercise_success(professor_client, mock_exercise_service):
    mock_exercise_service.publish.return_value = _make_exercise_read()
    payload = {
        "status": ExerciseStatus.PUBLISHED_AS_EXAM.value,
        "course_id": str(uuid.uuid4()),
        "deadline": "2024-06-01T00:00:00Z",
    }
    response = await professor_client.post(f"/api/v1/exercises/{uuid.uuid4()}/publish", json=payload)
    assert response.status_code == 200
    mock_exercise_service.publish.assert_awaited_once()


@pytest.mark.anyio
async def test_publish_exercise_exam_missing_course_422(professor_client, mock_exercise_service):
    """PUBLISHED_AS_EXAM exige course_id + deadline → 422."""
    payload = {
        "status": ExerciseStatus.PUBLISHED_AS_EXAM.value,
        "course_id": None,
        "deadline": None,
    }
    response = await professor_client.post(f"/api/v1/exercises/{uuid.uuid4()}/publish", json=payload)
    assert response.status_code == 422
    mock_exercise_service.publish.assert_not_awaited()


@pytest.mark.anyio
async def test_archive_exercise_to_library(professor_client, mock_exercise_service):
    mock_exercise_service.publish.return_value = _make_exercise_read()
    response = await professor_client.post(
        f"/api/v1/exercises/{uuid.uuid4()}/archive-to-library",
        json={"difficulty_level": "facile"},
    )
    assert response.status_code == 200
    mock_exercise_service.publish.assert_awaited_once()


@pytest.mark.anyio
async def test_archive_exercise_to_library_requires_difficulty_level(professor_client, mock_exercise_service):
    """Câblage Recommendation_Agent (clôture) — difficulty_level obligatoire dans le corps de la requête (422 Pydantic, service jamais atteint)."""
    response = await professor_client.post(f"/api/v1/exercises/{uuid.uuid4()}/archive-to-library", json={})
    assert response.status_code == 422
    mock_exercise_service.publish.assert_not_awaited()


@pytest.mark.anyio
async def test_set_question_bareme_success(professor_client, mock_exercise_service):
    mock_exercise_service.set_question_bareme.return_value = _make_exercise_read()
    exercise_id = uuid.uuid4()
    question_id = uuid.uuid4()
    response = await professor_client.put(
        f"/api/v1/exercises/{exercise_id}/questions/{question_id}/bareme",
        json={"points": 10, "criteria": [{"label": "C1", "points": 5}]},
    )
    assert response.status_code == 200
    mock_exercise_service.set_question_bareme.assert_awaited_once_with(
        exercise_id=exercise_id,
        question_id=question_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
        points=10,
        criteria=[{"label": "C1", "points": 5}],
    )


@pytest.mark.anyio
async def test_get_exercise_pipeline_status_success(professor_client, mock_exercise_service, mock_job_supervision_service):
    # Le handler accède à exercise.created_by_professor_id AVANT toute
    # sérialisation response_model (vérification de propriété) — un dict
    # brut (_make_exercise_read()) plante avec AttributeError ; il faut un
    # objet avec accès attribut, valeur alignée sur l'id du professeur du
    # fixture professor_client (cf. test_get_exercise_bareme, même pattern).
    exercise = MagicMock()
    exercise.created_by_professor_id = "00000000-0000-4000-a000-000000000002"
    mock_exercise_service.get_by_id.return_value = exercise
    mock_job_supervision_service.get_latest_for_exercise.return_value = None
    exercise_id = uuid.uuid4()
    response = await professor_client.get(f"/api/v1/exercises/{exercise_id}/pipeline-status")
    assert response.status_code == 200
    mock_job_supervision_service.get_latest_for_exercise.assert_awaited_once_with(exercise_id)


@pytest.mark.anyio
async def test_add_question_success(professor_client, mock_exercise_service):
    mock_exercise_service.add_question.return_value = _make_exercise_read()
    exercise_id = uuid.uuid4()
    response = await professor_client.post(
        f"/api/v1/exercises/{exercise_id}/questions", json={"statement": "Nouvelle question"}
    )
    assert response.status_code == 201
    mock_exercise_service.add_question.assert_awaited_once_with(
        exercise_id=exercise_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
        statement="Nouvelle question",
    )


@pytest.mark.anyio
async def test_update_question_success(professor_client, mock_exercise_service):
    mock_exercise_service.update_question_statement.return_value = _make_exercise_read()
    exercise_id = uuid.uuid4()
    question_id = uuid.uuid4()
    response = await professor_client.patch(
        f"/api/v1/exercises/{exercise_id}/questions/{question_id}", json={"statement": "Modifiée"}
    )
    assert response.status_code == 200
    mock_exercise_service.update_question_statement.assert_awaited_once_with(
        exercise_id=exercise_id,
        question_id=question_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
        statement="Modifiée",
    )


@pytest.mark.anyio
async def test_delete_question_success(professor_client, mock_exercise_service):
    mock_exercise_service.delete_question.return_value = _make_exercise_read()
    exercise_id = uuid.uuid4()
    question_id = uuid.uuid4()
    response = await professor_client.delete(f"/api/v1/exercises/{exercise_id}/questions/{question_id}")
    assert response.status_code == 200
    mock_exercise_service.delete_question.assert_awaited_once_with(
        exercise_id=exercise_id,
        question_id=question_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
    )


# --- Bareme Router ---

@pytest.mark.anyio
async def test_get_exercise_bareme(admin_client, mock_exercise_service):
    exercise = MagicMock()
    exercise.title = "Examen final"
    exercise.questions = []
    mock_exercise_service.get_by_id.return_value = exercise
    response = await admin_client.get(f"/api/v1/exercises/{uuid.uuid4()}/bareme")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Examen final"
    assert body["questions"] == []


# --- Submission Router ---

@pytest.mark.anyio
async def test_get_submission_success(admin_client, mock_submission_service):
    mock_submission_service.get_submission.return_value = _make_submission_read()
    response = await admin_client.get(f"/api/v1/submissions/{uuid.uuid4()}")
    assert response.status_code == 200
    mock_submission_service.get_submission.assert_awaited_once()


@pytest.mark.anyio
async def test_list_my_submissions(student_client, mock_submission_service):
    """
    Bug corrigé (espace étudiant) : le routeur appelait submission_service.
    _submission_repo.list_by_student(...) directement (attribut privé,
    jamais passé par le service -> Submission ORM brute jamais enrichie,
    échec de validation response_model à chaque appel réel, masqué ici
    avant correction par un AsyncMock nu qui accepte n'importe quel
    attribut). Passe désormais par SubmissionService.list_by_student.
    """
    mock_submission_service.list_by_student.return_value = CursorPage(
        items=[_make_submission_read()], next_cursor=None, has_more=False
    )
    response = await student_client.get("/api/v1/students/me/submissions")
    assert response.status_code == 200
    mock_submission_service.list_by_student.assert_awaited_once()


@pytest.mark.anyio
async def test_list_my_assigned_exercises(student_client, mock_exercise_service):
    """
    Gap fermé (espace étudiant) : ExerciseRepository.
    list_published_exams_for_student existait déjà mais n'était appelée par
    aucun endpoint.
    """
    mock_exercise_service.list_assigned_for_student.return_value = CursorPage(
        items=[_make_exercise_read()], next_cursor=None, has_more=False
    )
    response = await student_client.get("/api/v1/students/me/assigned-exercises")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    mock_exercise_service.list_assigned_for_student.assert_awaited_once()


@pytest.mark.anyio
async def test_list_my_assigned_exercises_requires_student(professor_client, mock_exercise_service):
    response = await professor_client.get("/api/v1/students/me/assigned-exercises")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_create_submission_success(student_client, mock_submission_service):
    mock_submission_service.create_submission.return_value = _make_submission_read()
    exercise_id = str(uuid.uuid4())
    response = await student_client.post(
        "/api/v1/submissions",
        data={"exercise_id": exercise_id},
        files={"document": ("copy.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 201
    mock_submission_service.create_submission.assert_awaited_once()


@pytest.mark.anyio
async def test_create_submission_rejects_unsupported_mime(student_client, mock_submission_service):
    exercise_id = str(uuid.uuid4())
    response = await student_client.post(
        "/api/v1/submissions",
        data={"exercise_id": exercise_id},
        files={"document": ("copy.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 422
    mock_submission_service.create_submission.assert_not_awaited()


@pytest.mark.anyio
async def test_create_submission_requires_student(professor_client, mock_submission_service):
    response = await professor_client.post(
        "/api/v1/submissions",
        data={"exercise_id": str(uuid.uuid4())},
        files={"document": ("copy.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert response.status_code == 403


# --- Jobs Router ---

@pytest.mark.anyio
async def test_get_submission_job_status(admin_client, mock_submission_service):
    mock_submission_service.get_submission.return_value = _make_submission_read()
    response = await admin_client.get(f"/api/v1/jobs/submission/{uuid.uuid4()}")
    assert response.status_code == 200
    mock_submission_service.get_submission.assert_awaited_once()