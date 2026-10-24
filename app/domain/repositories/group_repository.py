import uuid
from typing import Protocol

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.academic.group import Group
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class GroupRepositoryProtocol(Protocol):
    async def get_by_id(self, group_id: uuid.UUID) -> Group | None: ...
    async def get_by_program_and_label(
        self, program_id: uuid.UUID, label: str
    ) -> Group | None: ...
    async def list_page(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Group]: ...
    async def list_by_program(
        self, program_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Group]: ...
    async def create(self, program_id: uuid.UUID, label: str, academic_year: str) -> Group: ...
    async def delete(self, group_id: uuid.UUID) -> bool: ...


class SQLAlchemyGroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, group_id: uuid.UUID) -> Group | None:
        return await self._session.get(Group, group_id)

    async def get_by_program_and_label(
        self, program_id: uuid.UUID, label: str
    ) -> Group | None:
        result = await self._session.execute(
            select(Group).where(Group.program_id == program_id, Group.label == label)
        )
        return result.scalar_one_or_none()

    async def list_page(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Group]:
        return await self._paginated_query(select(Group), cursor, limit)

    async def list_by_program(
        self, program_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Group]:
        query = select(Group).where(Group.program_id == program_id)
        return await self._paginated_query(query, cursor, limit)

    async def _paginated_query(self, query, cursor: str | None, limit: int) -> CursorPage[Group]:
        query = query.order_by(Group.created_at, Group.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Group.created_at, Group.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda g: (g.created_at, g.id))

    async def create(self, program_id: uuid.UUID, label: str, academic_year: str) -> Group:
        group = Group(program_id=program_id, label=label, academic_year=academic_year)
        self._session.add(group)
        await self._session.flush()
        return group

    async def delete(self, group_id: uuid.UUID) -> bool:
        group = await self.get_by_id(group_id)
        if group is None:
            return False
        await self._session.delete(group)
        await self._session.flush()
        return True