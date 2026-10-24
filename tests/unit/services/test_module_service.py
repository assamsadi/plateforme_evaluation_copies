import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ModuleAlreadyExistsError,
    ModuleHasActiveDependenciesError,
    ModuleInvalidProgramError,
    ModuleNotFoundError,
)
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.repositories.pagination import CursorPage
from app.services.module_service import ModuleService


def _make_module(module_id: uuid.UUID, program_id: uuid.UUID, name: str, code: str) -> Module:
    now = datetime.now(timezone.utc)
    return Module(
        id=module_id, program_id=program_id, name=name, code=code, created_at=now, updated_at=now
    )


def _make_program(program_id: uuid.UUID, name: str, code: str) -> Program:
    now = datetime.now(timezone.utc)
    return Program(id=program_id, name=name, code=code, created_at=now, updated_at=now)


def _make_service(module_repo=None, enrollment_repo=None, program_repo=None) -> ModuleService:
    return ModuleService(
        module_repo or AsyncMock(),
        enrollment_repo or AsyncMock(),
        program_repo or AsyncMock(),
    )


def _fk_integrity_error() -> IntegrityError:
    return IntegrityError("stmt", {}, orig=Exception("violates foreign key constraint"))


def _unique_integrity_error() -> IntegrityError:
    return IntegrityError("stmt", {}, orig=Exception("duplicate key value"))


@pytest.mark.anyio
async def test_get_by_id_success():
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    module = _make_module(mid, pid, "Analyse Numérique", "AN")
    program = _make_program(pid, "Informatique", "INFO")

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = module

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    service = _make_service(module_repo=module_repo, program_repo=program_repo)
    result = await service.get_by_id(mid)

    assert result.id == mid
    assert result.name == "Analyse Numérique"
    assert result.code == "AN"
    assert result.program_id == pid
    assert result.program_name == "Informatique"
    module_repo.get_by_id.assert_awaited_once_with(mid)
    program_repo.get_by_id.assert_awaited_once_with(pid)


@pytest.mark.anyio
async def test_get_by_id_program_unknown():
    """Quand le programme parent est introuvable, program_name = 'Unknown'."""
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    module = _make_module(mid, pid, "Analyse Numérique", "AN")

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = module

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = None

    service = _make_service(module_repo=module_repo, program_repo=program_repo)
    result = await service.get_by_id(mid)

    assert result.program_name == "Unknown"


@pytest.mark.anyio
async def test_get_by_id_not_found():
    mid = uuid.uuid4()
    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = None

    service = _make_service(module_repo=module_repo)
    with pytest.raises(ModuleNotFoundError):
        await service.get_by_id(mid)


@pytest.mark.anyio
async def test_list_by_program_calls_repository():
    """Le service délègue la pagination au repository et retourne un CursorPage valide."""
    pid = uuid.uuid4()
    mid = uuid.uuid4()
    module = _make_module(mid, pid, "Analyse Numérique", "AN")
    program = _make_program(pid, "Informatique", "INFO")
    page = CursorPage(items=[module], next_cursor="next", has_more=True)

    module_repo = AsyncMock()
    module_repo.list_by_program.return_value = page

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    service = _make_service(module_repo=module_repo, program_repo=program_repo)
    result = await service.list_by_program(pid, cursor="cursor", limit=10)

    assert result.has_more is True
    assert result.next_cursor == "next"
    assert len(result.items) == 1
    assert result.items[0].id == mid
    module_repo.list_by_program.assert_awaited_once_with(pid, cursor="cursor", limit=10)


@pytest.mark.anyio
async def test_create_success_normalizes_code():
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    module = _make_module(mid, pid, "Analyse Numérique", "AN")
    program = _make_program(pid, "Informatique", "INFO")

    module_repo = AsyncMock()
    module_repo.create.return_value = module

    program_repo = AsyncMock()
    program_repo.get_by_id.return_value = program

    service = _make_service(module_repo=module_repo, program_repo=program_repo)
    result = await service.create(pid, name="  Analyse Numérique  ", code="  an ")

    assert result.code == "AN"
    assert result.program_name == "Informatique"
    module_repo.create.assert_awaited_once_with(program_id=pid, name="Analyse Numérique", code="AN")


@pytest.mark.anyio
async def test_create_fk_violation_raises_module_invalid_program():
    pid = uuid.uuid4()
    module_repo = AsyncMock()
    module_repo.create.side_effect = _fk_integrity_error()

    service = _make_service(module_repo=module_repo)
    with pytest.raises(ModuleInvalidProgramError):
        await service.create(pid, name="Analyse Numérique", code="AN")


@pytest.mark.anyio
async def test_create_unique_violation_raises_module_already_exists():
    pid = uuid.uuid4()
    module_repo = AsyncMock()
    module_repo.create.side_effect = _unique_integrity_error()

    service = _make_service(module_repo=module_repo)
    with pytest.raises(ModuleAlreadyExistsError):
        await service.create(pid, name="Analyse Numérique", code="AN")


@pytest.mark.anyio
async def test_delete_success():
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    module = _make_module(mid, pid, "Analyse Numérique", "AN")

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = module

    enrollment_repo = AsyncMock()
    enrollment_repo.list_by_module.return_value = CursorPage(items=[], next_cursor=None, has_more=False)

    service = _make_service(module_repo=module_repo, enrollment_repo=enrollment_repo)
    await service.delete(mid)

    module_repo.delete.assert_awaited_once_with(mid)
    enrollment_repo.list_by_module.assert_awaited_once_with(mid, limit=1)


@pytest.mark.anyio
async def test_delete_not_found():
    mid = uuid.uuid4()
    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = None

    service = _make_service(module_repo=module_repo)
    with pytest.raises(ModuleNotFoundError):
        await service.delete(mid)
    module_repo.delete.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_with_active_enrollments_raises():
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    module = _make_module(mid, pid, "Analyse Numérique", "AN")

    module_repo = AsyncMock()
    module_repo.get_by_id.return_value = module

    enrollment_repo = AsyncMock()
    enrollment_repo.list_by_module.return_value = CursorPage(
        items=[MagicMock()], next_cursor=None, has_more=True
    )

    service = _make_service(module_repo=module_repo, enrollment_repo=enrollment_repo)
    with pytest.raises(ModuleHasActiveDependenciesError):
        await service.delete(mid)
    module_repo.delete.assert_not_awaited()