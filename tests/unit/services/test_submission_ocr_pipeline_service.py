"""
Tests unitaires pour SubmissionOCRPipelineService.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import OCRExtractionError, SubmissionNotFoundError
from app.domain.models.assessment.extraction_correction import (
    ExtractionContentType,
    ExtractionEvidenceLevel,
    ExtractionOrigin,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.schemas.submission_schemas import AttachedExtractedBlock, RawExtractedBlock
from app.agents.Question_Attachment_Agent import AttachmentDecision, AttachmentResult
from app.services.submission_ocr_pipeline_service import (
    SubmissionOCRPipelineService,
    build_question_refs,
    raw_blocks_to_persistence_dicts,
)


def _make_submission(submission_id: uuid.UUID, student_id: uuid.UUID) -> Submission:
    return Submission(
        id=submission_id,
        exercise_id=uuid.uuid4(),
        student_id=student_id,
        attempt_number=1,
        status=SubmissionStatus.PENDING_OCR,
        document_path="submissions/x/original.pdf",
        document_mime_type="application/pdf",
    )


def _make_raw_block(submission_id: uuid.UUID) -> RawExtractedBlock:
    return RawExtractedBlock(
        image_crop_path=f"submissions/{submission_id}/ocr_crops/page_1_block_1.png",
        content_type=ExtractionContentType.TEXT,
        prediction_ocr="Réponse manuscrite",
        structured_output=None,
        confidence_score=Decimal("0.90"),
        bounding_box={"x": 50, "y": 100, "width": 400, "height": 80},
        page_number=1,
        block_order_index=1,
        origin=ExtractionOrigin.HANDWRITTEN,
        is_struck_through=False,
        evidence_level=ExtractionEvidenceLevel.AMBIGU,
    )


@pytest.mark.anyio
async def test_pipeline_run_success(monkeypatch):
    submission_id = uuid.uuid4()
    exercise_id = uuid.uuid4()
    student_id = uuid.uuid4()
    submission = _make_submission(submission_id, student_id)
    raw_block = _make_raw_block(submission_id)

    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = submission
    extraction_repo = AsyncMock()
    extraction_repo.bulk_create_for_submission.return_value = [MagicMock(question_id=None)]
    ocr_agent = AsyncMock()
    ocr_agent.execute.return_value = [raw_block]
    events = AsyncMock()

    monkeypatch.setattr(
        "app.services.submission_ocr_pipeline_service.storage_service.download",
        AsyncMock(return_value=b"%PDF-1.4"),
    )

    pipeline = SubmissionOCRPipelineService(
        submission_repo=submission_repo,
        extraction_repo=extraction_repo,
        event_publisher=events,
        ocr_agent=ocr_agent,
    )

    result = await pipeline.run(
        submission_id=submission_id,
        exercise_id=exercise_id,
        student_id=student_id,
        document_path=submission.document_path,
        mime_type=submission.document_mime_type,
    )

    assert len(result) == 1
    ocr_agent.execute.assert_awaited_once()
    extraction_repo.bulk_create_for_submission.assert_awaited_once()
    submission_repo.update_status.assert_awaited_once_with(
        submission_id,
        SubmissionStatus.PENDING_STUDENT_VERIFICATION,
    )
    events.publish_extraction_ready.assert_not_awaited()


@pytest.mark.anyio
async def test_pipeline_skips_ocr_and_attachment_when_already_processed():
    """
    Priorité 2 (audit doc restauré, point 2) : IdempotencyService signale un
    redéclenchement (try_mark_processed -> False) — OCR et attachment ne
    sont pas rejoués, aucun événement republié, aucune mise à jour de
    statut ; les blocs existants sont reconstruits depuis ExtractionCorrection.
    """
    submission_id = uuid.uuid4()
    exercise_id = uuid.uuid4()
    student_id = uuid.uuid4()
    submission = _make_submission(submission_id, student_id)

    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = submission
    extraction_repo = AsyncMock()
    existing_correction = MagicMock(
        image_crop_path="submissions/x/ocr_crops/page_1_block_1.png",
        content_type=ExtractionContentType.TEXT,
        prediction_ocr="déjà persisté",
        structured_output=None,
        confidence_score=Decimal("0.80"),
        bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        page_number=1,
        evidence_level=ExtractionEvidenceLevel.AMBIGU,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    extraction_repo.get_by_submission_id.return_value = [existing_correction]
    ocr_agent = AsyncMock()
    events = AsyncMock()
    idempotency_service = AsyncMock()
    idempotency_service.try_mark_processed.return_value = False  # déjà traité

    pipeline = SubmissionOCRPipelineService(
        submission_repo=submission_repo,
        extraction_repo=extraction_repo,
        event_publisher=events,
        ocr_agent=ocr_agent,
        idempotency_service=idempotency_service,
    )

    result = await pipeline.run(
        submission_id=submission_id,
        exercise_id=exercise_id,
        student_id=student_id,
        document_path=submission.document_path,
        mime_type=submission.document_mime_type,
    )

    ocr_agent.execute.assert_not_awaited()
    extraction_repo.bulk_create_for_submission.assert_not_awaited()
    submission_repo.update_status.assert_not_awaited()
    events.publish_extraction_ready.assert_not_awaited()
    assert len(result) == 1
    assert result[0].prediction_ocr == "déjà persisté"


@pytest.mark.anyio
async def test_pipeline_raises_when_submission_not_found():
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = None
    pipeline = SubmissionOCRPipelineService(
        submission_repo=submission_repo,
        extraction_repo=AsyncMock(),
    )

    with pytest.raises(SubmissionNotFoundError):
        await pipeline.run(
            submission_id=uuid.uuid4(),
            exercise_id=uuid.uuid4(),
            student_id=uuid.uuid4(),
            document_path="submissions/x/original.pdf",
            mime_type="application/pdf",
        )


@pytest.mark.anyio
async def test_pipeline_raises_when_no_document():
    submission_id = uuid.uuid4()
    student_id = uuid.uuid4()
    submission = _make_submission(submission_id, student_id)
    submission.document_path = None
    submission.document_mime_type = None

    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = submission
    pipeline = SubmissionOCRPipelineService(
        submission_repo=submission_repo,
        extraction_repo=AsyncMock(),
    )

    with pytest.raises(OCRExtractionError):
        await pipeline.run(
            submission_id=submission_id,
            exercise_id=uuid.uuid4(),
            student_id=student_id,
            document_path="",
            mime_type="",
        )


@pytest.mark.anyio
async def test_build_question_refs_computes_position_in_section_per_section():
    """Priorité 1 (audit doc restauré, point 1) : position_in_section est
    calculée par section, indépendamment de Question.order (global à
    l'exercice) — repart à 1 pour chaque nouvelle section."""
    section1_id = uuid.uuid4()
    section2_id = uuid.uuid4()
    exercise_id = uuid.uuid4()

    # Section 1 : 3 questions (order global 1,2,3) ; Section 2 : 2 questions (order global 4,5)
    q1 = MagicMock(id=uuid.uuid4(), order=1, statement="S1Q1", section_id=section1_id)
    q2 = MagicMock(id=uuid.uuid4(), order=2, statement="S1Q2", section_id=section1_id)
    q3 = MagicMock(id=uuid.uuid4(), order=3, statement="S1Q3", section_id=section1_id)
    q4 = MagicMock(id=uuid.uuid4(), order=4, statement="S2Q1", section_id=section2_id)
    q5 = MagicMock(id=uuid.uuid4(), order=5, statement="S2Q2", section_id=section2_id)

    exercise = MagicMock(
        id=exercise_id,
        questions=[q1, q2, q3, q4, q5],
        sections=[
            MagicMock(id=section1_id, order=1),
            MagicMock(id=section2_id, order=2),
        ],
    )

    variant_repo = AsyncMock()
    variant_repo.list_by_question.return_value = [
        MagicMock(is_reference=True, content="référence", reasoning_summary=None)
    ]

    refs = await build_question_refs(exercise, variant_repo)

    by_order = {r.order: r for r in refs}
    assert by_order[1].position_in_section == 1  # S1Q1
    assert by_order[2].position_in_section == 2  # S1Q2
    assert by_order[3].position_in_section == 3  # S1Q3
    assert by_order[4].position_in_section == 1  # S2Q1 — repart à 1, order global pourtant 4
    assert by_order[5].position_in_section == 2  # S2Q2


def test_raw_blocks_to_persistence_dicts_normalizes_latex_string():
    block = RawExtractedBlock(
        image_crop_path="submissions/x/ocr_crops/page_1_block_1.png",
        content_type=ExtractionContentType.EQUATION,
        prediction_ocr="x^2",
        structured_output="x^2",
        confidence_score=Decimal("0.95"),
        bounding_box={"x": 0, "y": 0, "width": 10, "height": 10},
        page_number=1,
        block_order_index=1,
        evidence_level=ExtractionEvidenceLevel.AMBIGU,
    )
    rows = raw_blocks_to_persistence_dicts([block])
    assert rows[0]["structured_output"] == {"latex": "x^2"}
    assert rows[0]["question_id"] is None


@pytest.mark.anyio
async def test_pipeline_runs_attachment_when_references_available(monkeypatch):
    submission_id = uuid.uuid4()
    exercise_id = uuid.uuid4()
    student_id = uuid.uuid4()
    question_id = uuid.uuid4()
    submission = _make_submission(submission_id, student_id)
    submission.exercise_id = exercise_id
    raw_block = _make_raw_block(submission_id)

    attached = AttachedExtractedBlock(
        **raw_block.model_dump(exclude={"evidence_level"}),
        submission_id=submission_id,
        question_id=question_id,
        evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
    )

    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = submission
    extraction_repo = AsyncMock()
    correction = MagicMock(
        id=uuid.uuid4(),
        question_id=question_id,
        image_crop_path=raw_block.image_crop_path,
    )
    extraction_repo.get_by_submission_id.return_value = [correction]
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(
        id=exercise_id,
        questions=[MagicMock(id=question_id, order=1, statement="Q1", section_id=None)],
        sections=[],
    )
    variant_repo = AsyncMock()
    variant_repo.list_by_question.return_value = [
        MagicMock(is_reference=True, content="référence", reasoning_summary=None)
    ]
    ocr_agent = AsyncMock()
    ocr_agent.execute.return_value = [raw_block]
    attachment_agent = AsyncMock()
    decision = AttachmentDecision(
        image_crop_path=raw_block.image_crop_path,
        question_id=question_id,
        evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
        justification="Label étudiant reconnu.",
        model_version="deterministic:level1_label_match",
        confidence_score=0.95,
        level_used=1,
    )
    attachment_agent.execute.return_value = AttachmentResult(
        attached_blocks=[attached], decisions=[decision]
    )
    events = AsyncMock()

    monkeypatch.setattr(
        "app.services.submission_ocr_pipeline_service.storage_service.download",
        AsyncMock(return_value=b"%PDF-1.4"),
    )
    monkeypatch.setattr(
        "app.services.submission_ocr_pipeline_service.build_question_refs",
        AsyncMock(return_value=[MagicMock()]),
    )

    pipeline = SubmissionOCRPipelineService(
        submission_repo=submission_repo,
        extraction_repo=extraction_repo,
        exercise_repo=exercise_repo,
        variant_repo=variant_repo,
        event_publisher=events,
        ocr_agent=ocr_agent,
        attachment_agent=attachment_agent,
    )

    await pipeline.run(
        submission_id=submission_id,
        exercise_id=exercise_id,
        student_id=student_id,
        document_path=submission.document_path,
        mime_type=submission.document_mime_type,
    )

    attachment_agent.execute.assert_awaited_once()
    extraction_repo.bulk_update_attachments.assert_awaited_once()
    events.publish_extraction_ready.assert_awaited_once()


@pytest.mark.anyio
async def test_pipeline_records_agent_decision_log_per_attached_block(monkeypatch):
    """
    Priorité 1 (audit) : une AgentDecisionLog par bloc non filtré, rattachée
    au vrai UUID de l'ExtractionCorrection (pas à submission_id/exercise_id).
    """
    submission_id = uuid.uuid4()
    exercise_id = uuid.uuid4()
    student_id = uuid.uuid4()
    question_id = uuid.uuid4()
    correction_id = uuid.uuid4()
    submission = _make_submission(submission_id, student_id)
    submission.exercise_id = exercise_id
    raw_block = _make_raw_block(submission_id)

    attached = AttachedExtractedBlock(
        **raw_block.model_dump(exclude={"evidence_level"}),
        submission_id=submission_id,
        question_id=question_id,
        evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
    )
    decision = AttachmentDecision(
        image_crop_path=raw_block.image_crop_path,
        question_id=question_id,
        evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
        justification="Label étudiant 'Q1' reconnu.",
        model_version="deterministic:level1_label_match",
        confidence_score=0.95,
        level_used=1,
    )

    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = submission
    extraction_repo = AsyncMock()
    persisted_correction = MagicMock(id=correction_id, image_crop_path=raw_block.image_crop_path)
    extraction_repo.bulk_update_attachments.return_value = [persisted_correction]
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(
        id=exercise_id,
        questions=[MagicMock(id=question_id, order=1, statement="Q1", section_id=None)],
        sections=[],
    )
    variant_repo = AsyncMock()
    variant_repo.list_by_question.return_value = [
        MagicMock(is_reference=True, content="référence", reasoning_summary=None)
    ]
    ocr_agent = AsyncMock()
    ocr_agent.execute.return_value = [raw_block]
    attachment_agent = AsyncMock()
    attachment_agent.execute.return_value = AttachmentResult(
        attached_blocks=[attached], decisions=[decision]
    )
    decision_log_repo = AsyncMock()

    monkeypatch.setattr(
        "app.services.submission_ocr_pipeline_service.storage_service.download",
        AsyncMock(return_value=b"%PDF-1.4"),
    )
    monkeypatch.setattr(
        "app.services.submission_ocr_pipeline_service.build_question_refs",
        AsyncMock(return_value=[MagicMock()]),
    )

    pipeline = SubmissionOCRPipelineService(
        submission_repo=submission_repo,
        extraction_repo=extraction_repo,
        exercise_repo=exercise_repo,
        variant_repo=variant_repo,
        event_publisher=AsyncMock(),
        ocr_agent=ocr_agent,
        attachment_agent=attachment_agent,
        decision_log_repo=decision_log_repo,
    )

    await pipeline.run(
        submission_id=submission_id,
        exercise_id=exercise_id,
        student_id=student_id,
        document_path=submission.document_path,
        mime_type=submission.document_mime_type,
    )

    decision_log_repo.create.assert_awaited_once()
    call_kwargs = decision_log_repo.create.await_args.kwargs
    assert call_kwargs["agent_name"] == "Question_Attachment_Agent"
    assert call_kwargs["related_entity_type"] == "ExtractionCorrection"
    assert call_kwargs["related_entity_id"] == correction_id
    assert call_kwargs["model_version"] == "deterministic:level1_label_match"
    assert call_kwargs["justification"] == "Label étudiant 'Q1' reconnu."
