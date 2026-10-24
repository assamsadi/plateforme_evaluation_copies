"""
Tests de ContestationVerificationService.process_pending_contestations —
repos et agent mockés en AsyncMock (même pattern que test_arbitration_service.py).
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.context import AgentExecutionContext
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
    ExtractionContentType,
    ExtractionCorrection,
    ExtractionEvidenceLevel,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.system_infrastructure.integrity_alert import IntegrityTriggerType
from app.domain.schemas.contestation_schemas import ContestationVerdict
from app.services.contestation_verification_service import ContestationVerificationService


def _make_submission(submission_id, exercise_id, student_id) -> Submission:
    return Submission(
        id=submission_id,
        exercise_id=exercise_id,
        student_id=student_id,
        attempt_number=1,
        status=SubmissionStatus.PENDING_EVALUATION,
        document_path=None,
        document_mime_type=None,
    )


def _make_block(
    submission_id,
    contestation_type=ContestationType.CONTENT,
    contestation_status=ContestationStatus.PENDING_VERIFICATION,
    human_correction="réclamation étudiant",
) -> ExtractionCorrection:
    return ExtractionCorrection(
        id=uuid.uuid4(),
        submission_id=submission_id,
        question_id=uuid.uuid4(),
        image_crop_path="submissions/test/crop.png",
        page_number=1,
        content_type=ExtractionContentType.TEXT,
        prediction_ocr="texte extrait",
        human_correction=human_correction,
        confidence_score=Decimal("0.400"),
        bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
        evidence_level=ExtractionEvidenceLevel.AMBIGU,
        contestation_type=contestation_type,
        contestation_status=contestation_status,
    )


def _make_service(
    extraction_correction_repo=None,
    correction_arbitration_repo=None,
    submission_repo=None,
    exercise_repo=None,
    solution_variant_repo=None,
    decision_log_repo=None,
    integrity_alert_repo=None,
    agent=None,
) -> ContestationVerificationService:
    return ContestationVerificationService(
        extraction_correction_repo=extraction_correction_repo or AsyncMock(),
        correction_arbitration_repo=correction_arbitration_repo or AsyncMock(),
        submission_repo=submission_repo or AsyncMock(),
        exercise_repo=exercise_repo or AsyncMock(),
        solution_variant_repo=solution_variant_repo or AsyncMock(),
        decision_log_repo=decision_log_repo or AsyncMock(),
        integrity_alert_repo=integrity_alert_repo or AsyncMock(),
        agent=agent,
    )


def _context() -> AgentExecutionContext:
    return AgentExecutionContext(trace_id="t1", flow_type="student_evaluation")


def _non_pending_block(submission_id) -> ExtractionCorrection:
    """
    Bloc non contesté, à ajouter aux fixtures de test qui exercent réellement
    l'agent (au-delà de la simple lecture) — sans lui, un seul bloc pending
    sur un seul bloc total donne un ratio de 100%, qui déclenche le
    garde-fou anti-abus (§8) avant même d'atteindre le code testé.
    """
    return _make_block(submission_id, contestation_status=ContestationStatus.RESOLVED)


def _verdict(block: ExtractionCorrection, verdict: str, **kwargs) -> ContestationVerdict:
    return ContestationVerdict(
        extraction_correction_id=block.id,
        contestation_type=block.contestation_type,
        verdict=verdict,
        justification="justification test",
        model_version="test:model",
        **kwargs,
    )


@pytest.mark.anyio
class TestProcessPendingContestationsNoOp:
    async def test_no_submission_returns_empty(self):
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = None
        service = _make_service(submission_repo=submission_repo)

        result = await service.process_pending_contestations(uuid.uuid4(), _context())

        assert result.verdicts == []
        assert result.flagged_for_manual_review is False

    async def test_no_pending_blocks_returns_empty_without_calling_agent(self):
        submission_id, exercise_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, exercise_id, student_id)

        extraction_repo = AsyncMock()
        resolved_block = _make_block(submission_id, contestation_status=ContestationStatus.RESOLVED)
        extraction_repo.get_by_submission_id.return_value = [resolved_block]

        agent = AsyncMock()
        service = _make_service(
            submission_repo=submission_repo, extraction_correction_repo=extraction_repo, agent=agent,
        )

        result = await service.process_pending_contestations(submission_id, _context())

        assert result.verdicts == []
        assert result.flagged_for_manual_review is False
        agent.execute.assert_not_awaited()


@pytest.mark.anyio
class TestAbuseThreshold:
    async def test_exceeds_threshold_creates_integrity_alert_and_skips_agent(self):
        submission_id, exercise_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, exercise_id, student_id)

        # 6 blocs sur 10 contestés (60% > seuil 50%, §8).
        pending = [_make_block(submission_id) for _ in range(6)]
        untouched = [
            _make_block(submission_id, contestation_status=ContestationStatus.RESOLVED) for _ in range(4)
        ]
        extraction_repo = AsyncMock()
        extraction_repo.get_by_submission_id.return_value = pending + untouched

        integrity_repo = AsyncMock()
        agent = AsyncMock()
        service = _make_service(
            submission_repo=submission_repo,
            extraction_correction_repo=extraction_repo,
            integrity_alert_repo=integrity_repo,
            agent=agent,
        )

        result = await service.process_pending_contestations(submission_id, _context())

        assert result.verdicts == []
        assert result.flagged_for_manual_review is True
        agent.execute.assert_not_awaited()
        integrity_repo.create.assert_awaited_once()
        call_kwargs = integrity_repo.create.call_args.kwargs
        assert call_kwargs["student_id"] == student_id
        assert call_kwargs["trigger_type"] == IntegrityTriggerType.SYSTEMATIC_CONTESTATION
        assert call_kwargs["auto_generated"] is True


@pytest.mark.anyio
class TestAmbiguVerdictPersistence:
    async def test_ambigu_creates_pending_arbitration_and_pauses_submission(self):
        submission_id, exercise_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, exercise_id, student_id)

        block = _make_block(submission_id)
        extraction_repo = AsyncMock()
        extraction_repo.get_by_submission_id.return_value = [block, _non_pending_block(submission_id)]

        agent = AsyncMock()
        agent.execute.return_value = _verdict(block, "AMBIGU")

        arbitration_repo = AsyncMock()
        decision_log_repo = AsyncMock()
        service = _make_service(
            submission_repo=submission_repo,
            extraction_correction_repo=extraction_repo,
            correction_arbitration_repo=arbitration_repo,
            decision_log_repo=decision_log_repo,
            agent=agent,
        )

        result = await service.process_pending_contestations(submission_id, _context())

        assert len(result.verdicts) == 1
        assert result.flagged_for_manual_review is False
        arbitration_repo.create_pending.assert_awaited_once_with(block.id)
        submission_repo.update_status.assert_awaited_once_with(
            submission_id, SubmissionStatus.PENDING_ARBITRATION
        )
        extraction_repo.apply_contestation_verdict.assert_awaited_once()
        apply_kwargs = extraction_repo.apply_contestation_verdict.call_args.kwargs
        assert apply_kwargs["contestation_status"] == ContestationStatus.AMBIGU
        assert apply_kwargs["confidence_score"] is None
        decision_log_repo.create.assert_awaited_once()


@pytest.mark.anyio
class TestPlausibleVerdictPersistence:
    async def test_plausible_content_applies_verdict_without_arbitration(self):
        submission_id, exercise_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, exercise_id, student_id)

        block = _make_block(submission_id)
        extraction_repo = AsyncMock()
        extraction_repo.get_by_submission_id.return_value = [block, _non_pending_block(submission_id)]

        agent = AsyncMock()
        agent.execute.return_value = _verdict(
            block, "PLAUSIBLE", verified_content="réponse confirmée", confidence_score=0.93,
        )

        arbitration_repo = AsyncMock()
        decision_log_repo = AsyncMock()
        service = _make_service(
            submission_repo=submission_repo,
            extraction_correction_repo=extraction_repo,
            correction_arbitration_repo=arbitration_repo,
            decision_log_repo=decision_log_repo,
            agent=agent,
        )

        await service.process_pending_contestations(submission_id, _context())

        arbitration_repo.create_pending.assert_not_awaited()
        submission_repo.update_status.assert_not_awaited()
        extraction_repo.apply_contestation_verdict.assert_awaited_once_with(
            correction_id=block.id,
            contestation_status=ContestationStatus.PLAUSIBLE,
            verified_content="réponse confirmée",
            confidence_score=Decimal("0.930"),
        )
        decision_log_repo.create.assert_awaited_once()
        assert decision_log_repo.create.call_args.kwargs["confidence_score"] == Decimal("0.930")


@pytest.mark.anyio
class TestFusionVerdictRouting:
    async def test_fusion_verdict_uses_apply_fusion_verdict(self):
        submission_id, exercise_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, exercise_id, student_id)

        block = _make_block(submission_id, contestation_type=ContestationType.FUSION)
        other_id = uuid.uuid4()
        extraction_repo = AsyncMock()
        extraction_repo.get_by_submission_id.return_value = [block, _non_pending_block(submission_id)]

        agent = AsyncMock()
        agent.execute.return_value = _verdict(
            block, "IMPLAUSIBLE",
            fused_correction_ids=[block.id, other_id],
            defusion_applied=False,
            confidence_score=0.95,
        )

        service = _make_service(
            submission_repo=submission_repo, extraction_correction_repo=extraction_repo, agent=agent,
        )

        await service.process_pending_contestations(submission_id, _context())

        extraction_repo.apply_fusion_verdict.assert_awaited_once_with(
            group_ids=[block.id, other_id],
            defusion_applied=False,
            contestation_status=ContestationStatus.IMPLAUSIBLE,
            confidence_score=Decimal("0.950"),
        )
        extraction_repo.apply_contestation_verdict.assert_not_awaited()


@pytest.mark.anyio
class TestBatchPriorityOrdering:
    async def test_fusion_block_processed_before_content_block(self):
        submission_id, exercise_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, exercise_id, student_id)

        content_block = _make_block(submission_id, contestation_type=ContestationType.CONTENT)
        fusion_block = _make_block(submission_id, contestation_type=ContestationType.FUSION)
        extraction_repo = AsyncMock()
        # Volontairement dans l'ordre CONTENT puis FUSION, pour vérifier que
        # le service les retraite bien (§9ter, niveau lot).
        extraction_repo.get_by_submission_id.return_value = [
            content_block, fusion_block,
            _non_pending_block(submission_id), _non_pending_block(submission_id),
        ]

        call_order: list[uuid.UUID] = []

        async def fake_execute(case, context):
            call_order.append(case.contested.id)
            return ContestationVerdict(
                extraction_correction_id=case.contested.id,
                contestation_type=case.request.contestation_type,
                verdict="IMPLAUSIBLE",
                justification="justification test",
                model_version="test:model",
            )

        agent = AsyncMock()
        agent.execute.side_effect = fake_execute

        service = _make_service(
            submission_repo=submission_repo, extraction_correction_repo=extraction_repo, agent=agent,
        )

        await service.process_pending_contestations(submission_id, _context())

        assert call_order == [fusion_block.id, content_block.id]


@pytest.mark.anyio
class TestBuildQuestionCandidatesPositionInSection:
    """
    Même bug de fond corrigé sur Question_Attachment_Agent (audit doc
    restauré) : Contestation_Verification_Agent._build_label_variants
    utilisait Question.order (global à l'exercice) au lieu de la position
    dans la section — corrigé ici avec la même approche (position_in_section
    calculée par section, indépendante de l'ordre global).
    """

    async def test_position_in_section_computed_per_section_not_global_order(self):
        section1_id = uuid.uuid4()
        section2_id = uuid.uuid4()
        exercise_id = uuid.uuid4()

        # Section 1 : 3 questions (order global 1,2,3) ; Section 2 : 2 questions (order global 4,5)
        q1 = MagicMock(id=uuid.uuid4(), order=1, section_id=section1_id)
        q2 = MagicMock(id=uuid.uuid4(), order=2, section_id=section1_id)
        q3 = MagicMock(id=uuid.uuid4(), order=3, section_id=section1_id)
        q4 = MagicMock(id=uuid.uuid4(), order=4, section_id=section2_id)
        q5 = MagicMock(id=uuid.uuid4(), order=5, section_id=section2_id)

        exercise = MagicMock(
            id=exercise_id,
            questions=[q1, q2, q3, q4, q5],
            sections=[
                MagicMock(id=section1_id, order=1, title="Section 1"),
                MagicMock(id=section2_id, order=2, title="Section 2"),
            ],
        )

        exercise_repo = AsyncMock()
        exercise_repo.get_by_id.return_value = exercise
        variant_repo = AsyncMock()
        variant_repo.list_by_question.return_value = []

        service = _make_service(exercise_repo=exercise_repo, solution_variant_repo=variant_repo)

        candidates = await service._build_question_candidates(exercise_id)

        by_order = {c.order: c for c in candidates}
        assert by_order[1].position_in_section == 1  # S1Q1
        assert by_order[2].position_in_section == 2  # S1Q2
        assert by_order[3].position_in_section == 3  # S1Q3
        assert by_order[4].position_in_section == 1  # S2Q1 — repart à 1, order global pourtant 4
        assert by_order[5].position_in_section == 2  # S2Q2
