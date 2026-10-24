"""
Repository StudentNotebook — persistance de la référence externe NotebookLM
créée pour une génération de recommandations (§7, intégration NotebookLM,
Partie 1/2 + Partie 2/2 formats de sortie).

Écriture initiale (create) uniquement APRÈS succès réel de la création
côté NotebookLM (cf. NotebookLMService, best-effort) — jamais de ligne
"failed" à nettoyer.

Partie 2/2 — mises à jour ultérieures best-effort (audio/flashcards) et
cycle de vie vidéo (not_requested -> pending -> ready, ou repli sur
not_requested si la génération échoue réellement — jamais bloqué sur
pending indéfiniment, cf. docstring modèle).
"""
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.student_notebook import (
    GenerationStatus,
    StudentNotebook,
    VideoOverviewStatus,
)


class StudentNotebookRepositoryProtocol(Protocol):
    async def create(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        notebook_id: str,
        submission_id: uuid.UUID | None = None,
    ) -> StudentNotebook: ...
    async def get_by_id(self, notebook_record_id: uuid.UUID) -> StudentNotebook | None: ...
    async def list_by_student(self, student_id: uuid.UUID) -> list[StudentNotebook]: ...
    async def update_audio_overview_path(self, notebook_record_id: uuid.UUID, path: str) -> None: ...
    async def update_audio_overview_status(
        self, notebook_record_id: uuid.UUID, status: GenerationStatus,
    ) -> None: ...
    async def update_flashcards_path(self, notebook_record_id: uuid.UUID, path: str) -> None: ...
    async def update_flashcards_status(
        self, notebook_record_id: uuid.UUID, status: GenerationStatus,
    ) -> None: ...
    async def update_video_overview_status(
        self, notebook_record_id: uuid.UUID, status: VideoOverviewStatus, path: str | None = None,
    ) -> None: ...


class SQLAlchemyStudentNotebookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        notebook_id: str,
        submission_id: uuid.UUID | None = None,
    ) -> StudentNotebook:
        record = StudentNotebook(
            student_id=student_id, module_id=module_id,
            submission_id=submission_id, notebook_id=notebook_id,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_id(self, notebook_record_id: uuid.UUID) -> StudentNotebook | None:
        return await self._session.get(StudentNotebook, notebook_record_id)

    async def list_by_student(self, student_id: uuid.UUID) -> list[StudentNotebook]:
        result = await self._session.execute(
            select(StudentNotebook)
            .where(StudentNotebook.student_id == student_id)
            .order_by(StudentNotebook.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_audio_overview_path(self, notebook_record_id: uuid.UUID, path: str) -> None:
        """Path uniquement posé sur un succès réel — passe donc toujours le statut à READY."""
        record = await self._session.get(StudentNotebook, notebook_record_id)
        if record is not None:
            record.audio_overview_path = path
            record.audio_overview_status = GenerationStatus.READY
            await self._session.flush()

    async def update_audio_overview_status(self, notebook_record_id: uuid.UUID, status: GenerationStatus) -> None:
        record = await self._session.get(StudentNotebook, notebook_record_id)
        if record is not None:
            record.audio_overview_status = status
            await self._session.flush()

    async def update_flashcards_path(self, notebook_record_id: uuid.UUID, path: str) -> None:
        """Path uniquement posé sur un succès réel — passe donc toujours le statut à READY."""
        record = await self._session.get(StudentNotebook, notebook_record_id)
        if record is not None:
            record.flashcards_path = path
            record.flashcards_status = GenerationStatus.READY
            await self._session.flush()

    async def update_flashcards_status(self, notebook_record_id: uuid.UUID, status: GenerationStatus) -> None:
        record = await self._session.get(StudentNotebook, notebook_record_id)
        if record is not None:
            record.flashcards_status = status
            await self._session.flush()

    async def update_video_overview_status(
        self, notebook_record_id: uuid.UUID, status: VideoOverviewStatus, path: str | None = None,
    ) -> None:
        record = await self._session.get(StudentNotebook, notebook_record_id)
        if record is not None:
            record.video_overview_status = status
            if path is not None:
                record.video_overview_path = path
            await self._session.flush()
