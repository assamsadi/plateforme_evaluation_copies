"""
Service Program — au-delà du simple CRUD, applique 3 règles métier :
1. Normalisation du code (majuscules, sans espace) avant toute écriture.
2. Traduction d'une violation de contrainte unique DB en erreur métier
   claire (ProgramAlreadyExistsError), plutôt que de laisser remonter une
   exception SQL brute jusqu'au client API. Le rollback est géré par le
   middleware FastAPI (UoW dans get_db) — le service ne possède plus la
   session directement.
3. Interdiction de suppression si des Module ou Group actifs en dépendent
   — évite de casser silencieusement toute la hiérarchie en dessous
   (Course, Exercise, Enrollment...).
"""
import uuid
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ProgramAlreadyExistsError,
    ProgramHasActiveDependenciesError,
    ProgramNotFoundError,
)
from app.domain.repositories.group_repository import GroupRepositoryProtocol
from app.domain.repositories.module_repository import ModuleRepositoryProtocol
from app.domain.repositories.pagination import CursorPage
from app.domain.repositories.program_repository import ProgramRepositoryProtocol
from app.domain.schemas.academic_schemas import ProgramRead


def _normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


class ProgramServiceProtocol(Protocol):
    async def get_by_id(self, program_id: uuid.UUID) -> ProgramRead: ...
    async def list_page(self, cursor: str | None, limit: int) -> CursorPage[ProgramRead]: ...
    async def create(self, name: str, code: str) -> ProgramRead: ...
    async def update(self, program_id: uuid.UUID, name: str, code: str) -> ProgramRead: ...
    async def delete(self, program_id: uuid.UUID) -> None: ...


class ProgramService:
    def __init__(
        self,
        program_repository: ProgramRepositoryProtocol,
        module_repository: ModuleRepositoryProtocol,
        group_repository: GroupRepositoryProtocol,
    ) -> None:
        self._programs = program_repository
        self._modules = module_repository
        self._groups = group_repository

    async def get_by_id(self, program_id: uuid.UUID) -> ProgramRead:
        program = await self._programs.get_by_id(program_id)
        if program is None:
            raise ProgramNotFoundError(program_id)
        return ProgramRead.model_validate(program)

    async def list_page(self, cursor: str | None = None, limit: int = 50) -> CursorPage[ProgramRead]:
        page = await self._programs.list_page(cursor=cursor, limit=limit)
        items = [ProgramRead.model_validate(p) for p in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def create(self, name: str, code: str) -> ProgramRead:
        normalized_code = _normalize_code(code)
        try:
            program = await self._programs.create(name=name.strip(), code=normalized_code)
            return ProgramRead.model_validate(program)
        except IntegrityError as e:
            raise ProgramAlreadyExistsError(name, normalized_code) from e

    async def update(self, program_id: uuid.UUID, name: str, code: str) -> ProgramRead:
        raw_program = await self._programs.get_by_id(program_id)
        if raw_program is None:
            raise ProgramNotFoundError(program_id)
        normalized_code = _normalize_code(code)
        try:
            updated = await self._programs.update(program_id, name.strip(), normalized_code)
        except IntegrityError as e:
            raise ProgramAlreadyExistsError(name, normalized_code) from e
        assert updated is not None  # garanti par le get_by_id ci-dessus
        return ProgramRead.model_validate(updated)

    async def delete(self, program_id: uuid.UUID) -> None:
        raw_program = await self._programs.get_by_id(program_id)
        if raw_program is None:
            raise ProgramNotFoundError(program_id)

        modules_page = await self._modules.list_by_program(program_id, limit=1)
        groups_page = await self._groups.list_by_program(program_id, limit=1)

        if modules_page.items or groups_page.items:
            # On ne charge qu'1 ligne (limit=1) pour savoir s'il EXISTE une
            # dépendance, sans jamais charger tous les modules/groupes
            # juste pour un comptage — cohérent avec les optimisations
            # déjà faites côté repositories (EXISTS plutôt que COUNT
            # complet quand seule la présence importe).
            raise ProgramHasActiveDependenciesError(
                program_id,
                module_count=len(modules_page.items),
                group_count=len(groups_page.items),
            )

        await self._programs.delete(program_id)
