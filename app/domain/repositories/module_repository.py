import uuid
from typing import Protocol

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.academic.module import Module
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class ModuleRepositoryProtocol(Protocol):
    async def get_by_id(self, module_id: uuid.UUID) -> Module | None: ...
    async def get_by_code(self, code: str) -> Module | None: ...
    async def get_by_program_and_name(self, program_id: uuid.UUID, name: str) -> Module | None: ...
    async def list_page(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Module]: ...
    async def list_by_program(
        self, program_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Module]: ...
    async def create(self, program_id: uuid.UUID, name: str, code: str) -> Module: ...
    async def update(self, module_id: uuid.UUID, name: str, code: str) -> Module | None: ...
    async def delete(self, module_id: uuid.UUID) -> bool: ...


class SQLAlchemyModuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, module_id: uuid.UUID) -> Module | None:
        return await self._session.get(Module, module_id)

    async def get_by_code(self, code: str) -> Module | None:
        result = await self._session.execute(select(Module).where(Module.code == code))
        return result.scalar_one_or_none()

    async def get_by_program_and_name(self, program_id: uuid.UUID, name: str) -> Module | None:
        result = await self._session.execute(
            select(Module).where(Module.program_id == program_id, Module.name == name)
        )
        return result.scalar_one_or_none()

    async def list_page(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Module]:
        return await self._paginated_query(select(Module), cursor, limit)

    async def list_by_program(
        self, program_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Module]:
        query = select(Module).where(Module.program_id == program_id)
        return await self._paginated_query(query, cursor, limit)

    async def _paginated_query(self, query, cursor: str | None, limit: int) -> CursorPage[Module]:
        query = query.order_by(Module.created_at, Module.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Module.created_at, Module.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda m: (m.created_at, m.id))

    async def create(self, program_id: uuid.UUID, name: str, code: str) -> Module:
        module = Module(program_id=program_id, name=name, code=code)
        self._session.add(module)
        await self._session.flush()
        return module

    async def update(self, module_id: uuid.UUID, name: str, code: str) -> Module | None:
        module = await self.get_by_id(module_id)
        if module is None:
            return None
        module.name = name
        module.code = code
        await self._session.flush()
        return module

    async def delete(self, module_id: uuid.UUID) -> bool:
        module = await self.get_by_id(module_id)
        if module is None:
            return False
        await self._session.delete(module)
        await self._session.flush()
        return True