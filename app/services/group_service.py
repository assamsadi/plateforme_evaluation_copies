"""
Service Group — règles métier :
1. Format de academic_year validé par regex (YYYY-YYYY, ex: "2025-2026"),
   avec vérification de cohérence (année de fin = année de début + 1).
2. Unicité (label par program) : violation DB traduite en erreur claire.
   Le rollback est géré par le middleware FastAPI — le service ne possède
   plus la session directement.
3. Interdiction de suppression si des Student ou Course actifs en
   dépendent.
"""
import re
import uuid
from typing import Protocol

from app.core.exceptions import (
    GroupAlreadyExistsError,
    GroupHasActiveDependenciesError,
    GroupNotFoundError,
    InvalidAcademicYearFormatError,
)
from sqlalchemy.exc import IntegrityError

from app.domain.models.academic.group import Group
from app.domain.repositories.course_repository import CourseRepositoryProtocol
from app.domain.repositories.group_repository import GroupRepositoryProtocol
from app.domain.repositories.pagination import CursorPage
from app.domain.repositories.program_repository import ProgramRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.academic_schemas import GroupRead

_ACADEMIC_YEAR_PATTERN = re.compile(r"^(\d{4})-(\d{4})$")


def _validate_academic_year(academic_year: str) -> str:
    match = _ACADEMIC_YEAR_PATTERN.match(academic_year.strip())
    if not match:
        raise InvalidAcademicYearFormatError(academic_year)
    start_year, end_year = int(match.group(1)), int(match.group(2))
    if end_year != start_year + 1:
        raise InvalidAcademicYearFormatError(academic_year)
    return academic_year.strip()


class GroupServiceProtocol(Protocol):
    async def get_by_id(self, group_id: uuid.UUID) -> GroupRead: ...
    async def list_by_program(
        self, program_id: uuid.UUID, cursor: str | None, limit: int
    ) -> CursorPage[GroupRead]: ...
    async def create(self, program_id: uuid.UUID, label: str, academic_year: str) -> GroupRead: ...
    async def delete(self, group_id: uuid.UUID) -> None: ...


class GroupService:
    def __init__(
        self,
        group_repository: GroupRepositoryProtocol,
        user_repository: UserRepositoryProtocol,
        course_repository: CourseRepositoryProtocol,
        program_repository: ProgramRepositoryProtocol,
    ) -> None:
        self._groups = group_repository
        self._users = user_repository
        self._courses = course_repository
        self._programs = program_repository

    async def _to_group_read(self, group: Group) -> GroupRead:
        """Peuple group.program_name et convertit en GroupRead."""
        program = await self._programs.get_by_id(group.program_id)
        group.program_name = program.name if program else "Unknown"
        return GroupRead.model_validate(group)

    async def get_by_id(self, group_id: uuid.UUID) -> GroupRead:
        group = await self._groups.get_by_id(group_id)
        if group is None:
            raise GroupNotFoundError(group_id)
        return await self._to_group_read(group)

    async def list_by_program(
        self, program_id: uuid.UUID, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[GroupRead]:
        page = await self._groups.list_by_program(program_id, limit=limit, cursor=cursor)
        items = [await self._to_group_read(g) for g in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def create(self, program_id: uuid.UUID, label: str, academic_year: str) -> GroupRead:
        validated_year = _validate_academic_year(academic_year)
        try:
            group = await self._groups.create(
                program_id=program_id, label=label.strip(), academic_year=validated_year
            )
            return await self._to_group_read(group)
        except IntegrityError as e:
            raise GroupAlreadyExistsError(program_id, label) from e

    async def delete(self, group_id: uuid.UUID) -> None:
        raw_group = await self._groups.get_by_id(group_id)
        if raw_group is None:
            raise GroupNotFoundError(group_id)

        students_page = await self._users.list_students_by_group(group_id, limit=1)
        courses_page = await self._courses.list_by_group(group_id, limit=1)

        if students_page.items or courses_page.items:
            raise GroupHasActiveDependenciesError(group_id)

        await self._groups.delete(group_id)