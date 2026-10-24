import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import AlertNotFoundError
from app.domain.models.system_infrastructure.integrity_alert import (
    IntegrityActionTaken,
    IntegrityAlert,
    IntegrityAlertStatus,
    IntegrityTriggerType,
)
from app.services.integrity_service import IntegrityService


def _make_alert(
    alert_id: uuid.UUID,
    student_id: uuid.UUID,
    trigger_type: IntegrityTriggerType = IntegrityTriggerType.MANUAL_FLAG,
    status: IntegrityAlertStatus = IntegrityAlertStatus.PENDING,
) -> IntegrityAlert:
    now = datetime.now(timezone.utc)
    return IntegrityAlert(
        id=alert_id,
        student_id=student_id,
        trigger_type=trigger_type,
        auto_generated=False,
        evidence={},
        reason="Plagiat suspecté",
        status=status,
        action_taken=None,
        reviewed_by_user_id=None,
        review_notes=None,
        reviewed_at=None,
        created_at=now,
        updated_at=now,
    )


def _make_student(student_id: uuid.UUID) -> MagicMock:
    s = MagicMock()
    s.id = student_id
    s.first_name = "Alice"
    s.last_name = "Dupont"
    return s


def _make_service(integrity_repo=None, user_repo=None) -> IntegrityService:
    return IntegrityService(
        integrity_repo or AsyncMock(),
        user_repo or AsyncMock(),
    )


@pytest.mark.anyio
async def test_flag_student_success():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    alert = _make_alert(aid, sid, trigger_type=IntegrityTriggerType.SUSPECTED_PLAGIARISM)
    alert.evidence = {"similarity_score": 0.92}

    integrity_repo = AsyncMock()
    integrity_repo.create.return_value = alert

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(integrity_repo=integrity_repo, user_repo=user_repo)
    result = await service.flag_student(
        sid, IntegrityTriggerType.SUSPECTED_PLAGIARISM, "Plagiat suspecté", {"similarity_score": 0.92}
    )

    assert result.id == aid
    assert result.student_id == sid
    assert result.student_full_name == "Alice Dupont"
    assert result.trigger_type == IntegrityTriggerType.SUSPECTED_PLAGIARISM
    assert result.evidence == {"similarity_score": 0.92}
    integrity_repo.create.assert_awaited_once_with(
        student_id=sid,
        trigger_type=IntegrityTriggerType.SUSPECTED_PLAGIARISM,
        reason="Plagiat suspecté",
        auto_generated=False,
        evidence={"similarity_score": 0.92},
    )


@pytest.mark.anyio
async def test_flag_student_auto_generated_flag():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    alert = _make_alert(aid, sid, trigger_type=IntegrityTriggerType.HIGH_REJECTION_RATE)
    alert.auto_generated = True

    integrity_repo = AsyncMock()
    integrity_repo.create.return_value = alert

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(integrity_repo=integrity_repo, user_repo=user_repo)
    result = await service.flag_student(
        sid, IntegrityTriggerType.HIGH_REJECTION_RATE, "Taux de rejet anormal", None, auto_generated=True
    )

    assert result.auto_generated is True
    call_kwargs = integrity_repo.create.await_args.kwargs
    assert call_kwargs["auto_generated"] is True
    # Bug corrigé (audit espace admin) : evidence=None atteignait IntegrityAlert.evidence
    # (colonne JSONB nullable=False) tel quel — jamais détecté faute d'appelant réel avant.
    assert call_kwargs["evidence"] == {}


@pytest.mark.anyio
async def test_review_alert_success():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    review_user = uuid.uuid4()
    alert = _make_alert(aid, sid, status=IntegrityAlertStatus.CONFIRMED)
    alert.action_taken = IntegrityActionTaken.WARNING_ISSUED
    alert.reviewed_by_user_id = review_user
    alert.review_notes = "Avertissement envoyé"

    integrity_repo = AsyncMock()
    integrity_repo.review.return_value = alert

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(integrity_repo=integrity_repo, user_repo=user_repo)
    result = await service.review_alert(
        aid, review_user, IntegrityAlertStatus.CONFIRMED, IntegrityActionTaken.WARNING_ISSUED, "Avertissement envoyé"
    )

    assert result.status == IntegrityAlertStatus.CONFIRMED
    assert result.action_taken == IntegrityActionTaken.WARNING_ISSUED
    assert result.review_notes == "Avertissement envoyé"
    integrity_repo.review.assert_awaited_once_with(
        alert_id=aid,
        reviewed_by_user_id=review_user,
        status=IntegrityAlertStatus.CONFIRMED,
        action_taken=IntegrityActionTaken.WARNING_ISSUED,
        review_notes="Avertissement envoyé",
    )


@pytest.mark.anyio
async def test_review_alert_dismissed_no_action():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    review_user = uuid.uuid4()
    alert = _make_alert(aid, sid, status=IntegrityAlertStatus.DISMISSED)
    alert.action_taken = IntegrityActionTaken.NO_ACTION

    integrity_repo = AsyncMock()
    integrity_repo.review.return_value = alert

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(integrity_repo=integrity_repo, user_repo=user_repo)
    result = await service.review_alert(
        aid, review_user, IntegrityAlertStatus.DISMISSED, IntegrityActionTaken.NO_ACTION, "Faux positif"
    )

    assert result.status == IntegrityAlertStatus.DISMISSED
    assert result.action_taken == IntegrityActionTaken.NO_ACTION


@pytest.mark.anyio
async def test_review_alert_not_found():
    aid = uuid.uuid4()
    integrity_repo = AsyncMock()
    integrity_repo.review.return_value = None

    service = _make_service(integrity_repo=integrity_repo)
    with pytest.raises(AlertNotFoundError):
        await service.review_alert(aid, uuid.uuid4(), IntegrityAlertStatus.CONFIRMED, None, None)


@pytest.mark.anyio
async def test_list_pending_success():
    aid = uuid.uuid4()
    sid = uuid.uuid4()
    alert = _make_alert(aid, sid)

    integrity_repo = AsyncMock()
    integrity_repo.list_pending.return_value = [alert]

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(integrity_repo=integrity_repo, user_repo=user_repo)
    result = await service.list_pending()

    assert len(result) == 1
    assert result[0].student_full_name == "Alice Dupont"
    integrity_repo.list_pending.assert_awaited_once()


@pytest.mark.anyio
async def test_get_student_history_success():
    aid1 = uuid.uuid4()
    aid2 = uuid.uuid4()
    sid = uuid.uuid4()
    alerts = [_make_alert(aid1, sid), _make_alert(aid2, sid)]

    integrity_repo = AsyncMock()
    integrity_repo.list_by_student.return_value = alerts

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(integrity_repo=integrity_repo, user_repo=user_repo)
    result = await service.get_student_history(sid)

    assert len(result) == 2
    integrity_repo.list_by_student.assert_awaited_once_with(sid)