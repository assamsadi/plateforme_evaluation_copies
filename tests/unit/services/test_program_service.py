import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ProgramAlreadyExistsError,
    ProgramNotFoundError,
)
from app.domain.models.academic.program import Program
from app.domain.repositories.pagination import CursorPage
from app.services.program_service import ProgramService


def _make_program(program_id: uuid.UUID, name: str, code: str) -> Program:
    now = datetime.now(timezone.utc)
    return Program(id=program_id, name=name, code=code, created_at=now, updated_at=now)


def _make_service(program_repo=None, module_repo=None, group_repo=None) -> ProgramService:
    return ProgramService(
        program_repo or AsyncMock(),
        module_repo or AsyncMock(),
        group_repo or AsyncMock(),
    )


@pytest.mark.anyio
async def test_get_by_id_success():
    pid = uuid.uuid4()
    program = _make_program(pid, "Informatique", "INFO")
    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    service = _make_service(program_repo=program_repo)
    result = await service.get_by_id(pid)

    assert result.id == pid
    assert result.name == "Informatique"
    assert result.code == "INFO"
    program_repo.get_by_id.assert_awaited_once_with(pid)


@pytest.mark.anyio
async def test_get_by_id_not_found():
    pid = uuid.uuid4()
    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = None

    service = _make_service(program_repo=program_repo)
    with pytest.raises(ProgramNotFoundError):
        await service.get_by_id(pid)


@pytest.mark.anyio
async def test_list_page_calls_repository():
    """Le service délègue la pagination au repository et retourne un CursorPage valide."""
    pid1 = uuid.uuid4()
    pid2 = uuid.uuid4()
    programs = [_make_program(pid1, "Informatique", "INFO"), _make_program(pid2, "Génie Civil", "GC")]
    page = CursorPage(items=programs, next_cursor="next-cursor", has_more=True)

    program_repo = AsyncMock()
    program_repo.list_page.return_value = page

    service = _make_service(program_repo=program_repo)
    result = await service.list_page(cursor="cursor", limit=10)

    assert result.has_more is True
    assert result.next_cursor == "next-cursor"
    assert len(result.items) == 2
    assert result.items[0].id == pid1
    program_repo.list_page.assert_awaited_once_with(cursor="cursor", limit=10)


@pytest.mark.anyio
async def test_create_success_normalizes_code():
    pid = uuid.uuid4()
    program = _make_program(pid, "Informatique", "INFO")
    program_repo = AsyncMock()
    program_repo.create.return_value = program

    service = _make_service(program_repo=program_repo)
    result = await service.create(name="  Informatique  ", code="  info ")

    assert result.id == pid
    assert result.code == "INFO"
    # Le code est normalisé (strip + upper + sans espace) avant écriture
    program_repo.create.assert_awaited_once_with(name="Informatique", code="INFO")


@pytest.mark.anyio
async def test_create_integrity_error_raises_program_already_exists():
    program_repo = AsyncMock()
    program_repo.create.side_effect = IntegrityError("stmt", {}, orig=Exception())

    service = _make_service(program_repo=program_repo)
    with pytest.raises(ProgramAlreadyExistsError):
        await service.create(name="Informatique", code="INFO")


@pytest.mark.anyio
async def test_update_success():
    pid = uuid.uuid4()
    existing = _make_program(pid, "Informatique", "INFO")
    updated = _make_program(pid, "Informatique Appliquée", "INFOA")

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = existing
    program_repo.update.return_value = updated

    service = _make_service(program_repo=program_repo)
    result = await service.update(pid, name="  Informatique Appliquée  ", code="  infoa ")

    assert result.name == "Informatique Appliquée"
    assert result.code == "INFOA"
    program_repo.update.assert_awaited_once_with(pid, "Informatique Appliquée", "INFOA")


@pytest.mark.anyio
async def test_update_not_found():
    pid = uuid.uuid4()
    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = None

    service = _make_service(program_repo=program_repo)
    with pytest.raises(ProgramNotFoundError):
        await service.update(pid, name="X", code="X")


@pytest.mark.anyio
async def test_update_integrity_error_raises_program_already_exists():
    pid = uuid.uuid4()
    existing = _make_program(pid, "Informatique", "INFO")

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = existing
    program_repo.update.side_effect = IntegrityError("stmt", {}, orig=Exception())

    service = _make_service(program_repo=program_repo)
    with pytest.raises(ProgramAlreadyExistsError):
        await service.update(pid, name="Informatique", code="INFO")


@pytest.mark.anyio
async def test_delete_success():
    pid = uuid.uuid4()
    program = _make_program(pid, "Informatique", "INFO")

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    module_repo = AsyncMock()
    module_repo.list_by_program.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    group_repo = AsyncMock()
    group_repo.list_by_program.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    service = _make_service(program_repo=program_repo, module_repo=module_repo, group_repo=group_repo)
    await service.delete(pid)

    program_repo.delete.assert_awaited_once_with(pid)
    module_repo.list_by_program.assert_awaited_once_with(pid, limit=1)
    group_repo.list_by_program.assert_awaited_once_with(pid, limit=1)


@pytest.mark.anyio
async def test_delete_not_found():
    pid = uuid.uuid4()
    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = None

    service = _make_service(program_repo=program_repo)
    with pytest.raises(ProgramNotFoundError):
        await service.delete(pid)
    program_repo.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_with_active_modules_does_not_delete():
    """La suppression est refusée quand des modules dépendent du programme."""
    from app.core.exceptions import ProgramHasActiveDependenciesError
    pid = uuid.uuid4()
    program = _make_program(pid, "Informatique", "INFO")

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    module_repo = AsyncMock()
    module_repo.list_by_program.return_value = CursorPage(
        items=[MagicMock()], next_cursor=None, has_more=True
    )

    group_repo = AsyncMock()
    group_repo.list_by_program.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    service = _make_service(program_repo=program_repo, module_repo=module_repo, group_repo=group_repo)
    with pytest.raises(ProgramHasActiveDependenciesError):
        await service.delete(pid)
    program_repo.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_with_active_groups_does_not_delete():
    """La suppression est refusée quand des groupes dépendent du programme."""
    from app.core.exceptions import ProgramHasActiveDependenciesError
    pid = uuid.uuid4()
    program = _make_program(pid, "Informatique", "INFO")

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    module_repo = AsyncMock()
    module_repo.list_by_program.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    group_repo = AsyncMock()
    group_repo.list_by_program.return_value = CursorPage(
        items=[MagicMock()], next_cursor=None, has_more=True
    )

    service = _make_service(program_repo=program_repo, module_repo=module_repo, group_repo=group_repo)
    with pytest.raises(ProgramHasActiveDependenciesError):
        await service.delete(pid)
    program_repo.delete.assert_not_awaited()
