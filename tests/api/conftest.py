"""
API test fixtures — self-contained (no real DB needed).

Provides:
  - AsyncClient fixtures: unauthenticated + role-authenticated
  - Per-service mock overrides (opt-in, not autouse)

Usage pattern in tests:
    async def test_get_program(admin_client, mock_program_service):
        mock_program_service.get_by_id.return_value = MagicMock(id=..., name=...)
        response = await admin_client.get("/api/v1/programs/...")
        assert response.status_code == 200
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.api import deps
from app.domain.models.identity.user import UserRole


# --- AsyncClient Fixtures ---

@pytest.fixture
async def client():
    """Unauthenticated HTTP client against the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


def _make_user(role: UserRole, user_id, email, first_name, last_name):
    user = MagicMock()
    user.id = user_id
    user.email = email
    user.role = role
    user.first_name = first_name
    user.last_name = last_name
    user.hashed_password = "hashed_pw"
    user.totp_enabled = False
    # Ces champs doivent être None (pas des MagicMock auto-générés)
    # pour que la sérialisation JSON de MFAStatusResponse fonctionne.
    user.totp_verified_at = None
    user.totp_last_used_at = None
    return user


@pytest.fixture
def fake_student():
    return _make_user(UserRole.STUDENT, "00000000-0000-4000-a000-000000000001", "alice@test.edu", "Alice", "Dupont")


@pytest.fixture
def fake_professor():
    return _make_user(UserRole.PROFESSOR, "00000000-0000-4000-a000-000000000002", "bob@test.edu", "Bob", "Martin")


@pytest.fixture
def fake_admin():
    return _make_user(UserRole.ADMIN, "00000000-0000-4000-a000-000000000003", "charlie@test.edu", "Charlie", "Bernard")


@pytest.fixture
async def student_client(client, fake_student):
    """HTTP client authenticated as a student."""
    app.dependency_overrides[deps.get_current_user] = lambda: fake_student
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_student
    app.dependency_overrides[deps.get_current_student] = lambda: fake_student
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def professor_client(client, fake_professor):
    """HTTP client authenticated as a professor."""
    app.dependency_overrides[deps.get_current_user] = lambda: fake_professor
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_professor
    app.dependency_overrides[deps.get_current_professor] = lambda: fake_professor
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def admin_client(client, fake_admin):
    """HTTP client authenticated as an admin."""
    app.dependency_overrides[deps.get_current_user] = lambda: fake_admin
    app.dependency_overrides[deps.get_current_active_user] = lambda: fake_admin
    app.dependency_overrides[deps.get_current_admin] = lambda: fake_admin
    yield client
    app.dependency_overrides.clear()


# --- Service Mock Factories ---

@pytest.fixture
def mock_user_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_user_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_course_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_course_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_program_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_program_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_module_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_module_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_group_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_group_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_enrollment_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_enrollment_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_exercise_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_exercise_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_document_structuring_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_document_structuring_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_submission_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_submission_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_evaluation_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_evaluation_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_feedback_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_feedback_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_grade_appeal_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_grade_appeal_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_arbitration_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_arbitration_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_solution_variant_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_solution_variant_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_solution_variant_generation_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_solution_variant_generation_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_recommendation_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_recommendation_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_feedback_report_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_feedback_report_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_integrity_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_integrity_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_data_privacy_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_data_privacy_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_audit_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_audit_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_statistics_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_statistics_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_competency_assessment_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_competency_assessment_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_job_supervision_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_job_supervision_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_decision_log_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_decision_log_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_model_config_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_model_config_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_system_config_service():
    svc = AsyncMock()
    app.dependency_overrides[deps.get_system_config_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()