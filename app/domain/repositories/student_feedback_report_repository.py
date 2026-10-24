"""
Repository StudentFeedbackReport — persistance du feedback socratique
généré par Feedback_Agent (§7 cahier des charges, "Feedback Intelligent").

Une ligne par exécution de feedback_node — jamais de mise à jour après
création (contrairement à StudentNotebook) : une nouvelle soumission qui
retraverse le pipeline produit une NOUVELLE ligne (nouveau submission_id),
jamais une réécriture de la précédente.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Protocol

from app.domain.models.assessment.student_feedback_report import StudentFeedbackReport


class StudentFeedbackReportRepositoryProtocol(Protocol):
    async def create(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        submission_id: uuid.UUID,
        feedback_text: str,
        competencies_addressed: list[str],
    ) -> StudentFeedbackReport: ...

    async def get_by_submission(self, submission_id: uuid.UUID) -> StudentFeedbackReport | None: ...


class SQLAlchemyStudentFeedbackReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        submission_id: uuid.UUID,
        feedback_text: str,
        competencies_addressed: list[str],
    ) -> StudentFeedbackReport:
        record = StudentFeedbackReport(
            student_id=student_id,
            module_id=module_id,
            submission_id=submission_id,
            feedback_text=feedback_text,
            competencies_addressed=competencies_addressed,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_submission(self, submission_id: uuid.UUID) -> StudentFeedbackReport | None:
        result = await self._session.execute(
            select(StudentFeedbackReport)
            .where(StudentFeedbackReport.submission_id == submission_id)
            .order_by(StudentFeedbackReport.created_at.desc())
        )
        return result.scalars().first()
