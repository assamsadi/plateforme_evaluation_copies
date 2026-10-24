import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    GroupAlreadyExistsError,
    GroupHasActiveDependenciesError,
    GroupNotFoundError,
    InvalidAcademicYearFormatError,
)
from app.domain.models.academic.group import Group
from app.domain.models.academic.program import Program
from app.domain.repositories.pagination import CursorPage
from app.services.group_service import GroupService


def _make_group(group_id: uuid.UUID, program_id: uuid.UUID, label: str, academic_year: str) -> Group:
    now = datetime.now(timezone.utc)
    return Group(
        id=group_id,
        program_id=program_id,
        label=label,
        academic_year=academic_year,
        created_at=now,
        updated_at=now,
    )


def _make_program(program_id: uuid.UUID, name: str, code: str) -> Program:
    now = datetime.now(timezone.utc)
    return Program(id=program_id, name=name, code=code, created_at=now, updated_at=now)


def _make_service(group_repo=None, user_repo=None, course_repo=None, program_repo=None) -> GroupService:
    return GroupService(
        group_repo or AsyncMock(),
        user_repo or AsyncMock(),
        course_repo or AsyncMock(),
        program_repo or AsyncMock(),
    )


@pytest.mark.anyio
async def test_get_by_id_success():
    gid = uuid.uuid4()
    pid = uuid.uuid4()
    group = _make_group(gid, pid, "TD1", "2025-2026")
    program = _make_program(pid, "Informatique", "INFO")

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = group

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    service = _make_service(group_repo=group_repo, program_repo=program_repo)
    result = await service.get_by_id(gid)

    assert result.id == gid
    assert result.label == "TD1"
    assert result.academic_year == "2025-2026"
    assert result.program_id == pid
    assert result.program_name == "Informatique"
    group_repo.get_by_id.assert_awaited_once_with(gid)


@pytest.mark.anyio
async def test_get_by_id_program_unknown():
    gid = uuid.uuid4()
    pid = uuid.uuid4()
    group = _make_group(gid, pid, "TD1", "2025-2026")

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = group

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = None

    service = _make_service(group_repo=group_repo, program_repo=program_repo)
    result = await service.get_by_id(gid)

    assert result.program_name == "Unknown"


@pytest.mark.anyio
async def test_get_by_id_not_found():
    gid = uuid.uuid4()
    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = None

    service = _make_service(group_repo=group_repo)
    with pytest.raises(GroupNotFoundError):
        await service.get_by_id(gid)


@pytest.mark.anyio
async def test_list_by_program_calls_repository():
    """Le service délègue la pagination au repository et retourne un CursorPage valide."""
    pid = uuid.uuid4()
    gid = uuid.uuid4()
    group = _make_group(gid, pid, "TD1", "2025-2026")
    program = _make_program(pid, "Informatique", "INFO")
    page = CursorPage(items=[group], next_cursor="next", has_more=True)

    group_repo = AsyncMock()
    group_repo.list_by_program.return_value = page

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    service = _make_service(group_repo=group_repo, program_repo=program_repo)
    result = await service.list_by_program(pid, cursor="cursor", limit=10)

    assert result.has_more is True
    assert result.next_cursor == "next"
    assert len(result.items) == 1
    assert result.items[0].id == gid
    group_repo.list_by_program.assert_awaited_once_with(pid, limit=10, cursor="cursor")


@pytest.mark.anyio
async def test_create_success():
    gid = uuid.uuid4()
    pid = uuid.uuid4()
    group = _make_group(gid, pid, "TD1", "2025-2026")
    program = _make_program(pid, "Informatique", "INFO")

    group_repo = AsyncMock()
    group_repo.create.return_value = group

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    service = _make_service(group_repo=group_repo, program_repo=program_repo)
    result = await service.create(pid, label="  TD1  ", academic_year=" 2025-2026 ")

    assert result.label == "TD1"
    assert result.academic_year == "2025-2026"
    assert result.program_name == "Informatique"
    group_repo.create.assert_awaited_once_with(
        program_id=pid, label="TD1", academic_year="2025-2026"
    )


@pytest.mark.anyio
async def test_create_invalid_year_format():
    pid = uuid.uuid4()
    service = _make_service()
    with pytest.raises(InvalidAcademicYearFormatError):
        await service.create(pid, label="TD1", academic_year="2025")


@pytest.mark.anyio
async def test_create_invalid_year_not_consecutive():
    pid = uuid.uuid4()
    service = _make_service()
    with pytest.raises(InvalidAcademicYearFormatError):
        await service.create(pid, label="TD1", academic_year="2025-2027")


@pytest.mark.anyio
async def test_create_integrity_error_raises_group_already_exists():
    pid = uuid.uuid4()
    group_repo = AsyncMock()
    group_repo.create.side_effect = IntegrityError("stmt", {}, orig=Exception())

    service = _make_service(group_repo=group_repo)
    with pytest.raises(GroupAlreadyExistsError):
        await service.create(pid, label="TD1", academic_year="2025-2026")


@pytest.mark.anyio
async def test_delete_success():
    gid = uuid.uuid4()
    pid = uuid.uuid4()
    group = _make_group(gid, pid, "TD1", "2025-2026")

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = group

    user_repo = AsyncMock()
    user_repo.list_students_by_group.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    course_repo = AsyncMock()
    course_repo.list_by_group.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    service = _make_service(group_repo=group_repo, user_repo=user_repo, course_repo=course_repo)
    await service.delete(gid)

    group_repo.delete.assert_awaited_once_with(gid)
    user_repo.list_students_by_group.assert_awaited_once_with(gid, limit=1)
    course_repo.list_by_group.assert_awaited_once_with(gid, limit=1)


@pytest.mark.anyio
async def test_delete_not_found():
    gid = uuid.uuid4()
    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = None

    service = _make_service(group_repo=group_repo)
    with pytest.raises(GroupNotFoundError):
        await service.delete(gid)
    group_repo.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_with_active_students_raises():
    gid = uuid.uuid4()
    pid = uuid.uuid4()
    group = _make_group(gid, pid, "TD1", "2025-2026")

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = group

    user_repo = AsyncMock()
    user_repo.list_students_by_group.return_value = CursorPage(
        items=[MagicMock()], next_cursor=None, has_more=True
    )

    course_repo = AsyncMock()
    course_repo.list_by_group.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    service = _make_service(group_repo=group_repo, user_repo=user_repo, course_repo=course_repo)
    with pytest.raises(GroupHasActiveDependenciesError):
        await service.delete(gid)
    group_repo.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_with_active_courses_raises():
    gid = uuid.uuid4()
    pid = uuid.uuid4()
    group = _make_group(gid, pid, "TD1", "2025-2026")

    group_repo = AsyncMock()
    group_repo.get_by_id.return_value = group

    user_repo = AsyncMock()
    user_repo.list_students_by_group.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    course_repo = AsyncMock()
    course_repo.list_by_group.return_value = CursorPage(
        items=[MagicMock()], next_cursor=None, has_more=True
    )

    service = _make_service(group_repo=group_repo, user_repo=user_repo, course_repo=course_repo)
    with pytest.raises(GroupHasActiveDependenciesError):
        await service.delete(gid)
    group_repo.delete.assert_not_awaited()