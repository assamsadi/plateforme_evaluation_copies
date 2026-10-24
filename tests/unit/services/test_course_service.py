import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import (
    CourseAlreadyExistsError,
    CourseHasActiveExercisesError,
    CourseInvalidReferenceError,
    CourseNotFoundError,
    NotCourseOwnerError,
)
from app.domain.models.academic.course import Course
from app.domain.models.identity.user import AcademicStatus, UserRole
from app.domain.repositories.pagination import CursorPage
from app.services.course_service import CourseService


def _make_course(
    course_id: uuid.UUID, module_id: uuid.UUID, professor_id: uuid.UUID, group_id: uuid.UUID
) -> Course:
    now = datetime.now(timezone.utc)
    return Course(
        id=course_id,
        module_id=module_id,
        professor_user_id=professor_id,
        group_id=group_id,
        semester="S1-2025",
        created_at=now,
        updated_at=now,
    )


def _make_service(course_repo=None, module_repo=None, user_repo=None, group_repo=None, exercise_repo=None) -> CourseService:
    return CourseService(
        course_repo or AsyncMock(),
        module_repo or AsyncMock(),
        user_repo or AsyncMock(),
        group_repo or AsyncMock(),
        exercise_repo or AsyncMock(),
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


def _make_group(group_id: uuid.UUID) -> MagicMock:
    g = MagicMock()
    g.id = group_id
    g.label = "G1"
    return g


def _make_student(student_id: uuid.UUID, group_id: uuid.UUID) -> MagicMock:
    s = MagicMock()
    s.id = student_id
    s.email = "etudiant@example.com"
    s.role = UserRole.STUDENT
    s.first_name = "Jean"
    s.last_name = "Martin"
    s.is_active = True
    s.student_number = "E12345"
    s.group_id = group_id
    s.enrollment_year = 2025
    s.academic_status = AcademicStatus.ACTIVE
    s.level = "L3"
    return s


@pytest.mark.anyio
async def test_get_by_id_success():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = _make_group(gid)

    service = _make_service(
        course_repo=course_repo, module_repo=module_repo, user_repo=user_repo, group_repo=group_repo
    )
    result = await service.get_by_id(cid)

    assert result.id == cid
    assert result.module_name == "Analyse Numérique"
    assert result.professor_full_name == "Alice Dupont"
    assert result.group_label == "G1"
    course_repo.get_by_id.assert_awaited_once_with(cid)


@pytest.mark.anyio
async def test_get_by_id_unknown_references():
    """Quand une référence est introuvable, les champs aplatis = 'Unknown'."""
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = None

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = None

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = None

    service = _make_service(
        course_repo=course_repo, module_repo=module_repo, user_repo=user_repo, group_repo=group_repo
    )
    result = await service.get_by_id(cid)

    assert result.module_name == "Unknown"
    assert result.professor_full_name == "Unknown"
    assert result.group_label == "Unknown"


@pytest.mark.anyio
async def test_get_by_id_not_found():
    cid = uuid.uuid4()
    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = None

    service = _make_service(course_repo=course_repo)
    with pytest.raises(CourseNotFoundError):
        await service.get_by_id(cid)


@pytest.mark.anyio
async def test_create_success():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = _make_group(gid)

    course_repo = AsyncMock()
    course_repo.create.return_value = course

    service = _make_service(
        course_repo=course_repo, module_repo=module_repo, user_repo=user_repo, group_repo=group_repo
    )
    result = await service.create(mid, pid, gid, "S1-2025")

    assert result.id == cid
    assert result.module_name == "Analyse Numérique"
    assert result.professor_full_name == "Alice Dupont"
    assert result.group_label == "G1"
    course_repo.create.assert_awaited_once_with(
        module_id=mid, professor_user_id=pid, group_id=gid, semester="S1-2025"
    )


@pytest.mark.anyio
async def test_list_by_professor_success():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = _make_group(gid)

    course_repo = AsyncMock()
    course_repo.list_by_professor.return_value = CursorPage(items=[course], next_cursor=None, has_more=False)

    service = _make_service(
        course_repo=course_repo, module_repo=module_repo, user_repo=user_repo, group_repo=group_repo
    )
    result = await service.list_by_professor(pid)

    assert len(result.items) == 1
    assert result.items[0].id == cid
    assert result.items[0].module_name == "Analyse Numérique"
    course_repo.list_by_professor.assert_awaited_once_with(pid, cursor=None, limit=50)


@pytest.mark.anyio
async def test_create_module_not_found():
    mid = uuid.uuid4()
    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = None

    service = _make_service(module_repo=module_repo)
    with pytest.raises(CourseInvalidReferenceError) as exc_info:
        await service.create(mid, uuid.uuid4(), uuid.uuid4(), "S1-2025")
    assert "module_id" in str(exc_info.value)


@pytest.mark.anyio
async def test_create_professor_not_found():
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = None

    service = _make_service(module_repo=module_repo, user_repo=user_repo)
    with pytest.raises(CourseInvalidReferenceError) as exc_info:
        await service.create(mid, pid, uuid.uuid4(), "S1-2025")
    assert "professor_user_id" in str(exc_info.value)


@pytest.mark.anyio
async def test_create_group_not_found():
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = None

    service = _make_service(module_repo=module_repo, user_repo=user_repo, group_repo=group_repo)
    with pytest.raises(CourseInvalidReferenceError) as exc_info:
        await service.create(mid, pid, gid, "S1-2025")
    assert "group_id" in str(exc_info.value)


@pytest.mark.anyio
async def test_delete_success():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course

    exercise_repo = AsyncMock()
    exercise_repo.list_by_course.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    service = _make_service(course_repo=course_repo, exercise_repo=exercise_repo)
    await service.delete(cid, pid)

    course_repo.delete.assert_awaited_once_with(cid)
    exercise_repo.list_by_course.assert_awaited_once_with(cid, limit=1)


@pytest.mark.anyio
async def test_delete_not_found():
    cid = uuid.uuid4()
    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = None

    service = _make_service(course_repo=course_repo)
    with pytest.raises(CourseNotFoundError):
        await service.delete(cid, uuid.uuid4())
    course_repo.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_with_active_exercises_raises():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course

    exercise_repo = AsyncMock()
    exercise_repo.list_by_course.return_value = CursorPage(
        items=[MagicMock()], next_cursor=None, has_more=True
    )

    service = _make_service(course_repo=course_repo, exercise_repo=exercise_repo)
    with pytest.raises(CourseHasActiveExercisesError):
        await service.delete(cid, pid)
    course_repo.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_rejects_non_owner():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course

    service = _make_service(course_repo=course_repo)
    with pytest.raises(NotCourseOwnerError):
        await service.delete(cid, uuid.uuid4())
    course_repo.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_update_semester_success():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)
    updated_course = _make_course(cid, mid, pid, gid)
    updated_course.semester = "S2-2025"

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course
    course_repo.get_by_unique_key.return_value = None
    course_repo.update_semester.return_value = updated_course

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)
    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = _make_group(gid)

    service = _make_service(
        course_repo=course_repo, module_repo=module_repo, user_repo=user_repo, group_repo=group_repo
    )
    result = await service.update_semester(cid, pid, "S2-2025")

    assert result.semester == "S2-2025"
    course_repo.get_by_unique_key.assert_awaited_once_with(mid, gid, "S2-2025")
    course_repo.update_semester.assert_awaited_once_with(cid, "S2-2025")


@pytest.mark.anyio
async def test_update_semester_rejects_non_owner():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course

    service = _make_service(course_repo=course_repo)
    with pytest.raises(NotCourseOwnerError):
        await service.update_semester(cid, uuid.uuid4(), "S2-2025")
    course_repo.update_semester.assert_not_awaited()


@pytest.mark.anyio
async def test_update_semester_rejects_conflict():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)
    conflicting_course = _make_course(uuid.uuid4(), mid, pid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course
    course_repo.get_by_unique_key.return_value = conflicting_course

    service = _make_service(course_repo=course_repo)
    with pytest.raises(CourseAlreadyExistsError):
        await service.update_semester(cid, pid, "S2-2025")
    course_repo.update_semester.assert_not_awaited()


@pytest.mark.anyio
async def test_list_students_success():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    sid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)
    student = _make_student(sid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course

    user_repo = AsyncMock()
    user_repo.list_students_by_group.return_value = CursorPage(
        items=[student], next_cursor=None, has_more=False
    )

    service = _make_service(course_repo=course_repo, user_repo=user_repo)
    result = await service.list_students(cid, pid)

    assert len(result) == 1
    assert result[0].id == sid
    assert result[0].student_number == "E12345"
    user_repo.list_students_by_group.assert_awaited_once_with(gid, limit=200)


@pytest.mark.anyio
async def test_list_students_not_found():
    cid = uuid.uuid4()
    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = None

    service = _make_service(course_repo=course_repo)
    with pytest.raises(CourseNotFoundError):
        await service.list_students(cid, uuid.uuid4())


@pytest.mark.anyio
async def test_list_students_rejects_non_owner():
    cid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    course = _make_course(cid, mid, pid, gid)

    course_repo = AsyncMock()
    course_repo.get_by_id.return_value = course

    user_repo = AsyncMock()

    service = _make_service(course_repo=course_repo, user_repo=user_repo)
    with pytest.raises(NotCourseOwnerError):
        await service.list_students(cid, uuid.uuid4())
    user_repo.list_students_by_group.assert_not_awaited()