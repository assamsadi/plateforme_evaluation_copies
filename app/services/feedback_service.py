"""
Service de gestion du feedback et de son historique de versions.

Règles métier appliquées :
1. Le feedback IA génère la version initiale ou une nouvelle version (author_type=AI).
   Il s'appuie sur le mécanisme get_or_create() du repository pour garantir un seul 
   feedback racine par (soumission, question).
2. Le professeur peut éditer ce feedback (author_type=TEACHER), ce qui crée une nouvelle 
   version dans l'historique sans écraser les précédentes. L'historique permet de 
   tracer les corrections manuelles.
"""
import uuid
from typing import Protocol

from app.core.exceptions import FeedbackNotFoundError
from app.domain.models.assessment.feedback_version import FeedbackAuthorType, FeedbackVersion
from app.domain.repositories.feedback_repository import FeedbackRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.evaluation_schemas import FeedbackVersionRead


class FeedbackServiceProtocol(Protocol):
    async def generate_ai_feedback(
        self, submission_id: uuid.UUID, question_id: uuid.UUID, content: str
    ) -> FeedbackVersionRead: ...

    async def edit_feedback(
        self, feedback_id: uuid.UUID, professor_id: uuid.UUID, new_content: str
    ) -> FeedbackVersionRead: ...

    async def get_latest(self, feedback_id: uuid.UUID) -> FeedbackVersionRead: ...

    async def get_history(self, feedback_id: uuid.UUID) -> list[FeedbackVersionRead]: ...


class FeedbackService:
    def __init__(
        self,
        feedback_repo: FeedbackRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
    ) -> None:
        self._feedback_repo = feedback_repo
        self._user_repo = user_repo

    async def generate_ai_feedback(
        self, submission_id: uuid.UUID, question_id: uuid.UUID, content: str
    ) -> FeedbackVersionRead:
        feedback = await self._feedback_repo.get_or_create(
            submission_id=submission_id, question_id=question_id
        )
        version = await self._feedback_repo.add_version(
            feedback_id=feedback.id,
            content=content,
            author_type=FeedbackAuthorType.AI,
            author_user_id=None,
        )
        version.author_full_name = None
        return FeedbackVersionRead.model_validate(version)

    async def edit_feedback(
        self, feedback_id: uuid.UUID, professor_id: uuid.UUID, new_content: str
    ) -> FeedbackVersionRead:
        latest = await self._feedback_repo.get_latest_version(feedback_id)
        if not latest:
            raise FeedbackNotFoundError(feedback_id)

        version = await self._feedback_repo.add_version(
            feedback_id=feedback_id,
            content=new_content,
            author_type=FeedbackAuthorType.TEACHER,
            author_user_id=professor_id,
        )
        teacher = await self._user_repo.get_by_id(professor_id)
        version.author_full_name = f"{teacher.first_name} {teacher.last_name}" if teacher else None
        return FeedbackVersionRead.model_validate(version)

    async def get_latest(self, feedback_id: uuid.UUID) -> FeedbackVersionRead:
        latest = await self._feedback_repo.get_latest_version(feedback_id)
        if not latest:
            raise FeedbackNotFoundError(feedback_id)
        if latest.author_type == FeedbackAuthorType.TEACHER and latest.author_user_id:
            teacher = await self._user_repo.get_by_id(latest.author_user_id)
            latest.author_full_name = f"{teacher.first_name} {teacher.last_name}" if teacher else None
        else:
            latest.author_full_name = None
        return FeedbackVersionRead.model_validate(latest)

    async def get_history(self, feedback_id: uuid.UUID) -> list[FeedbackVersionRead]:
        versions = await self._feedback_repo.list_versions(feedback_id)
        result: list[FeedbackVersionRead] = []
        for v in versions:
            if v.author_type == FeedbackAuthorType.TEACHER and v.author_user_id:
                teacher = await self._user_repo.get_by_id(v.author_user_id)
                v.author_full_name = f"{teacher.first_name} {teacher.last_name}" if teacher else None
            else:
                v.author_full_name = None
            result.append(FeedbackVersionRead.model_validate(v))
        return result

