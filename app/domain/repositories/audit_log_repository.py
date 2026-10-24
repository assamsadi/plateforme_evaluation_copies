import uuid
from typing import Protocol

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.audit_log import AuditLog, AuditSeverity
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class AuditLogRepositoryProtocol(Protocol):
    async def create(
        self,
        user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        diff: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        severity: AuditSeverity = AuditSeverity.INFO,
    ) -> AuditLog: ...
    async def list_page(
        self,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        entity_type: str | None = None,
        user_id: uuid.UUID | None = None,
        severity: AuditSeverity | None = None,
        action: str | None = None,
    ) -> CursorPage[AuditLog]: ...


class SQLAlchemyAuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        diff: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        severity: AuditSeverity = AuditSeverity.INFO,
    ) -> AuditLog:
        audit_log = AuditLog(
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            diff=diff,
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            severity=severity,
        )
        self._session.add(audit_log)
        await self._session.flush()
        return audit_log

    async def list_page(
        self,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        entity_type: str | None = None,
        user_id: uuid.UUID | None = None,
        severity: AuditSeverity | None = None,
        action: str | None = None,
    ) -> CursorPage[AuditLog]:
        # Ordre DESC (plus récent d'abord) — contrairement aux autres
        # repositories (Program/Group/Module en ASC) : un journal d'audit
        # se consulte en partant des événements les plus récents, pas des
        # plus anciens. Le curseur encode toujours (created_at, id) de la
        # dernière ligne vue, juste comparé avec `<` au lieu de `>`.
        query = select(AuditLog)
        if action:
            query = query.where(AuditLog.action == action)
        if entity_type:
            query = query.where(AuditLog.entity_type == entity_type)
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        if severity:
            query = query.where(AuditLog.severity == severity)

        query = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(AuditLog.created_at, AuditLog.id) < (after_created_at, after_id)
            )
        query = query.limit(limit + 1)

        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda log: (log.created_at, log.id))
