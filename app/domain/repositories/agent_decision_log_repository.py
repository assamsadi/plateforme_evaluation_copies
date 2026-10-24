"""
Repository AgentDecisionLog.

Trace l'ensemble des décisions des agents IA pour l'observabilité LLMOps,
l'explicabilité et la boucle de rétroaction humaine.
"""
import uuid
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.agent_decision_log import (
    AgentDecisionLog,
    ProfessorValidationStatus,
)
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class AgentDecisionLogRepositoryProtocol(Protocol):
    async def create(
        self,
        agent_name: str,
        related_entity_type: str,
        related_entity_id: uuid.UUID,
        justification: str,
        model_version: str,
        input_summary: str | None = None,
        output_summary: str | None = None,
        confidence_score: Decimal | None = None,
        prompt_text: str | None = None,
        prompt_version: str | None = None,
        tools_consulted: list[dict] | None = None,
        execution_time_ms: int | None = None,
        token_count_input: int | None = None,
        token_count_output: int | None = None,
        thread_id: uuid.UUID | None = None,
        run_id: str | None = None,
        node_name: str | None = None,
    ) -> AgentDecisionLog: ...

    async def get_by_id(self, log_id: uuid.UUID) -> AgentDecisionLog | None: ...

    async def list_by_entity(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLog]: ...

    async def record_professor_feedback(
        self,
        log_id: uuid.UUID,
        professor_id: uuid.UUID,
        status: ProfessorValidationStatus,
        correction: str | None = None,
    ) -> AgentDecisionLog | None: ...

    async def list_all(
        self,
        agent_name: str | None = None,
        professor_validation_status: ProfessorValidationStatus | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLog]: ...


class SQLAlchemyAgentDecisionLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        agent_name: str,
        related_entity_type: str,
        related_entity_id: uuid.UUID,
        justification: str,
        model_version: str,
        input_summary: str | None = None,
        output_summary: str | None = None,
        confidence_score: Decimal | None = None,
        prompt_text: str | None = None,
        prompt_version: str | None = None,
        tools_consulted: list[dict] | None = None,
        execution_time_ms: int | None = None,
        token_count_input: int | None = None,
        token_count_output: int | None = None,
        thread_id: uuid.UUID | None = None,
        run_id: str | None = None,
        node_name: str | None = None,
    ) -> AgentDecisionLog:
        log = AgentDecisionLog(
            agent_name=agent_name,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            justification=justification,
            model_version=model_version,
            input_summary=input_summary,
            output_summary=output_summary,
            confidence_score=confidence_score,
            prompt_text=prompt_text,
            prompt_version=prompt_version,
            tools_consulted=tools_consulted or [],
            execution_time_ms=execution_time_ms,
            token_count_input=token_count_input,
            token_count_output=token_count_output,
            thread_id=thread_id,
            run_id=run_id,
            node_name=node_name,
        )
        self._session.add(log)
        await self._session.flush()
        return log

    async def get_by_id(self, log_id: uuid.UUID) -> AgentDecisionLog | None:
        return await self._session.get(AgentDecisionLog, log_id)

    async def list_by_entity(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLog]:
        query = select(AgentDecisionLog).where(
            AgentDecisionLog.related_entity_type == entity_type,
            AgentDecisionLog.related_entity_id == entity_id,
        )
        query = query.order_by(AgentDecisionLog.created_at, AgentDecisionLog.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(AgentDecisionLog.created_at, AgentDecisionLog.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda l: (l.created_at, l.id))

    async def record_professor_feedback(
        self,
        log_id: uuid.UUID,
        professor_id: uuid.UUID,
        status: ProfessorValidationStatus,
        correction: str | None = None,
    ) -> AgentDecisionLog | None:
        log = await self.get_by_id(log_id)
        if log is None:
            return None
        log.professor_validation_status = status
        log.professor_correction = correction
        log.validated_by_professor_id = professor_id
        await self._session.flush()
        return log

    async def list_all(
        self,
        agent_name: str | None = None,
        professor_validation_status: ProfessorValidationStatus | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[AgentDecisionLog]:
        """
        Vue transverse (supervision admin) — pas de filtre "severity" : le
        modèle n'a aucune colonne de sévérité (vérifié). agent_name et
        professor_validation_status sont les seuls axes de filtre réels
        existants (professor_validation_status = proxy le plus proche d'un
        "type de décision" : CORRECTED signale une décision que le
        professeur a dû rectifier, utile pour repérer les décisions à
        surveiller).
        """
        query = select(AgentDecisionLog)
        if agent_name is not None:
            query = query.where(AgentDecisionLog.agent_name == agent_name)
        if professor_validation_status is not None:
            query = query.where(
                AgentDecisionLog.professor_validation_status == professor_validation_status
            )
        query = query.order_by(AgentDecisionLog.created_at, AgentDecisionLog.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(AgentDecisionLog.created_at, AgentDecisionLog.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda l: (l.created_at, l.id))
