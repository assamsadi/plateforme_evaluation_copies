"""
Repository Feedback — racine d'agrégat couvrant Feedback + FeedbackVersion.

add_version() utilise SELECT MAX(version_number) ... FOR UPDATE, même
pattern que SubmissionRepository.get_next_attempt_number() — évite que
deux éditions simultanées du même feedback (ex. l'agent IA régénère
pendant que le prof édite) créent deux fois la même version_number,
violant silencieusement la contrainte unique (feedback_id, version_number).
"""
import uuid
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.feedback import Feedback
from app.domain.models.assessment.feedback_version import (
    FeedbackAuthorType,
    FeedbackVersion,
)


class FeedbackRepositoryProtocol(Protocol):
    async def get_by_id(self, feedback_id: uuid.UUID) -> Feedback | None: ...
    async def get_by_submission_and_question(
        self, submission_id: uuid.UUID, question_id: uuid.UUID
    ) -> Feedback | None: ...
    async def get_or_create(
        self, submission_id: uuid.UUID, question_id: uuid.UUID
    ) -> Feedback: ...
    async def list_versions(self, feedback_id: uuid.UUID) -> list[FeedbackVersion]: ...
    async def get_latest_version(self, feedback_id: uuid.UUID) -> FeedbackVersion | None: ...
    async def add_version(
        self,
        feedback_id: uuid.UUID,
        content: str,
        author_type: FeedbackAuthorType,
        author_user_id: uuid.UUID | None,
    ) -> FeedbackVersion: ...


class SQLAlchemyFeedbackRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, feedback_id: uuid.UUID) -> Feedback | None:
        return await self._session.get(Feedback, feedback_id)

    async def get_by_submission_and_question(
        self, submission_id: uuid.UUID, question_id: uuid.UUID
    ) -> Feedback | None:
        result = await self._session.execute(
            select(Feedback).where(
                Feedback.submission_id == submission_id, Feedback.question_id == question_id
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, submission_id: uuid.UUID, question_id: uuid.UUID
    ) -> Feedback:
        existing = await self.get_by_submission_and_question(submission_id, question_id)
        if existing is not None:
            return existing
        feedback = Feedback(submission_id=submission_id, question_id=question_id)
        self._session.add(feedback)
        await self._session.flush()
        return feedback

    async def list_versions(self, feedback_id: uuid.UUID) -> list[FeedbackVersion]:
        result = await self._session.execute(
            select(FeedbackVersion)
            .where(FeedbackVersion.feedback_id == feedback_id)
            .order_by(FeedbackVersion.version_number)
        )
        return list(result.scalars().all())

    async def get_latest_version(self, feedback_id: uuid.UUID) -> FeedbackVersion | None:
        result = await self._session.execute(
            select(FeedbackVersion)
            .where(FeedbackVersion.feedback_id == feedback_id)
            .order_by(FeedbackVersion.version_number.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def add_version(
        self,
        feedback_id: uuid.UUID,
        content: str,
        author_type: FeedbackAuthorType,
        author_user_id: uuid.UUID | None,
    ) -> FeedbackVersion:
        """
        Verrou pessimiste sur MAX(version_number) : doit être appelée
        sans requête intercalée avant l'insert qui suit (même contrat
        que SubmissionRepository.get_next_attempt_number()).
        """
        # Verrouille la ligne Feedback
        await self._session.execute(
            select(Feedback)
            .where(Feedback.id == feedback_id)
            .with_for_update()
        )

        # Puis calcule le MAX sans FOR UPDATE
        result = await self._session.execute(
            select(func.max(FeedbackVersion.version_number))
            .where(FeedbackVersion.feedback_id == feedback_id)
        )

        next_version = (result.scalar_one_or_none() or 0) + 1

        version = FeedbackVersion(
            feedback_id=feedback_id,
            version_number=next_version,
            content=content,
            author_type=author_type,
            author_user_id=author_user_id,
        )
        self._session.add(version)
        await self._session.flush()
        return version