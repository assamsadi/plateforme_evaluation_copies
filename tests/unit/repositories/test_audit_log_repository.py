"""
Tests du AuditLogRepository — couvre toutes les méthodes publiques :
- create (nominal, avec diff, avec ip/user_agent, avec severity, avec success=False)
"""
import uuid

import pytest

from app.domain.models.identity.user import Admin, UserRole
from app.domain.models.system_infrastructure.audit_log import AuditLog, AuditSeverity
from app.domain.repositories.audit_log_repository import SQLAlchemyAuditLogRepository


@pytest.fixture
async def user(db_session):
    u = Admin(
        id=uuid.uuid4(),
        first_name="Charlie",
        last_name="Bernard",
        email=f"admin_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
    )
    db_session.add(u)
    await db_session.flush()
    return u

@pytest.mark.anyio
class TestAuditLogRepositoryCreate:
    """Tests de la méthode create()."""

    async def test_create_nominal(self, db_session, user):
        repo = SQLAlchemyAuditLogRepository(db_session)
        log = await repo.create(
            user_id=user.id,
            entity_type="Program",
            entity_id=uuid.uuid4(),
            action="create_program",
        )

        assert log.id is not None
        assert log.user_id == user.id
        assert log.entity_type == "Program"
        assert log.action == "create_program"
        assert log.success is True
        assert log.severity == AuditSeverity.INFO
        assert log.diff is None
        assert log.ip_address is None
        assert log.user_agent is None
        assert log.created_at is not None

    async def test_create_with_diff(self, db_session, user):
        repo = SQLAlchemyAuditLogRepository(db_session)
        diff = {"before": {"name": "Old"}, "after": {"name": "New"}}
        log = await repo.create(
            user_id=user.id,
            entity_type="Program",
            entity_id=uuid.uuid4(),
            action="update_program",
            diff=diff,
        )

        assert log.diff == diff

    async def test_create_with_ip_and_user_agent(self, db_session, user):
        repo = SQLAlchemyAuditLogRepository(db_session)
        log = await repo.create(
            user_id=user.id,
            entity_type="Exercise",
            entity_id=uuid.uuid4(),
            action="publish_exercise",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )

        assert log.ip_address == "192.168.1.1"
        assert log.user_agent == "Mozilla/5.0"

    async def test_create_with_warning_severity(self, db_session, user):
        repo = SQLAlchemyAuditLogRepository(db_session)
        log = await repo.create(
            user_id=user.id,
            entity_type="User",
            entity_id=uuid.uuid4(),
            action="deactivate_user",
            severity=AuditSeverity.WARNING,
        )

        assert log.severity == AuditSeverity.WARNING

    async def test_create_with_critical_severity(self, db_session, user):
        repo = SQLAlchemyAuditLogRepository(db_session)
        log = await repo.create(
            user_id=user.id,
            entity_type="Grade",
            entity_id=uuid.uuid4(),
            action="grade_override",
            severity=AuditSeverity.CRITICAL,
        )

        assert log.severity == AuditSeverity.CRITICAL

    async def test_create_with_success_false(self, db_session, user):
        repo = SQLAlchemyAuditLogRepository(db_session)
        log = await repo.create(
            user_id=user.id,
            entity_type="Submission",
            entity_id=uuid.uuid4(),
            action="delete_submission",
            success=False,
        )

        assert log.success is False