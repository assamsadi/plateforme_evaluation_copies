import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.core.exceptions import (
    AlreadySubmittedError,
    DeadlinePassedError,
    ExerciseNotFoundError,
    ExerciseNotPublishedError,
    NotInExamGroupError,
    StudentNotFoundError,
    StudentSuspendedError,
)
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.identity.user import AcademicStatus, Student
from app.services.submission_service import SubmissionService


@pytest.mark.anyio
async def test_submission_service_exercise_not_found():
    sub_repo = AsyncMock()
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = None

    service = SubmissionService(sub_repo, ex_repo, AsyncMock(), AsyncMock(), AsyncMock())
    with pytest.raises(ExerciseNotFoundError):
        await service.create_submission(uuid.uuid4(), uuid.uuid4(), b"data", "application/pdf")


@pytest.mark.anyio
async def test_submission_service_student_suspended():
    eid = uuid.uuid4()
    sid = uuid.uuid4()

    mock_exercise = MagicMock(id=eid)
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = mock_exercise

    user_repo = AsyncMock()
    mock_student = MagicMock(spec=Student)
    mock_student.academic_status = AcademicStatus.SUSPENDED
    user_repo.get_by_id_with_role_details.return_value = mock_student

    service = SubmissionService(AsyncMock(), ex_repo, AsyncMock(), user_repo, AsyncMock())
    with pytest.raises(StudentSuspendedError):
        await service.create_submission(eid, sid, b"data", "application/pdf")


@pytest.mark.anyio
async def test_submission_service_double_submission_prevented():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    cid = uuid.uuid4()

    mock_exercise = MagicMock(
        id=eid,
        status=ExerciseStatus.PUBLISHED_AS_EXAM,
        course_id=cid,
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
    )
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = mock_exercise

    user_repo = AsyncMock()
    mock_student = MagicMock(spec=Student)
    mock_student.academic_status = AcademicStatus.ACTIVE
    user_repo.get_by_id_with_role_details.return_value = mock_student

    course_repo = AsyncMock()
    course_repo.is_student_in_course_group.return_value = True

    sub_repo = AsyncMock()
    sub_repo.count_attempts.return_value = 1  # Already attempted once!

    service = SubmissionService(sub_repo, ex_repo, course_repo, user_repo, AsyncMock())
    with pytest.raises(AlreadySubmittedError):
        await service.create_submission(eid, sid, b"data", "application/pdf")


@pytest.mark.anyio
async def test_submission_service_deadline_passed():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    cid = uuid.uuid4()

    mock_exercise = MagicMock(
        id=eid,
        status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
        course_id=cid,
        deadline=datetime.now(timezone.utc) - timedelta(days=1),  # Expired
    )
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = mock_exercise

    user_repo = AsyncMock()
    mock_student = MagicMock(spec=Student)
    mock_student.academic_status = AcademicStatus.ACTIVE
    user_repo.get_by_id_with_role_details.return_value = mock_student

    course_repo = AsyncMock()
    course_repo.is_student_in_course_group.return_value = True

    service = SubmissionService(AsyncMock(), ex_repo, course_repo, user_repo, AsyncMock())
    with pytest.raises(DeadlinePassedError):
        await service.create_submission(eid, sid, b"data", "application/pdf")


@pytest.mark.anyio
async def test_submission_service_create_success():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    cid = uuid.uuid4()
    sub_id = uuid.uuid4()

    mock_exercise = MagicMock(
        id=eid,
        title="Math Exam",
        status=ExerciseStatus.PUBLISHED_AS_EXAM,
        course_id=cid,
        deadline=datetime.now(timezone.utc) + timedelta(days=1),
    )
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = mock_exercise

    user_repo = AsyncMock()
    mock_student = MagicMock(spec=Student)
    mock_student.academic_status = AcademicStatus.ACTIVE
    mock_student.first_name = "Alice"
    mock_student.last_name = "Dupont"
    user_repo.get_by_id_with_role_details.return_value = mock_student

    course_repo = AsyncMock()
    course_repo.is_student_in_course_group.return_value = True

    sub_repo = AsyncMock()
    sub_repo.count_attempts.return_value = 0
    
    mock_created_sub = Submission(
        id=sub_id,
        exercise_id=eid,
        student_id=sid,
        attempt_number=1,
        status=SubmissionStatus.PENDING_OCR,
        created_at=datetime.now(timezone.utc),
    )
    sub_repo.create.return_value = mock_created_sub

    service = SubmissionService(
        sub_repo, ex_repo, course_repo, user_repo, AsyncMock(),
        storage_service=AsyncMock(),
        event_publisher=AsyncMock(),
    )
    result = await service.create_submission(eid, sid, b"%PDF-1.4 fake", "application/pdf")

    assert result.id == sub_id
    assert result.attempt_number == 1
    sub_repo.create.assert_called_once_with(eid, sid, 1)
    sub_repo.update_document.assert_awaited_once()
    service._storage.upload.assert_awaited_once()
    service._events.publish_submission_created.assert_awaited_once()
    event_payload = service._events.publish_submission_created.await_args.args[0]
    assert event_payload.submission_id == sub_id
    assert event_payload.document_path.startswith("submissions/")


@pytest.mark.anyio
async def test_list_by_student_enriches_submissions():
    """
    Bug corrigé (espace étudiant) : GET /students/me/submissions appelait
    submission_service._submission_repo.list_by_student(...) directement
    depuis le routeur (attribut privé, jamais passé par ce service) —
    renvoyait des Submission ORM brutes, jamais enrichies (exercise_title/
    student_full_name absents alors que SubmissionRead les exige, non
    optionnels) -> échec de validation response_model à chaque appel réel.
    """
    from app.domain.repositories.pagination import CursorPage

    sid = uuid.uuid4()
    eid = uuid.uuid4()
    student_id = uuid.uuid4()

    submission = Submission(
        id=sid, exercise_id=eid, student_id=student_id, attempt_number=1,
        status=SubmissionStatus.EVALUATED, created_at=datetime.now(timezone.utc),
    )
    sub_repo = AsyncMock()
    sub_repo.list_by_student.return_value = CursorPage(items=[submission], next_cursor=None, has_more=False)

    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(id=eid, title="Examen Final")

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = MagicMock(first_name="Alice", last_name="Dupont")

    service = SubmissionService(sub_repo, ex_repo, AsyncMock(), user_repo, AsyncMock())
    result = await service.list_by_student(student_id)

    assert len(result.items) == 1
    assert result.items[0].exercise_title == "Examen Final"
    assert result.items[0].student_full_name == "Alice Dupont"
    sub_repo.list_by_student.assert_awaited_once_with(student_id, cursor=None, limit=50)
