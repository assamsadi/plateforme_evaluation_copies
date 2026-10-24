import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AppealNotFoundError
from app.domain.models.assessment.grade_appeal import AppealResolution, GradeAppeal
from app.domain.repositories.pagination import CursorPage
from app.services.grade_appeal_service import GradeAppealService


def _make_appeal(
    appeal_id: uuid.UUID, submission_id: uuid.UUID, student_id: uuid.UUID
) -> GradeAppeal:
    now = datetime.now(timezone.utc)
    return GradeAppeal(
        id=appeal_id,
        submission_id=submission_id,
        evaluation_id=None,
        extraction_correction_id=None,
        student_id=student_id,
        reason="Note contestée",
        original_score=Decimal("8"),
        status="pending",
        resolution=None,
        revised_score=None,
        resolved_by_professor_id=None,
        review_comment=None,
        resolved_at=None,
        escalated_to_admin_id=None,
        ai_reevaluation_score=None,
        ai_reevaluation_justification=None,
        ai_reevaluation_criteria=None,
        created_at=now,
        updated_at=now,
    )


def _make_student(student_id: uuid.UUID) -> MagicMock:
    s = MagicMock()
    s.id = student_id
    s.first_name = "Alice"
    s.last_name = "Dupont"
    return s


def _make_service(appeal_repo=None, evaluation_repo=None, user_repo=None) -> GradeAppealService:
    return GradeAppealService(
        appeal_repo or AsyncMock(),
        evaluation_repo or AsyncMock(),
        user_repo or AsyncMock(),
    )


@pytest.mark.anyio
async def test_file_appeal_success():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    std_id = uuid.uuid4()
    appeal = _make_appeal(aid, sid, std_id)

    appeal_repo = AsyncMock()
    appeal_repo.create.return_value = appeal

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(std_id)

    service = _make_service(appeal_repo=appeal_repo, user_repo=user_repo)
    result = await service.file_appeal(sid, std_id, "Note contestée")

    assert result.id == aid
    assert result.student_id == std_id
    assert result.student_full_name == "Alice Dupont"
    assert result.original_score == Decimal("8")
    appeal_repo.create.assert_awaited_once_with(
        submission_id=sid,
        student_id=std_id,
        reason="Note contestée",
        evaluation_id=None,
        extraction_correction_id=None,
    )


@pytest.mark.anyio
async def test_file_appeal_with_evaluation_id():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    std_id = uuid.uuid4()
    ev_id = uuid.uuid4()
    appeal = _make_appeal(aid, sid, std_id)
    appeal.evaluation_id = ev_id

    appeal_repo = AsyncMock()
    appeal_repo.create.return_value = appeal

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(std_id)

    service = _make_service(appeal_repo=appeal_repo, user_repo=user_repo)
    result = await service.file_appeal(sid, std_id, "Note contestée", evaluation_id=ev_id)

    assert result.evaluation_id == ev_id
    appeal_repo.create.assert_awaited_once_with(
        submission_id=sid,
        student_id=std_id,
        reason="Note contestée",
        evaluation_id=ev_id,
        extraction_correction_id=None,
    )


@pytest.mark.anyio
async def test_file_appeal_student_unknown():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    std_id = uuid.uuid4()
    appeal = _make_appeal(aid, sid, std_id)

    appeal_repo = AsyncMock()
    appeal_repo.create.return_value = appeal

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = None

    service = _make_service(appeal_repo=appeal_repo, user_repo=user_repo)
    result = await service.file_appeal(sid, std_id, "Note contestée")

    assert result.student_full_name == "Unknown"


@pytest.mark.anyio
async def test_record_ai_reevaluation_success():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    std_id = uuid.uuid4()
    appeal = _make_appeal(aid, sid, std_id)
    appeal.ai_reevaluation_score = Decimal("9")
    appeal.ai_reevaluation_justification = "Correction plus juste"
    appeal.ai_reevaluation_criteria = [{"criterion": "exactitude", "score": 90, "justification": "Ok"}]

    appeal_repo = AsyncMock()
    appeal_repo.record_ai_reevaluation.return_value = appeal

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(std_id)

    service = _make_service(appeal_repo=appeal_repo, user_repo=user_repo)
    result = await service.record_ai_reevaluation(aid, Decimal("9"), "Correction plus juste", [])

    assert result.ai_reevaluation_score == Decimal("9")
    appeal_repo.record_ai_reevaluation.assert_awaited_once_with(
        appeal_id=aid, score=Decimal("9"), justification="Correction plus juste", criteria=[]
    )


@pytest.mark.anyio
async def test_record_ai_reevaluation_not_found():
    aid = uuid.uuid4()
    appeal_repo = AsyncMock()
    appeal_repo.record_ai_reevaluation.return_value = None

    service = _make_service(appeal_repo=appeal_repo)
    with pytest.raises(AppealNotFoundError):
        await service.record_ai_reevaluation(aid, Decimal("9"), "Justif", [])


@pytest.mark.anyio
async def test_resolve_appeal_success():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    std_id = uuid.uuid4()
    professor_id = uuid.uuid4()
    appeal = _make_appeal(aid, sid, std_id)
    appeal.resolution = AppealResolution.GRADE_REVISED
    appeal.revised_score = Decimal("9.5")
    appeal.review_comment = "Révisé après analyse"

    appeal_repo = AsyncMock()
    appeal_repo.resolve.return_value = appeal

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(std_id)

    service = _make_service(appeal_repo=appeal_repo, user_repo=user_repo)
    result = await service.resolve_appeal(
        aid, professor_id, AppealResolution.GRADE_REVISED, "Révisé après analyse", Decimal("9.5")
    )

    assert result.resolution == AppealResolution.GRADE_REVISED
    assert result.revised_score == Decimal("9.5")
    appeal_repo.resolve.assert_awaited_once_with(
        appeal_id=aid,
        requesting_professor_id=professor_id,
        resolution=AppealResolution.GRADE_REVISED,
        review_comment="Révisé après analyse",
        revised_score=Decimal("9.5"),
    )


@pytest.mark.anyio
async def test_resolve_appeal_not_found():
    aid = uuid.uuid4()
    appeal_repo = AsyncMock()
    appeal_repo.resolve.return_value = None

    service = _make_service(appeal_repo=appeal_repo)
    with pytest.raises(AppealNotFoundError):
        await service.resolve_appeal(aid, uuid.uuid4(), AppealResolution.GRADE_UPHELD, None)


@pytest.mark.anyio
async def test_escalate_to_admin_success():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    std_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    appeal = _make_appeal(aid, sid, std_id)
    appeal.escalated_to_admin_id = admin_id

    appeal_repo = AsyncMock()
    appeal_repo.escalate.return_value = appeal

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(std_id)

    service = _make_service(appeal_repo=appeal_repo, user_repo=user_repo)
    result = await service.escalate_to_admin(aid, admin_id)

    # GradeAppealRead n'expose pas escalated_to_admin_id (champ interne) —
    # on vérifie la délégation au repository et le retour du DTO.
    assert result.id == aid
    assert result.student_full_name == "Alice Dupont"
    appeal_repo.escalate.assert_awaited_once_with(appeal_id=aid, admin_id=admin_id)


@pytest.mark.anyio
async def test_escalate_to_admin_not_found():
    aid = uuid.uuid4()
    appeal_repo = AsyncMock()
    appeal_repo.escalate.return_value = None

    service = _make_service(appeal_repo=appeal_repo)
    with pytest.raises(AppealNotFoundError):
        await service.escalate_to_admin(aid, uuid.uuid4())


@pytest.mark.anyio
async def test_list_pending_for_professor_success():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    std_id = uuid.uuid4()
    professor_id = uuid.uuid4()
    appeal = _make_appeal(aid, sid, std_id)

    appeal_repo = AsyncMock()
    appeal_repo.list_pending_for_professor.return_value = CursorPage(
        items=[appeal], next_cursor=None, has_more=False
    )

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(std_id)

    service = _make_service(appeal_repo=appeal_repo, user_repo=user_repo)
    result = await service.list_pending_for_professor(professor_id)

    assert len(result.items) == 1
    assert result.items[0].id == aid
    assert result.items[0].student_full_name == "Alice Dupont"
    appeal_repo.list_pending_for_professor.assert_awaited_once_with(professor_id, cursor=None, limit=50)


@pytest.mark.anyio
class TestListBySubmissionForStudent:
    """Gap fermé : aucune lecture étudiante n'existait avant pour revoir le statut d'une contestation déposée."""

    async def test_returns_only_own_appeals(self):
        sid = uuid.uuid4()
        own_student_id = uuid.uuid4()
        other_student_id = uuid.uuid4()
        own_appeal = _make_appeal(uuid.uuid4(), sid, own_student_id)
        other_appeal = _make_appeal(uuid.uuid4(), sid, other_student_id)

        appeal_repo = AsyncMock()
        appeal_repo.list_by_submission.return_value = [own_appeal, other_appeal]
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = _make_student(own_student_id)

        service = _make_service(appeal_repo=appeal_repo, user_repo=user_repo)
        result = await service.list_by_submission_for_student(sid, own_student_id)

        assert len(result) == 1
        assert result[0].student_id == own_student_id
        appeal_repo.list_by_submission.assert_awaited_once_with(sid)

    async def test_no_appeals_returns_empty(self):
        sid = uuid.uuid4()
        student_id = uuid.uuid4()
        appeal_repo = AsyncMock()
        appeal_repo.list_by_submission.return_value = []

        service = _make_service(appeal_repo=appeal_repo)
        result = await service.list_by_submission_for_student(sid, student_id)

        assert result == []