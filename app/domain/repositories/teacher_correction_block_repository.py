"""
Repository TeacherCorrectionBlock.

Opérations :
- create : persiste un bloc unique (appelable par Document_Structuring_Agent)
- bulk_create_for_exercise : persiste en lot tous les blocs d'un exercice
- list_by_exercise : liste tous les blocs, triés par question_id puis created_at
- list_unresolved_by_exercise : filtre sur UNRESOLVED_NO_LABEL — utilisé
  par exercise_service.publish() pour la vérification de complétude bloquante
- update_resolution : HITL professeur — rattache le bloc à une question
  et trace la décision dans professor_resolution
"""
import uuid
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.assessment.teacher_correction_block import (
    BlockEvidenceLevel,
    TeacherCorrectionBlock,
)


class TeacherCorrectionBlockRepositoryProtocol(Protocol):
    async def create(
        self,
        exercise_id: uuid.UUID,
        content_type: ExtractionContentType,
        evidence_level: BlockEvidenceLevel,
        justification: str,
        question_id: uuid.UUID | None = None,
        image_crop_path: str | None = None,
        raw_text: str | None = None,
        structured_content: dict | None = None,
        page_number: int | None = None,
        block_order_index: int | None = None,
        ocr_confidence: Decimal | None = None,
    ) -> TeacherCorrectionBlock: ...

    async def bulk_create_for_exercise(
        self,
        exercise_id: uuid.UUID,
        blocks: list[dict],
    ) -> list[TeacherCorrectionBlock]: ...

    async def get_by_id(
        self, block_id: uuid.UUID
    ) -> TeacherCorrectionBlock | None: ...

    async def list_by_exercise(
        self, exercise_id: uuid.UUID
    ) -> list[TeacherCorrectionBlock]: ...

    async def list_unresolved_by_exercise(
        self, exercise_id: uuid.UUID
    ) -> list[TeacherCorrectionBlock]: ...

    async def update_resolution(
        self,
        block_id: uuid.UUID,
        question_id: uuid.UUID | None,
        professor_resolution: str,
    ) -> TeacherCorrectionBlock | None: ...


class SQLAlchemyTeacherCorrectionBlockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        exercise_id: uuid.UUID,
        content_type: ExtractionContentType,
        evidence_level: BlockEvidenceLevel,
        justification: str,
        question_id: uuid.UUID | None = None,
        image_crop_path: str | None = None,
        raw_text: str | None = None,
        structured_content: dict | None = None,
        page_number: int | None = None,
        block_order_index: int | None = None,
        ocr_confidence: Decimal | None = None,
    ) -> TeacherCorrectionBlock:
        block = TeacherCorrectionBlock(
            exercise_id=exercise_id,
            question_id=question_id,
            image_crop_path=image_crop_path,
            content_type=content_type,
            raw_text=raw_text,
            structured_content=structured_content,
            evidence_level=evidence_level,
            justification=justification,
            page_number=page_number,
            block_order_index=block_order_index,
            ocr_confidence=ocr_confidence,
        )
        self._session.add(block)
        await self._session.flush()
        return block

    async def bulk_create_for_exercise(
        self,
        exercise_id: uuid.UUID,
        blocks: list[dict],
    ) -> list[TeacherCorrectionBlock]:
        """
        Persiste tous les blocs extraits d'un exercice en une seule opération.

        Chaque bloc dict doit contenir :
          - content_type (ExtractionContentType | str)
          - evidence_level (BlockEvidenceLevel | str)
          - justification (str)
          - question_id (uuid.UUID | None) — optionnel
          - image_crop_path (str | None) — optionnel
          - raw_text (str | None) — optionnel
          - structured_content (dict | None) — optionnel
          - page_number (int | None) — optionnel, position réelle dans le
            document source (cf. docstring du modèle) — nécessaire pour que
            list_by_exercise() reconstruise le texte de correction dans
            l'ordre de LECTURE, pas l'ordre d'insertion pendant le pipeline.
          - block_order_index (int | None) — optionnel, tri secondaire au
            sein d'une même page.
          - ocr_confidence (Decimal | None) — optionnel, confiance OCR
            combinée (RawExtractedBlock.confidence_score, cf. B11).
        """
        created = []
        for block in blocks:
            tcb = TeacherCorrectionBlock(
                exercise_id=exercise_id,
                question_id=block.get("question_id"),
                image_crop_path=block.get("image_crop_path"),
                content_type=ExtractionContentType(block["content_type"]),
                raw_text=block.get("raw_text"),
                structured_content=block.get("structured_content"),
                evidence_level=BlockEvidenceLevel(block["evidence_level"]),
                justification=block["justification"],
                page_number=block.get("page_number"),
                block_order_index=block.get("block_order_index"),
                ocr_confidence=block.get("ocr_confidence"),
            )
            self._session.add(tcb)
            created.append(tcb)
        await self._session.flush()
        return created

    async def get_by_id(
        self, block_id: uuid.UUID
    ) -> TeacherCorrectionBlock | None:
        return await self._session.get(TeacherCorrectionBlock, block_id)

    async def list_by_exercise(
        self, exercise_id: uuid.UUID
    ) -> list[TeacherCorrectionBlock]:
        """
        Tri par question puis par POSITION RÉELLE dans le document source
        (page_number, block_order_index) — jamais created_at seul, qui ne
        reflète que l'ordre d'INSERTION pendant le pipeline (dépend du
        traitement interne de Document_Structuring_Agent, jamais garanti
        égal à l'ordre de lecture du document, cf. docstring du modèle et
        B5 de backlog_bugs_c2pct.md). created_at reste le tri de repli final
        pour les blocs plus anciens sans page_number (nullable, créés avant
        ce champ) — comportement inchangé pour eux, jamais une régression.
        """
        result = await self._session.execute(
            select(TeacherCorrectionBlock)
            .where(TeacherCorrectionBlock.exercise_id == exercise_id)
            .order_by(
                TeacherCorrectionBlock.question_id.nulls_last(),
                TeacherCorrectionBlock.page_number.nulls_last(),
                TeacherCorrectionBlock.block_order_index.nulls_last(),
                TeacherCorrectionBlock.created_at,
            )
        )
        return list(result.scalars().all())

    async def list_unresolved_by_exercise(
        self, exercise_id: uuid.UUID
    ) -> list[TeacherCorrectionBlock]:
        """Blocs UNRESOLVED_NO_LABEL — bloquants pour la publication."""
        result = await self._session.execute(
            select(TeacherCorrectionBlock)
            .where(
                TeacherCorrectionBlock.exercise_id == exercise_id,
                TeacherCorrectionBlock.evidence_level
                == BlockEvidenceLevel.UNRESOLVED_NO_LABEL,
                TeacherCorrectionBlock.professor_resolution.is_(None),
            )
            .order_by(TeacherCorrectionBlock.created_at)
        )
        return list(result.scalars().all())

    async def update_resolution(
        self,
        block_id: uuid.UUID,
        question_id: uuid.UUID | None,
        professor_resolution: str,
    ) -> TeacherCorrectionBlock | None:
        block = await self.get_by_id(block_id)
        if block is None:
            return None
        block.question_id = question_id
        block.professor_resolution = professor_resolution
        await self._session.flush()
        return block
