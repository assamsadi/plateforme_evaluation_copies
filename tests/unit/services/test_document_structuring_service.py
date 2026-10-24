"""
Tests unitaires pour DocumentStructuringService.

Couvre la résolution du question_id réel des TeacherCorrectionBlock via la
clé composite (section_order, question_order) contre les Question
effectivement créées par ExerciseRepository.add_structure() — jamais un
identifiant fabriqué côté agent (cf. décision actée : le service persiste,
l'agent calcule).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import ExerciseNotFoundError, NotExerciseOwnerError
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.assessment.teacher_correction_block import BlockEvidenceLevel
from app.services.document_structuring_service import DocumentStructuringService


@dataclass
class _FakeReport:
    status: str
    sections_created: list[dict] = field(default_factory=list)
    questions_created: list[dict] = field(default_factory=list)
    correction_blocks_created: list[dict] = field(default_factory=list)
    block_classifications: list[dict] = field(default_factory=list)


def _make_storage_mock() -> MagicMock:
    storage = MagicMock()
    storage.generate_read_url.return_value = "https://storage.example.com/signed-crop"
    return storage


def _fake_persisted_block(question_id: uuid.UUID | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        exercise_id=uuid.uuid4(),
        question_id=question_id,
        image_crop_path="exercises/x/ocr_crops/page_1_block_1.png",
        content_type=ExtractionContentType.TEXT,
        raw_text="Réponse : 42.",
        structured_content=None,
        evidence_level=(
            BlockEvidenceLevel.LABEL_EXPLICITE if question_id else BlockEvidenceLevel.UNRESOLVED_NO_LABEL
        ),
        professor_resolution=None,
        justification="Rattaché via label explicite Q1.",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.anyio
async def test_structure_exercise_raises_when_exercise_not_found():
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = None
    service = DocumentStructuringService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=AsyncMock(),
        agent_decision_log_repository=AsyncMock(),
        storage_service=_make_storage_mock(),
    )

    with pytest.raises(ExerciseNotFoundError):
        await service.structure_exercise(uuid.uuid4(), _FakeReport(status="COMPLETE"))


@pytest.mark.anyio
async def test_structure_exercise_resolves_question_id_via_composite_key():
    exercise_id = uuid.uuid4()
    question_1_id = uuid.uuid4()

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(id=exercise_id)
    exercise_repo.add_structure.return_value = (
        {1: uuid.uuid4()},  # section_id_by_order
        {(1, 1): question_1_id},  # question_id_by_key : section 1, question order 1
    )

    block_repo = AsyncMock()
    block_repo.bulk_create_for_exercise.return_value = [
        _fake_persisted_block(question_1_id),
        _fake_persisted_block(None),
    ]
    block_repo.list_unresolved_by_exercise.return_value = []

    service = DocumentStructuringService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=block_repo,
        agent_decision_log_repository=AsyncMock(),
        storage_service=_make_storage_mock(),
    )

    report = _FakeReport(
        status="INCOMPLETE",
        sections_created=[{"order": 1, "title": "Exercice 1"}],
        questions_created=[{"order": 1, "statement": "Calculer l'aire", "section_order": 1}],
        correction_blocks_created=[
            {
                "content_type": ExtractionContentType.TEXT,
                "evidence_level": BlockEvidenceLevel.LABEL_EXPLICITE,
                "justification": "Label Q1 explicite.",
                "question_order": 1,
                "section_order": 1,
                "image_crop_path": "crop1.png",
                "structured_content": None,
            },
            {
                "content_type": ExtractionContentType.TEXT,
                "evidence_level": BlockEvidenceLevel.UNRESOLVED_NO_LABEL,
                "justification": "Aucun numéro identifiable.",
                "question_order": None,
                "section_order": None,
                "image_crop_path": "crop2.png",
                "structured_content": None,
            },
        ],
    )

    result = await service.structure_exercise(exercise_id, report)

    exercise_repo.add_structure.assert_awaited_once_with(
        exercise_id=exercise_id,
        sections_data=report.sections_created,
        questions_data=report.questions_created,
    )

    persisted_blocks_data = block_repo.bulk_create_for_exercise.call_args.kwargs["blocks"]
    assert persisted_blocks_data[0]["question_id"] == question_1_id
    assert persisted_blocks_data[1]["question_id"] is None

    assert result.sections_created == 1
    assert result.questions_created == 1
    assert result.blocks_created == 2
    assert result.complete is False  # report.status == "INCOMPLETE"


@pytest.mark.anyio
async def test_structure_exercise_writes_one_decision_log_per_classified_block():
    """Une AgentDecisionLog par bloc classifié (STATEMENT/CORRECTION/AUTRE),
    rattachée à l'exercice (aucun bloc n'a d'UUID propre à la classification),
    model_version = modèle réellement utilisé (fallback "unknown" si absent
    — cas des blocs classifiés AUTRE après échec LLM total)."""
    exercise_id = uuid.uuid4()

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(id=exercise_id)
    exercise_repo.add_structure.return_value = ({}, {})

    block_repo = AsyncMock()
    block_repo.bulk_create_for_exercise.return_value = []
    block_repo.list_unresolved_by_exercise.return_value = []

    decision_log_repo = AsyncMock()

    service = DocumentStructuringService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=block_repo,
        agent_decision_log_repository=decision_log_repo,
        storage_service=_make_storage_mock(),
    )

    report = _FakeReport(
        status="COMPLETE",
        block_classifications=[
            {
                "block_index": 0,
                "classification": "STATEMENT",
                "content_type": ExtractionContentType.TEXT,
                "image_crop_path": "crop0.png",
                "model_used": "groq:llama-3.3-70b",
                "fallback_occurred": False,
                "tokens_used": 120,
                "confidence": 0.9,
                "justification": "Marqueur 'Question 1' explicite.",
            },
            {
                "block_index": 1,
                "classification": "AUTRE",
                "content_type": ExtractionContentType.TEXT,
                "image_crop_path": "crop1.png",
                "model_used": None,
                "fallback_occurred": False,
                "tokens_used": 0,
                "confidence": 0.0,
                "justification": "Échec classification LLM après retry.",
            },
        ],
    )

    await service.structure_exercise(exercise_id, report)

    assert decision_log_repo.create.await_count == 2

    first_call = decision_log_repo.create.call_args_list[0].kwargs
    assert first_call["agent_name"] == "Document_Structuring_Agent"
    assert first_call["related_entity_type"] == "Exercise"
    assert first_call["related_entity_id"] == exercise_id
    assert first_call["justification"] == "Marqueur 'Question 1' explicite."
    assert first_call["model_version"] == "groq:llama-3.3-70b"

    second_call = decision_log_repo.create.call_args_list[1].kwargs
    assert second_call["model_version"] == "unknown"  # fallback, model_used=None


@pytest.mark.anyio
async def test_structure_exercise_unmatched_key_leaves_question_id_none():
    """Un question_order sans correspondance dans question_id_by_key (incohérence
    interne agent/service) ne doit jamais fabriquer un question_id — reste None."""
    exercise_id = uuid.uuid4()

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(id=exercise_id)
    exercise_repo.add_structure.return_value = ({}, {})  # aucune question créée

    block_repo = AsyncMock()
    block_repo.bulk_create_for_exercise.return_value = [_fake_persisted_block(None)]
    block_repo.list_unresolved_by_exercise.return_value = []

    service = DocumentStructuringService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=block_repo,
        agent_decision_log_repository=AsyncMock(),
        storage_service=_make_storage_mock(),
    )

    report = _FakeReport(
        status="INCOMPLETE",
        correction_blocks_created=[
            {
                "content_type": ExtractionContentType.TEXT,
                "evidence_level": BlockEvidenceLevel.LABEL_EXPLICITE,
                "justification": "Label Q1 mais question absente du mapping.",
                "question_order": 1,
                "section_order": 1,
                "image_crop_path": "crop1.png",
                "structured_content": None,
            },
        ],
    )

    await service.structure_exercise(exercise_id, report)

    persisted_blocks_data = block_repo.bulk_create_for_exercise.call_args.kwargs["blocks"]
    assert persisted_blocks_data[0]["question_id"] is None


@pytest.mark.anyio
async def test_list_blocks_for_exercise_success():
    exercise_id = uuid.uuid4()
    professor_id = uuid.uuid4()

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(id=exercise_id, created_by_professor_id=professor_id)

    block_repo = AsyncMock()
    block_repo.list_by_exercise.return_value = [_fake_persisted_block(None)]

    service = DocumentStructuringService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=block_repo,
        agent_decision_log_repository=AsyncMock(),
        storage_service=_make_storage_mock(),
    )

    result = await service.list_blocks_for_exercise(exercise_id, professor_id)

    assert len(result) == 1
    block_repo.list_by_exercise.assert_awaited_once_with(exercise_id)


@pytest.mark.anyio
async def test_list_blocks_for_exercise_not_found():
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = None

    service = DocumentStructuringService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=AsyncMock(),
        agent_decision_log_repository=AsyncMock(),
        storage_service=_make_storage_mock(),
    )

    with pytest.raises(ExerciseNotFoundError):
        await service.list_blocks_for_exercise(uuid.uuid4(), uuid.uuid4())


@pytest.mark.anyio
async def test_list_blocks_for_exercise_rejects_non_owner():
    exercise_id = uuid.uuid4()
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(id=exercise_id, created_by_professor_id=uuid.uuid4())

    service = DocumentStructuringService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=AsyncMock(),
        agent_decision_log_repository=AsyncMock(),
        storage_service=_make_storage_mock(),
    )

    with pytest.raises(NotExerciseOwnerError):
        await service.list_blocks_for_exercise(exercise_id, uuid.uuid4())
