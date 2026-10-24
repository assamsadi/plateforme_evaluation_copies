import uuid
from typing import Protocol

from sqlalchemy import exists, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.academic.enrollment import Enrollment
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class EnrollmentRepositoryProtocol(Protocol):
    async def get_by_id(self, enrollment_id: uuid.UUID) -> Enrollment | None: ...
    async def get_by_student_and_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID
    ) -> Enrollment | None: ...
    async def is_student_enrolled_and_active(
        self, student_id: uuid.UUID, module_id: uuid.UUID
    ) -> bool: ...
    async def list_by_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Enrollment]: ...
    async def list_by_module(
        self, module_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Enrollment]: ...
    async def create(self, student_id: uuid.UUID, module_id: uuid.UUID) -> Enrollment: ...
    async def deactivate(self, enrollment_id: uuid.UUID) -> Enrollment | None: ...
    async def reactivate(self, enrollment_id: uuid.UUID) -> Enrollment | None: ...


class SQLAlchemyEnrollmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, enrollment_id: uuid.UUID) -> Enrollment | None:
        return await self._session.get(Enrollment, enrollment_id)

    async def get_by_student_and_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID
    ) -> Enrollment | None:
        result = await self._session.execute(
            select(Enrollment).where(
                Enrollment.student_id == student_id, Enrollment.module_id == module_id
            )
        )
        return result.scalar_one_or_none()

    async def is_student_enrolled_and_active(
        self, student_id: uuid.UUID, module_id: uuid.UUID
    ) -> bool:
        """
        EXISTS pur, aucun objet ORM chargé — appelée à CHAQUE accès à la
        Library d'un module, doit rester la plus légère possible.
        """
        stmt = select(
            exists().where(
                Enrollment.student_id == student_id,
                Enrollment.module_id == module_id,
                Enrollment.is_active.is_(True),
            )
        )
        result = await self._session.execute(stmt)
        return bool(result.scalar())

    async def list_by_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Enrollment]:
        query = select(Enrollment).where(Enrollment.student_id == student_id)
        return await self._paginated_query(query, cursor, limit)

    async def list_by_module(
        self, module_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Enrollment]:
        query = select(Enrollment).where(Enrollment.module_id == module_id)
        return await self._paginated_query(query, cursor, limit)

    async def _paginated_query(self, query, cursor: str | None, limit: int) -> CursorPage[Enrollment]:
        query = query.order_by(Enrollment.created_at, Enrollment.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Enrollment.created_at, Enrollment.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda e: (e.created_at, e.id))

    async def create(self, student_id: uuid.UUID, module_id: uuid.UUID) -> Enrollment:
        enrollment = Enrollment(student_id=student_id, module_id=module_id)
        self._session.add(enrollment)
        await self._session.flush()
        return enrollment

    async def deactivate(self, enrollment_id: uuid.UUID) -> Enrollment | None:
        """
        Désinscription = is_active=False, jamais un DELETE (§ décision
        : une inscription peut être désactivée, garde l'historique).
        """
        enrollment = await self.get_by_id(enrollment_id)
        if enrollment is None:
            return None
        enrollment.is_active = False
        await self._session.flush()
        return enrollment

    async def reactivate(self, enrollment_id: uuid.UUID) -> Enrollment | None:
        """
        Réinscription = réactive la ligne existante, JAMAIS une nouvelle
        ligne — la contrainte unique (student_id, module_id) porte sur la
        paire peu importe is_active, donc une 2e ligne échouerait de
        toute façon. enrolled_at n'est PAS remis à jour (garde la date
        d'inscription d'origine, cohérent avec l'historique conservé).
        """
        enrollment = await self.get_by_id(enrollment_id)
        if enrollment is None:
            return None
        enrollment.is_active = True
        await self._session.flush()
        return enrollment