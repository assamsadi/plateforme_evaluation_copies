"""
Tests GET /admin/statistics/platform — protégé par get_current_admin
(mécanisme existant, réutilisé tel quel, cf. tests/api/conftest.py).
"""
import pytest


@pytest.mark.anyio
async def test_get_platform_statistics_as_admin_returns_200(admin_client, mock_statistics_service):
    mock_statistics_service.get_platform_stats.return_value = {
        "total_users": 47,
        "users_by_role": {"student": 42, "professor": 5, "admin": 0},
        "total_exercises": 10,
        "exercises_by_status": {
            "draft": 3, "published_as_exam": 7,
            "published_as_homework": 0, "archived_in_library": 0,
        },
        "total_submissions": 24,
        "submissions_by_status": {
            "pending_ocr": 4, "pending_student_verification": 0, "pending_arbitration": 0,
            "pending_evaluation": 0, "evaluated": 20, "absent": 0,
        },
        "average_score": 13.46,
    }

    response = await admin_client.get("/api/v1/admin/statistics/platform")

    assert response.status_code == 200
    body = response.json()
    assert body["total_users"] == 47
    assert body["users_by_role"]["student"] == 42
    assert body["average_score"] == 13.46
    mock_statistics_service.get_platform_stats.assert_awaited_once()


@pytest.mark.anyio
async def test_get_platform_statistics_requires_admin_role(student_client, mock_statistics_service):
    response = await student_client.get("/api/v1/admin/statistics/platform")

    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_platform_statistics_requires_auth(client, mock_statistics_service):
    response = await client.get("/api/v1/admin/statistics/platform")

    assert response.status_code == 401
