"""
Tests de contestation_verification_node — get_db_context et
ContestationVerificationService mockés (le nœud n'est appelé par rien de
réel aujourd'hui, cf. docstring du module ; ce test vérifie uniquement
qu'il pose correctement status/pending_action/arbitration_required selon
le résultat du service).
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.schemas.contestation_schemas import ContestationVerdict
from app.graph.nodes.contestation_verification_node import contestation_verification_node
from app.graph.state import PipelineState
from app.services.contestation_verification_service import ContestationProcessingResult


class _FakeDbContext:
    async def __aenter__(self):
        return MagicMock()

    async def __aexit__(self, *args):
        return False


def _make_state(submission_id: uuid.UUID) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(submission_id),
        flow_type="student_evaluation",
        trace_id=str(submission_id),
        exercise_id=str(uuid.uuid4()),
        submission_id=str(submission_id),
        module_id=str(uuid.uuid4()),
        raw_file_path="submissions/test/original.pdf",
        created_at=now,
        updated_at=now,
    )


def _verdict(verdict: str) -> ContestationVerdict:
    return ContestationVerdict(
        extraction_correction_id=uuid.uuid4(),
        contestation_type="content",
        verdict=verdict,
        justification="test",
        model_version="test:model",
    )


@pytest.mark.anyio
class TestContestationVerificationNode:
    async def test_ambigu_verdict_pauses_state(self):
        submission_id = uuid.uuid4()
        state = _make_state(submission_id)

        service = AsyncMock()
        service.process_pending_contestations.return_value = ContestationProcessingResult(
            verdicts=[_verdict("PLAUSIBLE"), _verdict("AMBIGU")],
        )

        with (
            patch(
                "app.graph.nodes.contestation_verification_node.get_db_context",
                return_value=_FakeDbContext(),
            ),
            patch(
                "app.graph.nodes.contestation_verification_node.ContestationVerificationService",
                return_value=service,
            ),
        ):
            result = await contestation_verification_node(state)

        assert result.status == "PAUSED"
        assert result.pending_action == "teacher_arbitration"
        assert result.arbitration_required is True

    async def test_flagged_for_manual_review_pauses_state_even_with_no_verdicts(self):
        submission_id = uuid.uuid4()
        state = _make_state(submission_id)

        service = AsyncMock()
        service.process_pending_contestations.return_value = ContestationProcessingResult(
            verdicts=[], flagged_for_manual_review=True,
        )

        with (
            patch(
                "app.graph.nodes.contestation_verification_node.get_db_context",
                return_value=_FakeDbContext(),
            ),
            patch(
                "app.graph.nodes.contestation_verification_node.ContestationVerificationService",
                return_value=service,
            ),
        ):
            result = await contestation_verification_node(state)

        assert result.status == "PAUSED"
        assert result.pending_action == "teacher_arbitration"
        assert result.arbitration_required is True

    async def test_all_resolved_does_not_pause(self):
        submission_id = uuid.uuid4()
        state = _make_state(submission_id)
        state.pending_action = "student_verification"  # valeur précédente, doit être effacée

        service = AsyncMock()
        service.process_pending_contestations.return_value = ContestationProcessingResult(
            verdicts=[_verdict("PLAUSIBLE"), _verdict("IMPLAUSIBLE")],
        )

        with (
            patch(
                "app.graph.nodes.contestation_verification_node.get_db_context",
                return_value=_FakeDbContext(),
            ),
            patch(
                "app.graph.nodes.contestation_verification_node.ContestationVerificationService",
                return_value=service,
            ),
        ):
            result = await contestation_verification_node(state)

        assert result.status == "RUNNING"
        assert result.pending_action is None
        assert result.arbitration_required is False
