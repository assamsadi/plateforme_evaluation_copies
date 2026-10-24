"""
Unit test fixtures.

Provides mock repository instances for service-level unit testing.
Each fixture returns a fresh AsyncMock scoped to the test function.
"""
import pytest
from unittest.mock import AsyncMock


# ── Identity ─────────────────────────────────────────────────

@pytest.fixture
def mock_user_repo():
    return AsyncMock()


@pytest.fixture
def mock_audit_repo():
    return AsyncMock()


# ── Academic ─────────────────────────────────────────────────

@pytest.fixture
def mock_course_repo():
    return AsyncMock()


@pytest.fixture
def mock_module_repo():
    return AsyncMock()


@pytest.fixture
def mock_program_repo():
    return AsyncMock()


@pytest.fixture
def mock_group_repo():
    return AsyncMock()


@pytest.fixture
def mock_enrollment_repo():
    return AsyncMock()


# ── Assessment ───────────────────────────────────────────────

@pytest.fixture
def mock_exercise_repo():
    return AsyncMock()


@pytest.fixture
def mock_submission_repo():
    return AsyncMock()


@pytest.fixture
def mock_evaluation_repo():
    return AsyncMock()


@pytest.fixture
def mock_feedback_repo():
    return AsyncMock()


@pytest.fixture
def mock_appeal_repo():
    return AsyncMock()


@pytest.fixture
def mock_arbitration_repo():
    return AsyncMock()


@pytest.fixture
def mock_incident_repo():
    return AsyncMock()


@pytest.fixture
def mock_variant_repo():
    return AsyncMock()


@pytest.fixture
def mock_clarification_repo():
    return AsyncMock()


@pytest.fixture
def mock_recommendation_repo():
    return AsyncMock()


# ── System / Infrastructure ─────────────────────────────────

@pytest.fixture
def mock_integrity_repo():
    return AsyncMock()


@pytest.fixture
def mock_privacy_repo():
    return AsyncMock()


@pytest.fixture
def mock_competency_profile_repo():
    return AsyncMock()

