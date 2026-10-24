"""
Tests API — endpoints du déclencheur guidé (2.3) et du rapport de revue
(4 actions) de Solution_Variant_Generation_Agent (cf. audit
Solution_Variant_Generation_Agent §1c/§6).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models.assessment.solution_variant import SolutionVariant, VariantStatus
from app.core.exceptions import NotExerciseOwnerError


@pytest.mark.anyio
async def test_generate_guided_variant_dispatches_celery_task(professor_client, mock_solution_variant_generation_service):
    mock_solution_variant_generation_service.ensure_professor_owns_question.return_value = None
    qid = uuid.uuid4()

    with patch(
        "app.tasks.solution_variant_generation_tasks.generate_guided_variant_task.delay",
        new_callable=MagicMock,
    ) as mock_delay:
        response = await professor_client.post(
            f"/api/v1/questions/{qid}/solution-variants/generate-guided",
            json={"method_hint": "Résoudre par substitution", "concept_hint": ["algebre"]},
        )

    assert response.status_code == 202
    assert response.json()["question_id"] == str(qid)
    mock_solution_variant_generation_service.ensure_professor_owns_question.assert_awaited_once()
    mock_delay.assert_called_once()
    assert mock_delay.call_args.kwargs["question_id"] == str(qid)
    assert mock_delay.call_args.kwargs["method_hint"] == "Résoudre par substitution"
    assert mock_delay.call_args.kwargs["concept_hint"] == ["algebre"]


@pytest.mark.anyio
async def test_generate_guided_variant_requires_professor(student_client, mock_solution_variant_generation_service):
    qid = uuid.uuid4()
    response = await student_client.post(
        f"/api/v1/questions/{qid}/solution-variants/generate-guided",
        json={},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_generate_guided_variant_rejects_non_owner(professor_client, mock_solution_variant_generation_service):
    qid = uuid.uuid4()
    mock_solution_variant_generation_service.ensure_professor_owns_question.side_effect = NotExerciseOwnerError(
        uuid.uuid4(), uuid.uuid4()
    )

    response = await professor_client.post(
        f"/api/v1/questions/{qid}/solution-variants/generate-guided",
        json={},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_review_variant_accepted_action(professor_client, mock_solution_variant_generation_service, fake_professor):
    vid = uuid.uuid4()
    mock_solution_variant_generation_service.ensure_professor_owns_variant.return_value = None
    mock_v = SolutionVariant(id=vid, question_id=uuid.uuid4(), content="Contenu", status=VariantStatus.APPROVED)
    mock_solution_variant_generation_service.review_variant_decision.return_value = (mock_v, None)

    response = await professor_client.post(
        f"/api/v1/solution-variants/{vid}/review",
        json={"variant_id": str(vid), "action": "ACCEPTED"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["variant_id"] == str(vid)
    assert body["status"] == "approved"
    assert body["deleted"] is False
    mock_solution_variant_generation_service.ensure_professor_owns_variant.assert_awaited_once_with(vid, fake_professor.id)


@pytest.mark.anyio
async def test_review_variant_deleted_action(professor_client, mock_solution_variant_generation_service):
    vid = uuid.uuid4()
    mock_solution_variant_generation_service.ensure_professor_owns_variant.return_value = None
    mock_solution_variant_generation_service.review_variant_decision.return_value = (None, None)

    response = await professor_client.post(
        f"/api/v1/solution-variants/{vid}/review",
        json={"variant_id": str(vid), "action": "DELETED"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["variant_id"] is None


@pytest.mark.anyio
async def test_review_variant_requires_professor(student_client, mock_solution_variant_generation_service):
    vid = uuid.uuid4()
    response = await student_client.post(
        f"/api/v1/solution-variants/{vid}/review",
        json={"variant_id": str(vid), "action": "ACCEPTED"},
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_review_variant_rejects_non_owner(professor_client, mock_solution_variant_generation_service):
    vid = uuid.uuid4()
    mock_solution_variant_generation_service.ensure_professor_owns_variant.side_effect = NotExerciseOwnerError(
        uuid.uuid4(), uuid.uuid4()
    )

    response = await professor_client.post(
        f"/api/v1/solution-variants/{vid}/review",
        json={"variant_id": str(vid), "action": "ACCEPTED"},
    )
    assert response.status_code == 403
    mock_solution_variant_generation_service.review_variant_decision.assert_not_awaited()
