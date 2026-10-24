"""
Tests GET /admin/jobs/overview, GET /admin/jobs/{id}, GET /admin/agent-decisions
— protégés par get_current_admin (mécanisme existant, réutilisé tel quel).
"""
import uuid

import pytest

from app.core.exceptions import JobNotFoundError


def _make_job_read(status="pending"):
    return {
        "id": str(uuid.uuid4()),
        "exercise_id": str(uuid.uuid4()),
        "submission_id": None,
        "flow_type": "exercise_setup",
        "status": status,
        "current_node": None,
        "error_message": None,
        "created_at": "2026-08-15T10:00:00Z",
        "updated_at": "2026-08-15T10:00:00Z",
    }


def _make_decision_log_read(agent_name="comparison_agent"):
    return {
        "id": str(uuid.uuid4()),
        "agent_name": agent_name,
        "related_entity_type": "Evaluation",
        "related_entity_id": str(uuid.uuid4()),
        "input_summary": None,
        "output_summary": None,
        "justification": "Justification de test",
        "confidence_score": "0.9",
        "model_version": "v1",
        "created_at": "2026-08-15T10:00:00Z",
    }


@pytest.mark.anyio
async def test_jobs_overview_as_admin_returns_200(admin_client, mock_job_supervision_service):
    mock_job_supervision_service.get_overview.return_value = {
        "counts_by_status": {
            "pending": 2, "running": 1, "retrying": 0, "interrupted": 1,
            "completed": 10, "failed": 1, "cancelled": 0,
        },
        "recent_jobs": [_make_job_read()],
        "problematic_jobs": [_make_job_read("interrupted"), _make_job_read("failed")],
    }

    response = await admin_client.get("/api/v1/admin/jobs/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["counts_by_status"]["completed"] == 10
    assert len(body["problematic_jobs"]) == 2
    mock_job_supervision_service.get_overview.assert_awaited_once()


@pytest.mark.anyio
async def test_jobs_overview_requires_admin_role(student_client, mock_job_supervision_service):
    response = await student_client.get("/api/v1/admin/jobs/overview")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_job_detail_success(admin_client, mock_job_supervision_service):
    job_id = uuid.uuid4()
    mock_job_supervision_service.get_job_detail.return_value = _make_job_read()

    response = await admin_client.get(f"/api/v1/admin/jobs/{job_id}")

    assert response.status_code == 200
    mock_job_supervision_service.get_job_detail.assert_awaited_once_with(job_id)


@pytest.mark.anyio
async def test_get_job_detail_not_found_returns_404(admin_client, mock_job_supervision_service):
    job_id = uuid.uuid4()
    mock_job_supervision_service.get_job_detail.side_effect = JobNotFoundError(job_id)

    response = await admin_client.get(f"/api/v1/admin/jobs/{job_id}")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_get_job_detail_requires_admin_role(student_client, mock_job_supervision_service):
    response = await student_client.get(f"/api/v1/admin/jobs/{uuid.uuid4()}")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_list_agent_decisions_as_admin_returns_200(admin_client, mock_decision_log_service):
    from app.domain.repositories.pagination import CursorPage
    mock_decision_log_service.get_platform_decision_logs.return_value = CursorPage(
        items=[_make_decision_log_read()], next_cursor=None, has_more=False,
    )

    response = await admin_client.get("/api/v1/admin/agent-decisions")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 1
    mock_decision_log_service.get_platform_decision_logs.assert_awaited_once()


@pytest.mark.anyio
async def test_list_agent_decisions_passes_filters(admin_client, mock_decision_log_service):
    from app.domain.repositories.pagination import CursorPage
    mock_decision_log_service.get_platform_decision_logs.return_value = CursorPage(
        items=[], next_cursor=None, has_more=False,
    )

    response = await admin_client.get(
        "/api/v1/admin/agent-decisions?agent_name=comparison_agent&professor_validation_status=corrected"
    )

    assert response.status_code == 200
    _, kwargs = mock_decision_log_service.get_platform_decision_logs.call_args
    assert kwargs["agent_name"] == "comparison_agent"
    assert kwargs["professor_validation_status"].value == "corrected"


@pytest.mark.anyio
async def test_list_agent_decisions_requires_admin_role(student_client, mock_decision_log_service):
    response = await student_client.get("/api/v1/admin/agent-decisions")
    assert response.status_code == 403
