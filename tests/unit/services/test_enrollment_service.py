import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import (
    AlreadyEnrolledError,
    EnrollmentNotFoundError,
    StudentNotFoundError,
    StudentSuspendedError,
)
from app.domain.models.academic.enrollment import Enrollment
from app.domain.models.identity.user import AcademicStatus
from app.domain.repositories.pagination import CursorPage
from app.services.enrollment_service import EnrollmentService


def _make_enrollment(
    enrollment_id: uuid.UUID, student_id: uuid.UUID, module_id: uuid.UUID, is_active: bool = True
) -> Enrollment:
    now = datetime.now(timezone.utc)
    return Enrollment(
        id=enrollment_id,
        student_id=student_id,
        module_id=module_id,
        enrolled_at=now,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )


def _make_service(enrollment_repo=None, user_repo=None, module_repo=None) -> EnrollmentService:
    return EnrollmentService(
        enrollment_repo or AsyncMock(),
        user_repo or AsyncMock(),
        module_repo or AsyncMock(),
    )


def _make_student(student_id: uuid.UUID, academic_status: AcademicStatus) -> MagicMock:
    s = MagicMock()
    s.id = student_id
    s.academic_status = academic_status
    s.first_name = "Alice"
    s.last_name = "Dupont"
    return s


def _make_module(module_id: uuid.UUID) -> MagicMock:
    m = MagicMock()
    m.id = module_id
    m.name = "Analyse Numérique"
    return m


@pytest.mark.anyio
async def test_get_by_id_success():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    mid = uuid.uuid4()
    enrollment = _make_enrollment(eid, sid, mid)

    enrollment_repo = AsyncMock()
    enrollment_repo.get_by_id.return_value = enrollment

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid, AcademicStatus.ACTIVE)

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    service = _make_service(enrollment_repo=enrollment_repo, user_repo=user_repo, module_repo=module_repo)
    result = await service.get_by_id(eid)

    assert result.id == eid
    assert result.student_id == sid
    assert result.module_id == mid
    assert result.student_full_name == "Alice Dupont"
    assert result.module_name == "Analyse Numérique"
    assert result.is_active is True
    enrollment_repo.get_by_id.assert_awaited_once_with(eid)


@pytest.mark.anyio
async def test_get_by_id_unknown_references():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    mid = uuid.uuid4()
    enrollment = _make_enrollment(eid, sid, mid)

    enrollment_repo = AsyncMock()
    enrollment_repo.get_by_id.return_value = enrollment

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = None

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = None

    service = _make_service(enrollment_repo=enrollment_repo, user_repo=user_repo, module_repo=module_repo)
    result = await service.get_by_id(eid)

    assert result.student_full_name == "Unknown"
    assert result.module_name == "Unknown"


@pytest.mark.anyio
async def test_get_by_id_not_found():
    eid = uuid.uuid4()
    enrollment_repo = AsyncMock()
    enrollment_repo.get_by_id.return_value = None

    service = _make_service(enrollment_repo=enrollment_repo)
    with pytest.raises(EnrollmentNotFoundError):
        await service.get_by_id(eid)


@pytest.mark.anyio
async def test_enroll_success():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    mid = uuid.uuid4()
    enrollment = _make_enrollment(eid, sid, mid)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid, AcademicStatus.ACTIVE)

    enrollment_repo = AsyncMock()
    enrollment_repo.get_by_student_and_module.return_value = None
    enrollment_repo.create.return_value = enrollment

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    service = _make_service(enrollment_repo=enrollment_repo, user_repo=user_repo, module_repo=module_repo)
    result = await service.enroll(sid, mid)

    assert result.id == eid
    assert result.is_active is True
    enrollment_repo.get_by_student_and_module.assert_awaited_once_with(sid, mid)
    enrollment_repo.create.assert_awaited_once_with(student_id=sid, module_id=mid)


@pytest.mark.anyio
async def test_enroll_student_not_found():
    sid = uuid.uuid4()
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = None

    service = _make_service(user_repo=user_repo)
    with pytest.raises(StudentNotFoundError):
        await service.enroll(sid, uuid.uuid4())


@pytest.mark.anyio
async def test_enroll_student_suspended():
    sid = uuid.uuid4()
    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid, AcademicStatus.SUSPENDED)

    service = _make_service(user_repo=user_repo)
    with pytest.raises(StudentSuspendedError):
        await service.enroll(sid, uuid.uuid4())


@pytest.mark.anyio
async def test_enroll_already_active_raises():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    mid = uuid.uuid4()
    existing = _make_enrollment(eid, sid, mid, is_active=True)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid, AcademicStatus.ACTIVE)

    enrollment_repo = AsyncMock()
    enrollment_repo.get_by_student_and_module.return_value = existing

    service = _make_service(enrollment_repo=enrollment_repo, user_repo=user_repo)
    with pytest.raises(AlreadyEnrolledError):
        await service.enroll(sid, mid)
    enrollment_repo.create.assert_not_awaited()


@pytest.mark.anyio
async def test_enroll_reactivates_inactive():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    mid = uuid.uuid4()
    existing = _make_enrollment(eid, sid, mid, is_active=False)
    reactivated = _make_enrollment(eid, sid, mid, is_active=True)

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid, AcademicStatus.ACTIVE)

    enrollment_repo = AsyncMock()
    enrollment_repo.get_by_student_and_module.return_value = existing
    enrollment_repo.reactivate.return_value = reactivated

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    service = _make_service(enrollment_repo=enrollment_repo, user_repo=user_repo, module_repo=module_repo)
    result = await service.enroll(sid, mid)

    assert result.is_active is True
    enrollment_repo.reactivate.assert_awaited_once_with(eid)
    enrollment_repo.create.assert_not_awaited()


@pytest.mark.anyio
async def test_unenroll_success():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    mid = uuid.uuid4()
    deactivated = _make_enrollment(eid, sid, mid, is_active=False)

    enrollment_repo = AsyncMock()
    enrollment_repo.deactivate.return_value = deactivated

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid, AcademicStatus.ACTIVE)

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    service = _make_service(enrollment_repo=enrollment_repo, user_repo=user_repo, module_repo=module_repo)
    result = await service.unenroll(eid)

    assert result.is_active is False
    enrollment_repo.deactivate.assert_awaited_once_with(eid)


@pytest.mark.anyio
async def test_unenroll_not_found():
    eid = uuid.uuid4()
    enrollment_repo = AsyncMock()
    enrollment_repo.deactivate.return_value = None

    service = _make_service(enrollment_repo=enrollment_repo)
    with pytest.raises(EnrollmentNotFoundError):
        await service.unenroll(eid)


@pytest.mark.anyio
async def test_list_by_student_calls_repository():
    """Le service délègue la pagination au repository et retourne un CursorPage valide."""
    sid = uuid.uuid4()
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    enrollment = _make_enrollment(eid, sid, mid)
    page = CursorPage(items=[enrollment], next_cursor="next", has_more=True)

    enrollment_repo = AsyncMock()
    enrollment_repo.list_by_student.return_value = page

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid, AcademicStatus.ACTIVE)

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    service = _make_service(enrollment_repo=enrollment_repo, user_repo=user_repo, module_repo=module_repo)
    result = await service.list_by_student(sid, cursor="cursor", limit=10)

    assert result.has_more is True
    assert result.next_cursor == "next"
    assert len(result.items) == 1
    assert result.items[0].id == eid
    enrollment_repo.list_by_student.assert_awaited_once_with(sid, cursor="cursor", limit=10)


@pytest.mark.anyio
async def test_list_by_module_calls_repository():
    """Le service délègue la pagination au repository et retourne un CursorPage valide."""
    mid = uuid.uuid4()
    sid = uuid.uuid4()
    eid = uuid.uuid4()
    enrollment = _make_enrollment(eid, sid, mid)
    page = CursorPage(items=[enrollment], next_cursor="next", has_more=True)

    enrollment_repo = AsyncMock()
    enrollment_repo.list_by_module.return_value = page

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid, AcademicStatus.ACTIVE)

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = _make_module(mid)

    service = _make_service(enrollment_repo=enrollment_repo, user_repo=user_repo, module_repo=module_repo)
    result = await service.list_by_module(mid, cursor="cursor", limit=10)

    assert result.has_more is True
    assert result.next_cursor == "next"
    assert len(result.items) == 1
    assert result.items[0].id == eid
    enrollment_repo.list_by_module.assert_awaited_once_with(mid, cursor="cursor", limit=10)