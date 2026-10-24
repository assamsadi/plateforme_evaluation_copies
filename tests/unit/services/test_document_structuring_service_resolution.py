"""
Tests unitaires pour la méthode resolve_unresolved_blocks de DocumentStructuringService.
"""
from datetime import datetime, timezone
import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.core.exceptions import NotExerciseOwnerError
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.assessment.teacher_correction_block import (
    BlockEvidenceLevel,
    TeacherCorrectionBlock,
)
from app.domain.schemas.teacher_correction_block_schemas import BlockResolutionItem
from app.services.document_structuring_service import DocumentStructuringService


def _make_storage_mock() -> MagicMock:
    storage = MagicMock()
    storage.generate_read_url.return_value = "https://storage.example.com/signed-crop"
    return storage


@pytest.mark.anyio
async def test_resolve_unresolved_blocks_success():
    prof_id = uuid.uuid4()
    exercise_id = uuid.uuid4()
    question_id = uuid.uuid4()
    block_id = uuid.uuid4()

    exercise = Exercise(id=exercise_id, created_by_professor_id=prof_id, status=ExerciseStatus.DRAFT)

    block = TeacherCorrectionBlock(
        id=block_id,
        exercise_id=exercise_id,
        question_id=None,
        content_type=ExtractionContentType.TEXT,
        evidence_level=BlockEvidenceLevel.UNRESOLVED_NO_LABEL,
        justification="Bloc non résolu",
        created_at=datetime.now(timezone.utc),
    )


    mock_exercise_repo = AsyncMock()
    mock_exercise_repo.get_by_id.return_value = exercise

    mock_block_repo = AsyncMock()
    mock_block_repo.update_resolution.return_value = block
    mock_block_repo.list_by_exercise.return_value = [block]

    mock_decision_log_repo = AsyncMock()

    service = DocumentStructuringService(
        exercise_repository=mock_exercise_repo,
        teacher_correction_block_repository=mock_block_repo,
        agent_decision_log_repository=mock_decision_log_repo,
        storage_service=_make_storage_mock(),
    )

    resolutions = [
        BlockResolutionItem(
            block_id=block_id,
            question_id=question_id,
            professor_resolution="Rattaché manuellement à la question Q1 par le prof",
        )
    ]

    result = await service.resolve_unresolved_blocks(
        exercise_id=exercise_id,
        requesting_professor_id=prof_id,
        resolutions=resolutions,
    )

    assert len(result) == 1
    mock_block_repo.update_resolution.assert_called_once_with(
        block_id=block_id,
        question_id=question_id,
        professor_resolution="Rattaché manuellement à la question Q1 par le prof",
    )
    mock_decision_log_repo.create.assert_called_once()


@pytest.mark.anyio
async def test_resolve_unresolved_blocks_forbidden_if_not_owner():
    prof_id = uuid.uuid4()
    other_prof_id = uuid.uuid4()
    exercise_id = uuid.uuid4()

    exercise = Exercise(id=exercise_id, created_by_professor_id=prof_id, status=ExerciseStatus.DRAFT)

    mock_exercise_repo = AsyncMock()
    mock_exercise_repo.get_by_id.return_value = exercise
    mock_block_repo = AsyncMock()
    mock_decision_log_repo = AsyncMock()

    service = DocumentStructuringService(
        exercise_repository=mock_exercise_repo,
        teacher_correction_block_repository=mock_block_repo,
        agent_decision_log_repository=mock_decision_log_repo,
        storage_service=_make_storage_mock(),
    )

    resolutions = [
        BlockResolutionItem(
            block_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            professor_resolution="Tentative par prof non propriétaire",
        )
    ]

    with pytest.raises(NotExerciseOwnerError):
        await service.resolve_unresolved_blocks(
            exercise_id=exercise_id,
            requesting_professor_id=other_prof_id,
            resolutions=resolutions,
        )
