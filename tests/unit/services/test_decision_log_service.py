"""
Tests DecisionLogService.get_platform_decision_logs — vue transverse admin,
distincte de get_exercise_decision_logs (scopée exercice, testée ailleurs
via l'endpoint). Pas de vérification authorize_agent_log_access ici
(contrôle d'accès déjà le plus strict via get_current_admin au routeur).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.domain.models.system_infrastructure.agent_decision_log import (
    AgentDecisionLog,
    ProfessorValidationStatus,
)
from app.domain.repositories.pagination import CursorPage
from app.services.decision_log_service import DecisionLogService


def _make_log(agent_name="comparison_agent") -> AgentDecisionLog:
    """
    created_at explicite : instance transiente (jamais flush en DB) —
    CreatedAtOnlyMixin.created_at utilise server_default=func.clock_
    timestamp(), appliqué uniquement à l'INSERT réel, jamais à la simple
    construction Python (reste None sinon, rejeté par AgentDecisionLogRead
    qui l'exige non-nul).
    """
    return AgentDecisionLog(
        id=uuid.uuid4(), agent_name=agent_name, related_entity_type="Evaluation",
        related_entity_id=uuid.uuid4(), justification="Justification test", model_version="v1",
        confidence_score=Decimal("0.9"), tools_consulted=[],
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.anyio
class TestGetPlatformDecisionLogs:
    async def test_delegates_filters_to_repository(self):
        decision_log_repo = AsyncMock()
        fake_log = _make_log()
        decision_log_repo.list_all.return_value = CursorPage(items=[fake_log], next_cursor=None, has_more=False)
        service = DecisionLogService(decision_log_repo, AsyncMock(), AsyncMock())

        result = await service.get_platform_decision_logs(
            agent_name="comparison_agent",
            professor_validation_status=ProfessorValidationStatus.CORRECTED,
            cursor="abc", limit=10,
        )

        decision_log_repo.list_all.assert_awaited_once_with(
            agent_name="comparison_agent",
            professor_validation_status=ProfessorValidationStatus.CORRECTED,
            cursor="abc", limit=10,
        )
        assert len(result.items) == 1
        assert result.items[0].agent_name == "comparison_agent"

    async def test_no_filters_returns_all(self):
        decision_log_repo = AsyncMock()
        decision_log_repo.list_all.return_value = CursorPage(items=[_make_log(), _make_log("other_agent")], next_cursor=None, has_more=False)
        service = DecisionLogService(decision_log_repo, AsyncMock(), AsyncMock())

        result = await service.get_platform_decision_logs()

        assert len(result.items) == 2
        decision_log_repo.list_all.assert_awaited_once_with(
            agent_name=None, professor_validation_status=None, cursor=None, limit=50,
        )
