"""
Tests de SQLAlchemyAgentDecisionLogRepository.list_all() — vue transverse
(supervision admin), câblage DecisionLogService.get_platform_decision_logs.
Delta-based : la base de test est partagée entre les runs.
"""
import uuid

import pytest

from app.domain.models.system_infrastructure.agent_decision_log import ProfessorValidationStatus
from app.domain.repositories.agent_decision_log_repository import SQLAlchemyAgentDecisionLogRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository


def _unique_agent_name() -> str:
    return f"test_agent_{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def professor(db_session):
    """validated_by_professor_id est une vraie FK vers professors.id — pas un UUID arbitraire."""
    user_repo = SQLAlchemyUserRepository(db_session)
    return await user_repo.create_professor(
        email=f"prof_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
        first_name="Bob", last_name="Martin", department="Informatique", title="Dr",
        employee_number=f"EMP{uuid.uuid4().hex[:6]}",
    )


@pytest.mark.anyio
class TestAgentDecisionLogRepositoryListAll:
    async def test_no_filter_returns_created_logs_via_delta(self, db_session):
        repo = SQLAlchemyAgentDecisionLogRepository(db_session)
        before = await repo.list_all(limit=500)
        before_ids = {log.id for log in before.items}

        created = await repo.create(
            agent_name=_unique_agent_name(), related_entity_type="Evaluation",
            related_entity_id=uuid.uuid4(), justification="Décision de test", model_version="v1",
        )

        after = await repo.list_all(limit=500)
        after_ids = {log.id for log in after.items}

        assert created.id in after_ids
        assert created.id not in before_ids

    async def test_filters_by_agent_name(self, db_session):
        repo = SQLAlchemyAgentDecisionLogRepository(db_session)
        target_name = _unique_agent_name()
        other_name = _unique_agent_name()

        target = await repo.create(
            agent_name=target_name, related_entity_type="Evaluation",
            related_entity_id=uuid.uuid4(), justification="Cible", model_version="v1",
        )
        await repo.create(
            agent_name=other_name, related_entity_type="Evaluation",
            related_entity_id=uuid.uuid4(), justification="Autre", model_version="v1",
        )

        page = await repo.list_all(agent_name=target_name, limit=200)

        assert len(page.items) == 1
        assert page.items[0].id == target.id
        assert all(log.agent_name == target_name for log in page.items)

    async def test_filters_by_professor_validation_status(self, db_session, professor):
        repo = SQLAlchemyAgentDecisionLogRepository(db_session)
        name = _unique_agent_name()

        corrected = await repo.create(
            agent_name=name, related_entity_type="Evaluation",
            related_entity_id=uuid.uuid4(), justification="À corriger", model_version="v1",
        )
        not_reviewed = await repo.create(
            agent_name=name, related_entity_type="Evaluation",
            related_entity_id=uuid.uuid4(), justification="Pas revu", model_version="v1",
        )
        await repo.record_professor_feedback(
            corrected.id, professor_id=professor.id, status=ProfessorValidationStatus.CORRECTED,
            correction="Erreur corrigée",
        )

        page = await repo.list_all(
            agent_name=name, professor_validation_status=ProfessorValidationStatus.CORRECTED, limit=200,
        )

        assert len(page.items) == 1
        assert page.items[0].id == corrected.id

    async def test_pagination_cursor(self, db_session):
        repo = SQLAlchemyAgentDecisionLogRepository(db_session)
        name = _unique_agent_name()
        for i in range(3):
            await repo.create(
                agent_name=name, related_entity_type="Evaluation",
                related_entity_id=uuid.uuid4(), justification=f"Log {i}", model_version="v1",
            )

        first_page = await repo.list_all(agent_name=name, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_all(agent_name=name, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 1
