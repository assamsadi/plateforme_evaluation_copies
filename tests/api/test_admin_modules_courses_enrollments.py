import uuid
from unittest.mock import MagicMock

import pytest

from app.domain.models.identity.user import UserRole
from app.domain.repositories.pagination import CursorPage


# --- Admin Router (user management) ---

def _make_user_public(role=UserRole.ADMIN):
    return {
        "id": str(uuid.uuid4()),
        "email": "newuser@test.edu",
        "role": role.value,
        "first_name": "John",
        "last_name": "Doe",
        "is_active": True,
    }


def _make_professor_public():
    return {
        **_make_user_public(UserRole.PROFESSOR),
        "department": "Informatique",
        "title": "Dr",
        "employee_number": "EMP001",
        "office_location": None,
        "specialty": None,
    }


@pytest.mark.anyio
async def test_create_admin_success(admin_client, mock_user_service):
    mock_user_service.register_admin.return_value = _make_user_public()
    payload = {
        "email": "newadmin@test.edu",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
    }
    response = await admin_client.post("/api/v1/admin/users/admins", json=payload)
    assert response.status_code == 201
    assert response.json()["role"] == UserRole.ADMIN.value
    mock_user_service.register_admin.assert_awaited_once()


@pytest.mark.anyio
async def test_create_admin_value_error_400(admin_client, mock_user_service):
    mock_user_service.register_admin.side_effect = ValueError("Email existe")
    payload = {
        "email": "newadmin@test.edu",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
    }
    response = await admin_client.post("/api/v1/admin/users/admins", json=payload)
    assert response.status_code == 400


@pytest.mark.anyio
async def test_create_admin_requires_admin_role(student_client, mock_user_service):
    payload = {
        "email": "newadmin@test.edu",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
    }
    response = await student_client.post("/api/v1/admin/users/admins", json=payload)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_create_admin_requires_auth(client):
    response = await client.post("/api/v1/admin/users/admins", json={
        "email": "a@test.edu", "password": "password123", "first_name": "A", "last_name": "B"
    })
    assert response.status_code == 401


@pytest.mark.anyio
async def test_create_professor_success(admin_client, mock_user_service):
    mock_user_service.register_professor.return_value = _make_professor_public()
    payload = {
        "email": "newprof@test.edu",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
        "department": "Informatique",
        "title": "Dr",
        "employee_number": "EMP001",
    }
    response = await admin_client.post("/api/v1/admin/users/professors", json=payload)
    assert response.status_code == 201
    assert response.json()["role"] == UserRole.PROFESSOR.value
    mock_user_service.register_professor.assert_awaited_once()


@pytest.mark.anyio
async def test_create_professor_value_error_400(admin_client, mock_user_service):
    mock_user_service.register_professor.side_effect = ValueError("Email existe")
    payload = {
        "email": "newprof@test.edu",
        "password": "password123",
        "first_name": "John",
        "last_name": "Doe",
        "department": "Informatique",
        "title": "Dr",
        "employee_number": "EMP001",
    }
    response = await admin_client.post("/api/v1/admin/users/professors", json=payload)
    assert response.status_code == 400


# --- Program & Module Router ---

def _make_program_read():
    return {"id": str(uuid.uuid4()), "name": "Informatique", "code": "INFO"}


def _make_module_read():
    return {
        "id": str(uuid.uuid4()),
        "name": "Analyse",
        "code": "AN",
        "program_id": str(uuid.uuid4()),
        "program_name": "Informatique",
    }


@pytest.mark.anyio
async def test_list_programs_success(admin_client, mock_program_service):
    mock_program_service.list_page.return_value = CursorPage(
        items=[_make_program_read()], next_cursor=None, has_more=False
    )
    response = await admin_client.get("/api/v1/programs")
    assert response.status_code == 200
    mock_program_service.list_page.assert_awaited_once()


@pytest.mark.anyio
async def test_get_program_success(admin_client, mock_program_service):
    pid = uuid.uuid4()
    mock_program_service.get_by_id.return_value = _make_program_read()
    response = await admin_client.get(f"/api/v1/programs/{pid}")
    assert response.status_code == 200
    mock_program_service.get_by_id.assert_awaited_once_with(pid)


@pytest.mark.anyio
async def test_get_program_not_found(admin_client, mock_program_service):
    from app.core.exceptions import ProgramNotFoundError
    mock_program_service.get_by_id.side_effect = ProgramNotFoundError(uuid.uuid4())
    response = await admin_client.get(f"/api/v1/programs/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_create_program_success(admin_client, mock_program_service):
    mock_program_service.create.return_value = _make_program_read()
    response = await admin_client.post("/api/v1/programs", json={"name": "Informatique", "code": "INFO"})
    assert response.status_code == 201
    mock_program_service.create.assert_awaited_once_with(name="Informatique", code="INFO")


@pytest.mark.anyio
async def test_create_program_requires_admin(student_client, mock_program_service):
    response = await student_client.post("/api/v1/programs", json={"name": "Info", "code": "INFO"})
    assert response.status_code == 403


@pytest.mark.anyio
async def test_delete_program_success(admin_client, mock_program_service):
    mock_program_service.delete.return_value = None
    response = await admin_client.delete(f"/api/v1/programs/{uuid.uuid4()}")
    assert response.status_code == 204
    mock_program_service.delete.assert_awaited_once()


@pytest.mark.anyio
async def test_list_modules_by_program(admin_client, mock_module_service):
    mock_module_service.list_by_program.return_value = CursorPage(
        items=[_make_module_read()], next_cursor=None, has_more=False
    )
    response = await admin_client.get(f"/api/v1/programs/{uuid.uuid4()}/modules")
    assert response.status_code == 200
    mock_module_service.list_by_program.assert_awaited_once()


@pytest.mark.anyio
async def test_get_module_success(admin_client, mock_module_service):
    mid = uuid.uuid4()
    mock_module_service.get_by_id.return_value = _make_module_read()
    response = await admin_client.get(f"/api/v1/modules/{mid}")
    assert response.status_code == 200
    mock_module_service.get_by_id.assert_awaited_once_with(mid)


@pytest.mark.anyio
async def test_create_module_success(admin_client, mock_module_service):
    mock_module_service.create.return_value = _make_module_read()
    pid = uuid.uuid4()
    # ModuleCreate exige program_id dans le body (même s'il est aussi dans le path)
    response = await admin_client.post(
        f"/api/v1/programs/{pid}/modules",
        json={"program_id": str(pid), "name": "Analyse", "code": "AN"},
    )
    assert response.status_code == 201
    mock_module_service.create.assert_awaited_once_with(program_id=pid, name="Analyse", code="AN")


@pytest.mark.anyio
async def test_delete_module_success(admin_client, mock_module_service):
    mock_module_service.delete.return_value = None
    response = await admin_client.delete(f"/api/v1/modules/{uuid.uuid4()}")
    assert response.status_code == 204


# --- Course & Group Router ---

def _make_course_read():
    return {
        "id": str(uuid.uuid4()),
        "semester": "S1-2025",
        "module_id": str(uuid.uuid4()),
        "module_name": "Analyse",
        "professor_user_id": str(uuid.uuid4()),
        "professor_full_name": "Bob Martin",
        "group_id": str(uuid.uuid4()),
        "group_label": "G1",
    }


def _make_group_read():
    return {
        "id": str(uuid.uuid4()),
        "label": "TD1",
        "academic_year": "2025-2026",
        "program_id": str(uuid.uuid4()),
        "program_name": "Informatique",
    }


@pytest.mark.anyio
async def test_get_course_success(admin_client, mock_course_service):
    mock_course_service.get_by_id.return_value = _make_course_read()
    response = await admin_client.get(f"/api/v1/courses/{uuid.uuid4()}")
    assert response.status_code == 200
    mock_course_service.get_by_id.assert_awaited_once()


@pytest.mark.anyio
async def test_create_course_success(professor_client, mock_course_service):
    mock_course_service.create.return_value = _make_course_read()
    module_id = uuid.uuid4()
    group_id = uuid.uuid4()
    payload = {
        "module_id": str(module_id),
        "group_id": str(group_id),
        "semester": "S1-2025",
    }
    response = await professor_client.post("/api/v1/courses", json=payload)
    assert response.status_code == 201
    mock_course_service.create.assert_awaited_once_with(
        module_id=module_id,
        group_id=group_id,
        professor_user_id="00000000-0000-4000-a000-000000000002",
        semester="S1-2025",
    )


@pytest.mark.anyio
async def test_list_my_courses_success(professor_client, mock_course_service):
    from app.domain.repositories.pagination import CursorPage

    mock_course_service.list_by_professor.return_value = CursorPage(
        items=[_make_course_read()], next_cursor=None, has_more=False
    )
    response = await professor_client.get("/api/v1/courses/mine")
    assert response.status_code == 200
    mock_course_service.list_by_professor.assert_awaited_once_with(
        "00000000-0000-4000-a000-000000000002", cursor=None, limit=50
    )


@pytest.mark.anyio
async def test_create_course_requires_professor(student_client, mock_course_service):
    payload = {
        "module_id": str(uuid.uuid4()),
        "group_id": str(uuid.uuid4()),
        "semester": "S1-2025",
    }
    response = await student_client.post("/api/v1/courses", json=payload)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_delete_course_success(professor_client, mock_course_service):
    mock_course_service.delete.return_value = None
    course_id = uuid.uuid4()
    response = await professor_client.delete(f"/api/v1/courses/{course_id}")
    assert response.status_code == 204
    mock_course_service.delete.assert_awaited_once_with(
        course_id, "00000000-0000-4000-a000-000000000002"
    )


@pytest.mark.anyio
async def test_update_course_success(professor_client, mock_course_service):
    mock_course_service.update_semester.return_value = _make_course_read()
    course_id = uuid.uuid4()
    response = await professor_client.patch(
        f"/api/v1/courses/{course_id}", json={"semester": "S2-2025"}
    )
    assert response.status_code == 200
    mock_course_service.update_semester.assert_awaited_once_with(
        course_id=course_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
        semester="S2-2025",
    )


def _make_student_public():
    return {
        **_make_user_public(UserRole.STUDENT),
        "student_number": "E12345",
        "group_id": str(uuid.uuid4()),
        "enrollment_year": 2025,
        "academic_status": "active",
        "level": "L3",
    }


@pytest.mark.anyio
async def test_list_course_students_success(professor_client, mock_course_service):
    mock_course_service.list_students.return_value = [_make_student_public()]
    course_id = uuid.uuid4()
    response = await professor_client.get(f"/api/v1/courses/{course_id}/students")
    assert response.status_code == 200
    assert len(response.json()) == 1
    mock_course_service.list_students.assert_awaited_once_with(
        course_id, "00000000-0000-4000-a000-000000000002"
    )


@pytest.mark.anyio
async def test_list_course_students_requires_professor(student_client, mock_course_service):
    response = await student_client.get(f"/api/v1/courses/{uuid.uuid4()}/students")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_group_success(admin_client, mock_group_service):
    mock_group_service.get_by_id.return_value = _make_group_read()
    response = await admin_client.get(f"/api/v1/groups/{uuid.uuid4()}")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_list_groups_by_program(admin_client, mock_group_service):
    mock_group_service.list_by_program.return_value = CursorPage(
        items=[_make_group_read()], next_cursor=None, has_more=False
    )
    response = await admin_client.get(f"/api/v1/programs/{uuid.uuid4()}/groups")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_create_group_success(admin_client, mock_group_service):
    mock_group_service.create.return_value = _make_group_read()
    pid = uuid.uuid4()
    # GroupCreate exige program_id + academic_year dans le body
    response = await admin_client.post(
        f"/api/v1/programs/{pid}/groups",
        json={"program_id": str(pid), "label": "TD1", "academic_year": "2025-2026"},
    )
    assert response.status_code == 201
    mock_group_service.create.assert_awaited_once_with(program_id=pid, label="TD1", academic_year="2025-2026")


@pytest.mark.anyio
async def test_delete_group_success(admin_client, mock_group_service):
    mock_group_service.delete.return_value = None
    response = await admin_client.delete(f"/api/v1/groups/{uuid.uuid4()}")
    assert response.status_code == 204


# --- Enrollment Router ---

def _make_enrollment_read():
    return {
        "id": str(uuid.uuid4()),
        "is_active": True,
        "enrolled_at": "2024-01-01T00:00:00Z",
        "student_id": str(uuid.uuid4()),
        "student_full_name": "Alice Dupont",
        "module_id": str(uuid.uuid4()),
        "module_name": "Analyse",
    }


@pytest.mark.anyio
async def test_get_enrollment_success(admin_client, mock_enrollment_service):
    mock_enrollment_service.get_by_id.return_value = _make_enrollment_read()
    response = await admin_client.get(f"/api/v1/enrollments/{uuid.uuid4()}")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_list_my_enrollments(student_client, mock_enrollment_service):
    mock_enrollment_service.list_by_student.return_value = CursorPage(
        items=[_make_enrollment_read()], next_cursor=None, has_more=False
    )
    response = await student_client.get("/api/v1/students/me/enrollments")
    assert response.status_code == 200
    mock_enrollment_service.list_by_student.assert_awaited_once()


@pytest.mark.anyio
async def test_list_enrollments_by_module(admin_client, mock_enrollment_service):
    mock_enrollment_service.list_by_module.return_value = CursorPage(
        items=[_make_enrollment_read()], next_cursor=None, has_more=False
    )
    response = await admin_client.get(f"/api/v1/modules/{uuid.uuid4()}/enrollments")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_enroll_student_success(admin_client, mock_enrollment_service):
    mock_enrollment_service.enroll.return_value = _make_enrollment_read()
    student_id = uuid.uuid4()
    module_id = uuid.uuid4()
    payload = {
        "student_id": str(student_id),
        "module_id": str(module_id),
    }
    response = await admin_client.post("/api/v1/enrollments", json=payload)
    assert response.status_code == 201
    mock_enrollment_service.enroll.assert_awaited_once_with(
        student_id=student_id,
        module_id=module_id,
    )


@pytest.mark.anyio
async def test_deactivate_enrollment_success(admin_client, mock_enrollment_service):
    enrollment_id = uuid.uuid4()
    mock_enrollment_service.unenroll.return_value = _make_enrollment_read()
    response = await admin_client.post(f"/api/v1/enrollments/{enrollment_id}/deactivate")
    assert response.status_code == 200
    mock_enrollment_service.unenroll.assert_awaited_once_with(enrollment_id)