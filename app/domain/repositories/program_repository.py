"""
Repository Program — template de référence pour tous les autres
repositories du projet (même structure : Protocol abstrait + implémentation
SQLAlchemy injectée avec une AsyncSession).

Le service ne dépend JAMAIS de SQLAlchemyProgramRepository directement,
toujours de ProgramRepositoryProtocol — permet de substituer une
implémentation en mémoire dans les tests unitaires, sans DB réelle.
"""
import uuid
from typing import Protocol

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.academic.program import Program
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class ProgramRepositoryProtocol(Protocol):
    async def get_by_id(self, program_id: uuid.UUID) -> Program | None: ...
    async def get_by_code(self, code: str) -> Program | None: ...
    async def list_page(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Program]: ...
    async def create(self, name: str, code: str) -> Program: ...
    async def update(self, program_id: uuid.UUID, name: str, code: str) -> Program | None: ...
    async def delete(self, program_id: uuid.UUID) -> bool: ...


class SQLAlchemyProgramRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, program_id: uuid.UUID) -> Program | None:
        return await self._session.get(Program, program_id)

    async def get_by_code(self, code: str) -> Program | None:
        result = await self._session.execute(select(Program).where(Program.code == code))
        return result.scalar_one_or_none()

    async def list_page(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Program]:
        query = select(Program).order_by(Program.created_at, Program.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Program.created_at, Program.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)  # +1 pour détecter has_more sans COUNT séparé
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda p: (p.created_at, p.id))

    async def create(self, name: str, code: str) -> Program:
        program = Program(name=name, code=code)
        self._session.add(program)
        await self._session.flush()  # attribue l'id sans committer (le service/get_db gère le commit)
        return program

    async def update(self, program_id: uuid.UUID, name: str, code: str) -> Program | None:
        program = await self.get_by_id(program_id)
        if program is None:
            return None
        program.name = name
        program.code = code
        await self._session.flush()
        return program

    async def delete(self, program_id: uuid.UUID) -> bool:
        program = await self.get_by_id(program_id)
        if program is None:
            return False
        await self._session.delete(program)
        await self._session.flush()
        return True