import uuid
import pytest
from pydantic import ValidationError

from app.domain.models.identity.user import UserRole, AcademicStatus
from app.domain.schemas.auth_schemas import (
    LoginRequest,
    StudentCreate,
    ProfessorCreate,
    AdminCreate,
    MFAEnableRequest,
    UserPublic,
)


def test_login_request_valid():
    req = LoginRequest(email="test@example.com", password="secretpassword")
    assert req.email == "test@example.com"
    assert req.password == "secretpassword"


def test_login_request_invalid_email():
    with pytest.raises(ValidationError):
        LoginRequest(email="invalid-email", password="secretpassword")


def test_student_create_password_min_length():
    gid = uuid.uuid4()
    with pytest.raises(ValidationError):
        StudentCreate(
            email="student@test.com",
            password="short",  # < 8 chars
            first_name="Alice",
            last_name="Dupont",
            student_number="ST123",
            group_id=gid,
            enrollment_year=2024,
            level="L3",
        )


def test_student_create_valid():
    gid = uuid.uuid4()
    sc = StudentCreate(
        email="student@test.com",
        password="validpassword123",
        first_name="Alice",
        last_name="Dupont",
        student_number="ST123",
        group_id=gid,
        enrollment_year=2024,
        level="L3",
    )
    assert sc.email == "student@test.com"
    assert sc.group_id == gid


def test_professor_create_optional_fields():
    prof = ProfessorCreate(
        email="prof@test.com",
        password="securepassword123",
        first_name="Bob",
        last_name="Martin",
        department="Computer Science",
        title="Dr",
        employee_number="EMP999",
    )
    assert prof.office_location is None
    assert prof.specialty is None


def test_mfa_enable_request_code_length():
    with pytest.raises(ValidationError):
        MFAEnableRequest(code="12345")  # 5 digits instead of 6

    with pytest.raises(ValidationError):
        MFAEnableRequest(code="1234567")  # 7 digits

    req = MFAEnableRequest(code="123456")
    assert req.code == "123456"


def test_user_public_enum_validation():
    uid = uuid.uuid4()
    up = UserPublic(
        id=uid,
        email="user@test.com",
        role=UserRole.STUDENT,
        first_name="John",
        last_name="Doe",
        is_active=True,
    )
    assert up.role == UserRole.STUDENT
