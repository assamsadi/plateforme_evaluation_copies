import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.models.system_infrastructure.audit_log import AuditLog, AuditSeverity
from app.services.audit_service import AuditService


def _make_audit_log(
    log_id: uuid.UUID,
    user_id: uuid.UUID,
    entity_type: str = "Exercise",
    action: str = "create",
    severity: AuditSeverity = AuditSeverity.INFO,
) -> AuditLog:
    now = datetime.now(timezone.utc)
    return AuditLog(
        id=log_id,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=uuid.uuid4(),
        action=action,
        diff=None,
        ip_address=None,
        user_agent=None,
        success=True,
        severity=severity,
        entry_hash=None,
        created_at=now,
    )


def _make_professor(professor_id: uuid.UUID) -> MagicMock:
    p = MagicMock()
    p.id = professor_id
    p.first_name = "Alice"
    p.last_name = "Dupont"
    return p


def _make_service(audit_repo=None, user_repo=None) -> AuditService:
    return AuditService(
        audit_repo or AsyncMock(),
        user_repo or AsyncMock(),
    )


@pytest.mark.anyio
async def test_log_action_success_infers_info_severity():
    log_id = uuid.uuid4()
    uid = uuid.uuid4()
    eid = uuid.uuid4()
    audit_log = _make_audit_log(log_id, uid, entity_type="Exercise", action="create_exercise")

    audit_repo = AsyncMock()
    audit_repo.create.return_value = audit_log

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(uid)

    service = _make_service(audit_repo=audit_repo, user_repo=user_repo)
    result = await service.log_action(uid, "Exercise", eid, "create_exercise")

    assert result is not None
    assert result.id == log_id
    assert result.user_full_name == "Alice Dupont"
    assert result.severity == AuditSeverity.INFO
    audit_repo.create.assert_awaited_once_with(
        user_id=uid,
        entity_type="Exercise",
        entity_id=eid,
        action="create_exercise",
        diff=None,
        ip_address=None,
        user_agent=None,
        success=True,
        severity=AuditSeverity.INFO,
    )


@pytest.mark.anyio
async def test_log_action_infers_warning_severity():
    uid = uuid.uuid4()
    eid = uuid.uuid4()
    audit_log = _make_audit_log(uuid.uuid4(), uid, action="delete_exercise", severity=AuditSeverity.WARNING)

    audit_repo = AsyncMock()
    audit_repo.create.return_value = audit_log

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(uid)

    service = _make_service(audit_repo=audit_repo, user_repo=user_repo)
    result = await service.log_action(uid, "Exercise", eid, "delete_exercise")

    assert result.severity == AuditSeverity.WARNING
    # Le service a délégué le mot-clé "delete" -> WARNING
    call_kwargs = audit_repo.create.await_args.kwargs
    assert call_kwargs["severity"] == AuditSeverity.WARNING


@pytest.mark.anyio
async def test_log_action_infers_critical_severity():
    uid = uuid.uuid4()
    eid = uuid.uuid4()
    audit_log = _make_audit_log(uuid.uuid4(), uid, action="grade_override", severity=AuditSeverity.CRITICAL)

    audit_repo = AsyncMock()
    audit_repo.create.return_value = audit_log

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(uid)

    service = _make_service(audit_repo=audit_repo, user_repo=user_repo)
    result = await service.log_action(uid, "Evaluation", eid, "grade_override")

    assert result.severity == AuditSeverity.CRITICAL
    call_kwargs = audit_repo.create.await_args.kwargs
    assert call_kwargs["severity"] == AuditSeverity.CRITICAL


@pytest.mark.anyio
async def test_log_action_explicit_severity_overrides_inference():
    uid = uuid.uuid4()
    eid = uuid.uuid4()
    audit_log = _make_audit_log(uuid.uuid4(), uid, action="delete_exercise", severity=AuditSeverity.INFO)

    audit_repo = AsyncMock()
    audit_repo.create.return_value = audit_log

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(uid)

    service = _make_service(audit_repo=audit_repo, user_repo=user_repo)
    result = await service.log_action(uid, "Exercise", eid, "delete_exercise", severity=AuditSeverity.INFO)

    assert result.severity == AuditSeverity.INFO
    call_kwargs = audit_repo.create.await_args.kwargs
    assert call_kwargs["severity"] == AuditSeverity.INFO


@pytest.mark.anyio
async def test_log_action_user_unknown():
    uid = uuid.uuid4()
    eid = uuid.uuid4()
    audit_log = _make_audit_log(uuid.uuid4(), uid, action="create_exercise")

    audit_repo = AsyncMock()
    audit_repo.create.return_value = audit_log

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = None

    service = _make_service(audit_repo=audit_repo, user_repo=user_repo)
    result = await service.log_action(uid, "Exercise", eid, "create_exercise")

    assert result.user_full_name == "Unknown"


@pytest.mark.anyio
async def test_log_action_repository_failure_returns_none():
    """Un échec de journalisation ne doit jamais lever vers l'appelant."""
    uid = uuid.uuid4()
    eid = uuid.uuid4()

    audit_repo = AsyncMock()
    audit_repo.create.side_effect = Exception("db down")

    service = _make_service(audit_repo=audit_repo)
    result = await service.log_action(uid, "Exercise", eid, "create_exercise")

    assert result is None