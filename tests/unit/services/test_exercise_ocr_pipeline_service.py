"""
Tests unitaires pour ExerciseOCRPipelineService.
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.Document_Structuring_Agent import StructuringReport
from app.agents.document_structuring_exceptions import StructuringIncompleteError
from app.core.exceptions import ExerciseNotFoundError
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import (
    ExtractionContentType,
    ExtractionEvidenceLevel,
)
from app.domain.schemas.submission_schemas import RawExtractedBlock
from app.services.exercise_ocr_pipeline_service import ExerciseOCRPipelineService


def _make_raw_block() -> RawExtractedBlock:
    return RawExtractedBlock(
        image_crop_path="exercises/x/ocr_crops/page_1_block_1.png",
        content_type=ExtractionContentType.TEXT,
        prediction_ocr="Correction Q1",
        confidence_score=Decimal("0.90"),
        bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
        page_number=1,
        block_order_index=1,
        evidence_level=ExtractionEvidenceLevel.AMBIGU,
    )


@pytest.mark.anyio
async def test_exercise_pipeline_run_success(monkeypatch):
    exercise_id = uuid.uuid4()
    professor_id = uuid.uuid4()

    exercise = MagicMock(
        id=exercise_id,
        status=ExerciseStatus.DRAFT,
        created_by_professor_id=professor_id,
    )
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    raw_block = _make_raw_block()
    report = StructuringReport(
        exercise_id=exercise_id,
        status="COMPLETE",
        sections_created=[],
        questions_created=[],
        correction_blocks_created=[],
        unresolved_block_count=0,
        questions_without_correction_count=0,
        label_conflict_count=0,
        empty_section_count=0,
        details={},
    )

    ocr_agent = AsyncMock()
    ocr_agent.execute.return_value = [raw_block]
    structuring_agent = AsyncMock()
    structuring_agent.execute.return_value = report
    structuring_service = AsyncMock()

    monkeypatch.setattr(
        "app.services.exercise_ocr_pipeline_service.storage_service.download",
        AsyncMock(return_value=b"%PDF-1.4"),
    )

    pipeline = ExerciseOCRPipelineService(
        exercise_repo=exercise_repo,
        teacher_block_repo=AsyncMock(),
        decision_log_repo=AsyncMock(),
        ocr_agent=ocr_agent,
        structuring_agent=structuring_agent,
        structuring_service=structuring_service,
    )

    blocks, result = await pipeline.run(
        exercise_id=exercise_id,
        professor_id=professor_id,
        document_path=f"exercises/{exercise_id}/reference.pdf",
        mime_type="application/pdf",
    )

    assert len(blocks) == 1
    assert result.status == "COMPLETE"
    ocr_agent.execute.assert_awaited_once()
    structuring_agent.execute.assert_awaited_once()
    structuring_service.structure_exercise.assert_awaited_once_with(
        exercise_id=exercise_id, report=report
    )


@pytest.mark.anyio
async def test_exercise_pipeline_raises_structuring_incomplete_error(monkeypatch):
    """Le pipeline persiste toujours la structure trouvée, PUIS lève
    StructuringIncompleteError si le rapport agent est INCOMPLETE — verrou
    immédiat, distinct de IncompleteExerciseSetupError levée plus tard à
    la publication (barème / variante de référence)."""
    exercise_id = uuid.uuid4()
    professor_id = uuid.uuid4()

    exercise = MagicMock(
        id=exercise_id,
        status=ExerciseStatus.DRAFT,
        created_by_professor_id=professor_id,
    )
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    raw_block = _make_raw_block()
    report = StructuringReport(
        exercise_id=exercise_id,
        status="INCOMPLETE",
        sections_created=[],
        questions_created=[{"order": 1, "statement": "Q1", "section_order": None}],
        correction_blocks_created=[],
        unresolved_block_count=0,
        questions_without_correction_count=1,
        label_conflict_count=0,
        empty_section_count=0,
        details={},
    )

    ocr_agent = AsyncMock()
    ocr_agent.execute.return_value = [raw_block]
    structuring_agent = AsyncMock()
    structuring_agent.execute.return_value = report
    structuring_service = AsyncMock()

    monkeypatch.setattr(
        "app.services.exercise_ocr_pipeline_service.storage_service.download",
        AsyncMock(return_value=b"%PDF-1.4"),
    )

    pipeline = ExerciseOCRPipelineService(
        exercise_repo=exercise_repo,
        teacher_block_repo=AsyncMock(),
        decision_log_repo=AsyncMock(),
        ocr_agent=ocr_agent,
        structuring_agent=structuring_agent,
        structuring_service=structuring_service,
    )

    with pytest.raises(StructuringIncompleteError):
        await pipeline.run(
            exercise_id=exercise_id,
            professor_id=professor_id,
            document_path=f"exercises/{exercise_id}/reference.pdf",
            mime_type="application/pdf",
        )

    # La persistance a bien eu lieu AVANT que l'erreur soit levée.
    structuring_service.structure_exercise.assert_awaited_once_with(
        exercise_id=exercise_id, report=report
    )


@pytest.mark.anyio
async def test_exercise_pipeline_raises_when_exercise_not_found():
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = None

    pipeline = ExerciseOCRPipelineService(
        exercise_repo=exercise_repo,
        teacher_block_repo=AsyncMock(),
        decision_log_repo=AsyncMock(),
    )

    with pytest.raises(ExerciseNotFoundError):
        await pipeline.run(
            exercise_id=uuid.uuid4(),
            professor_id=uuid.uuid4(),
            document_path="exercises/x/reference.pdf",
            mime_type="application/pdf",
        )
