import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_current_admin,
    get_current_user,
    get_module_service,
    get_program_service,
)
from app.domain.models.identity.user import User
from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.academic_schemas import (
    ModuleCreate,
    ModuleRead,
    ModuleUpdate,
    ProgramCreate,
    ProgramRead,
    ProgramUpdate,
)
from app.services.module_service import ModuleService
from app.services.program_service import ProgramService

router = APIRouter(tags=["modules & programs"])


# --- Program Endpoints ---

@router.get("/programs", response_model=CursorPage[ProgramRead])
async def list_programs(
    program_service: Annotated[ProgramService, Depends(get_program_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: str | None = None,
    limit: int = 50,
):
    return await program_service.list_page(cursor=cursor, limit=limit)


@router.get("/programs/{program_id}", response_model=ProgramRead)
async def get_program(
    program_id: uuid.UUID,
    program_service: Annotated[ProgramService, Depends(get_program_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await program_service.get_by_id(program_id)


@router.post("/programs", response_model=ProgramRead, status_code=status.HTTP_201_CREATED)
async def create_program(
    schema: ProgramCreate,
    program_service: Annotated[ProgramService, Depends(get_program_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await program_service.create(name=schema.name, code=schema.code)


@router.patch("/programs/{program_id}", response_model=ProgramRead)
async def update_program(
    program_id: uuid.UUID,
    schema: ProgramUpdate,
    program_service: Annotated[ProgramService, Depends(get_program_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await program_service.update(program_id, name=schema.name, code=schema.code)


@router.delete("/programs/{program_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_program(
    program_id: uuid.UUID,
    program_service: Annotated[ProgramService, Depends(get_program_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    await program_service.delete(program_id)


# --- Module Endpoints ---

@router.get("/programs/{program_id}/modules", response_model=CursorPage[ModuleRead])
async def list_modules_by_program(
    program_id: uuid.UUID,
    module_service: Annotated[ModuleService, Depends(get_module_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: str | None = None,
    limit: int = 50,
):
    return await module_service.list_by_program(program_id=program_id, cursor=cursor, limit=limit)


@router.get("/modules/{module_id}", response_model=ModuleRead)
async def get_module(
    module_id: uuid.UUID,
    module_service: Annotated[ModuleService, Depends(get_module_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await module_service.get_by_id(module_id)


@router.post("/programs/{program_id}/modules", response_model=ModuleRead, status_code=status.HTTP_201_CREATED)
async def create_module(
    program_id: uuid.UUID,
    schema: ModuleCreate,
    module_service: Annotated[ModuleService, Depends(get_module_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await module_service.create(program_id=program_id, name=schema.name, code=schema.code)


@router.patch("/modules/{module_id}", response_model=ModuleRead)
async def update_module(
    module_id: uuid.UUID,
    schema: ModuleUpdate,
    module_service: Annotated[ModuleService, Depends(get_module_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await module_service.update(module_id, name=schema.name, code=schema.code)


@router.delete("/modules/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_module(
    module_id: uuid.UUID,
    module_service: Annotated[ModuleService, Depends(get_module_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    await module_service.delete(module_id)
