"""
Integration test fixtures.

Provides:
  - Mock DB session (autouse, no real Postgres needed)
  - AsyncClient fixtures: unauthenticated + role-authenticated
  - Per-service mock overrides (opt-in, not autouse)

Usage pattern in tests:
    async def test_get_program(admin_client, mock_program_service):
        mock_program_service.get_by_id.return_value = MagicMock(id=..., name=...)
        response = await admin_client.get("/api/v1/programs/...")
        assert response.status_code == 200
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.database import get_db
from app.api import deps


# ── Mock DB Session (autouse) ────────────────────────────────

@pytest.fixture(autouse=True)
def _override_deps(db_session):
    """
    Automatically override get_db for every integration test to use the same
    transactional database session as the test.
    """
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    yield
    app.dependency_overrides.clear()


# ── AsyncClient Fixtures ────────────────────────────────────

@pytest.fixture
async def client():
    """Unauthenticated HTTP client against the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def student_client(client, fake_student):
    """
    HTTP client authenticated as a student.
    Routes using get_current_user / get_current_student will see fake_student.
    Routes requiring professor/admin role will correctly return 403.
    """
    app.dependency_overrides[deps.get_current_user] = lambda: fake_student
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_student
    app.dependency_overrides[deps.get_current_student] = lambda: fake_student
    yield client


@pytest.fixture
async def professor_client(client, fake_professor):
    """HTTP client authenticated as a professor."""
    app.dependency_overrides[deps.get_current_user] = lambda: fake_professor
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_professor
    app.dependency_overrides[deps.get_current_professor] = lambda: fake_professor
    yield client


@pytest.fixture
async def admin_client(client, fake_admin):
    """HTTP client authenticated as an admin."""
    app.dependency_overrides[deps.get_current_user] = lambda: fake_admin
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_admin
    app.dependency_overrides[deps.get_current_admin] = lambda: fake_admin
    yield client


# ── Service Mock Factories ──────────────────────────────────
# Each fixture returns an AsyncMock AND registers it as the FastAPI
# dependency override for the corresponding service factory.
# Usage: request the fixture by name in your test function signature.

@pytest.fixture
def mock_user_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_user_service] = lambda: svc
    return svc


@pytest.fixture
def mock_course_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_course_service] = lambda: svc
    return svc


@pytest.fixture
def mock_program_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_program_service] = lambda: svc
    return svc


@pytest.fixture
def mock_module_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_module_service] = lambda: svc
    return svc


@pytest.fixture
def mock_group_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_group_service] = lambda: svc
    return svc


@pytest.fixture
def mock_enrollment_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_enrollment_service] = lambda: svc
    return svc


@pytest.fixture
def mock_exercise_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_exercise_service] = lambda: svc
    return svc


@pytest.fixture
def mock_submission_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_submission_service] = lambda: svc
    return svc


@pytest.fixture
def mock_evaluation_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_evaluation_service] = lambda: svc
    return svc


@pytest.fixture
def mock_feedback_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_feedback_service] = lambda: svc
    return svc


@pytest.fixture
def mock_grade_appeal_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_grade_appeal_service] = lambda: svc
    return svc


@pytest.fixture
def mock_arbitration_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_arbitration_service] = lambda: svc
    return svc


@pytest.fixture
def mock_solution_variant_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_solution_variant_service] = lambda: svc
    return svc


@pytest.fixture
def mock_recommendation_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_recommendation_service] = lambda: svc
    return svc


@pytest.fixture
def mock_integrity_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_integrity_service] = lambda: svc
    return svc


@pytest.fixture
def mock_data_privacy_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_data_privacy_service] = lambda: svc
    return svc


@pytest.fixture
def mock_audit_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_audit_service] = lambda: svc
    return svc


@pytest.fixture
def mock_statistics_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_statistics_service] = lambda: svc
    return svc


@pytest.fixture
def mock_job_supervision_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_job_supervision_service] = lambda: svc
    return svc


@pytest.fixture
def mock_decision_log_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_decision_log_service] = lambda: svc
    return svc


@pytest.fixture
def mock_model_config_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_model_config_service] = lambda: svc
    return svc


@pytest.fixture
def mock_system_config_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_system_config_service] = lambda: svc
    return svc
