import uuid
import pytest
from unittest.mock import AsyncMock

from app.core.exceptions import (
    ModuleInvalidProgramError,
    ProgramAlreadyExistsError,
    ProgramNotFoundError,
)
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.repositories.pagination import CursorPage
from app.services.module_service import ModuleService
from app.services.program_service import ProgramService
from sqlalchemy.exc import IntegrityError


@pytest.mark.anyio
async def test_program_service_get_by_id_success():
    program_repo = AsyncMock()
    module_repo = AsyncMock()
    group_repo = AsyncMock()

    prog_id = uuid.uuid4()
    mock_program = Program(id=prog_id, name="Informatique", code="INFO")
    program_repo.get_by_id.return_value = mock_program

    service = ProgramService(program_repo, module_repo, group_repo)
    result = await service.get_by_id(prog_id)

    assert result.id == prog_id
    assert result.name == "Informatique"
    assert result.code == "INFO"


@pytest.mark.anyio
async def test_program_service_get_by_id_not_found():
    program_repo = AsyncMock()
    module_repo = AsyncMock()
    group_repo = AsyncMock()

    program_repo.get_by_id.return_value = None

    service = ProgramService(program_repo, module_repo, group_repo)
    with pytest.raises(ProgramNotFoundError):
        await service.get_by_id(uuid.uuid4())


@pytest.mark.anyio
async def test_program_service_create_normalization():
    program_repo = AsyncMock()
    module_repo = AsyncMock()
    group_repo = AsyncMock()

    prog_id = uuid.uuid4()
    program_repo.create.return_value = Program(id=prog_id, name="Maths", code="MATH")

    service = ProgramService(program_repo, module_repo, group_repo)
    result = await service.create(name=" Maths ", code=" math ")

    program_repo.create.assert_called_once_with(name="Maths", code="MATH")
    assert result.code == "MATH"


@pytest.mark.anyio
async def test_module_service_fk_violation():
    module_repo = AsyncMock()
    enrollment_repo = AsyncMock()
    program_repo = AsyncMock()

    fake_orig = Exception("violates foreign key constraint program_id")
    module_repo.create.side_effect = IntegrityError("INSERT statement", params={}, orig=fake_orig)

    service = ModuleService(module_repo, enrollment_repo, program_repo)

    prog_id = uuid.uuid4()
    with pytest.raises(ModuleInvalidProgramError):
        await service.create(program_id=prog_id, name="Algo", code="ALGO1")
