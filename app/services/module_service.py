"""
Service Module — règles métier :
1. Unicité (name par program, code global) : violation DB traduite en
   erreur métier claire (ModuleAlreadyExistsError).
2. Existence du Program parent : PAS de vérification préalable explicite
   (décision actée) — la contrainte FK de PostgreSQL fait le travail ;
   le service intercepte l'IntegrityError résultante et la traduit en
   ModuleInvalidProgramError plutôt que de laisser remonter l'erreur SQL
   brute, sans payer le coût d'une requête de vérification en plus.
3. Interdiction de suppression si Exercise ou Enrollment actifs en
   dépendent — même logique que ProgramService.
"""
import uuid
from typing import Protocol

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    ModuleAlreadyExistsError,
    ModuleHasActiveDependenciesError,
    ModuleInvalidProgramError,
    ModuleNotFoundError,
)
from app.domain.models.academic.module import Module
from app.domain.repositories.enrollment_repository import EnrollmentRepositoryProtocol
from app.domain.repositories.module_repository import ModuleRepositoryProtocol
from app.domain.repositories.pagination import CursorPage
from app.domain.repositories.program_repository import ProgramRepositoryProtocol
from app.domain.schemas.academic_schemas import ModuleRead


def _normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def _is_foreign_key_violation(error: IntegrityError) -> bool:
    """
    Distingue une violation de contrainte unique d'une violation de FK à
    partir du message d'erreur PostgreSQL (asyncpg/psycopg) — pas de
    façon 100 % portable entre bases, mais suffisant ici (PostgreSQL
    uniquement dans ce projet). Évite une requête de vérification
    préalable coûteuse pour un cas qui reste rare (mauvais program_id).
    """
    message = str(error.orig).lower()
    return "foreign key" in message or "violates foreign key constraint" in message


class ModuleServiceProtocol(Protocol):
    async def get_by_id(self, module_id: uuid.UUID) -> ModuleRead: ...
    async def list_by_program(
        self, program_id: uuid.UUID, cursor: str | None, limit: int
    ) -> CursorPage[ModuleRead]: ...
    async def create(self, program_id: uuid.UUID, name: str, code: str) -> ModuleRead: ...
    async def update(self, module_id: uuid.UUID, name: str, code: str) -> ModuleRead: ...
    async def delete(self, module_id: uuid.UUID) -> None: ...


class ModuleService:
    def __init__(
        self,
        module_repository: ModuleRepositoryProtocol,
        enrollment_repository: EnrollmentRepositoryProtocol,
        program_repository: ProgramRepositoryProtocol,
    ) -> None:
        self._modules = module_repository
        self._enrollments = enrollment_repository
        self._programs = program_repository

    async def _to_module_read(self, module: Module) -> ModuleRead:
        """Peuple module.program_name et convertit en ModuleRead."""
        program = await self._programs.get_by_id(module.program_id)
        module.program_name = program.name if program else "Unknown"
        return ModuleRead.model_validate(module)

    async def get_by_id(self, module_id: uuid.UUID) -> ModuleRead:
        module = await self._modules.get_by_id(module_id)
        if module is None:
            raise ModuleNotFoundError(module_id)
        return await self._to_module_read(module)

    async def list_by_program(
        self, program_id: uuid.UUID, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[ModuleRead]:
        page = await self._modules.list_by_program(program_id, cursor=cursor, limit=limit)
        items = [await self._to_module_read(m) for m in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def create(self, program_id: uuid.UUID, name: str, code: str) -> ModuleRead:
        normalized_code = _normalize_code(code)
        try:
            module = await self._modules.create(
                program_id=program_id, name=name.strip(), code=normalized_code
            )
            return await self._to_module_read(module)
        except IntegrityError as e:
            if _is_foreign_key_violation(e):
                raise ModuleInvalidProgramError(program_id) from e
            raise ModuleAlreadyExistsError(name, normalized_code) from e

    async def update(self, module_id: uuid.UUID, name: str, code: str) -> ModuleRead:
        raw_module = await self._modules.get_by_id(module_id)
        if raw_module is None:
            raise ModuleNotFoundError(module_id)
        normalized_code = _normalize_code(code)
        try:
            updated = await self._modules.update(module_id, name.strip(), normalized_code)
        except IntegrityError as e:
            raise ModuleAlreadyExistsError(name, normalized_code) from e
        assert updated is not None  # garanti par le get_by_id ci-dessus
        return await self._to_module_read(updated)

    async def delete(self, module_id: uuid.UUID) -> None:
        module = await self._modules.get_by_id(module_id)
        if module is None:
            raise ModuleNotFoundError(module_id)

        # NOTE : la vérification de dépendance sur Exercise sera complétée
        # quand exercise_repository.py exposera list_by_module(limit=1) —
        # pour l'instant on vérifie uniquement Enrollment, déjà disponible.
        enrollments_page = await self._enrollments.list_by_module(module_id, limit=1)
        if enrollments_page.items:
            raise ModuleHasActiveDependenciesError(module_id)

        await self._modules.delete(module_id)
