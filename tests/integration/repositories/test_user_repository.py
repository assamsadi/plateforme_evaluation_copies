import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.academic.group import Group
from app.domain.models.academic.program import Program
from app.domain.models.identity.user import Admin, Professor, Student
from app.domain.repositories.user_repository import SQLAlchemyUserRepository


@pytest.mark.anyio
async def test_user_repository_crud_and_polymorphism(db_session):
    repo = SQLAlchemyUserRepository(db_session)

    # 1. Create Admin
    admin_email = f"admin_{uuid.uuid4()}@test.com"
    admin = await repo.create_admin(
        email=admin_email,
        hashed_password="hash",
        first_name="Admin",
        last_name="User",
    )
    assert isinstance(admin, Admin)
    assert admin.id is not None

    # Polymorphic get_by_id returns Admin subclass
    loaded_admin = await repo.get_by_id(admin.id)
    assert isinstance(loaded_admin, Admin)
    assert loaded_admin.email == admin_email

    # 2. Create Professor
    prof_email = f"prof_{uuid.uuid4()}@test.com"
    emp_num = f"EMP_{uuid.uuid4()}"[:20]
    prof = await repo.create_professor(
        email=prof_email,
        hashed_password="hash",
        first_name="Prof",
        last_name="Xavier",
        department="CS",
        title="Dr",
        employee_number=emp_num,
    )
    assert isinstance(prof, Professor)

    loaded_prof = await repo.get_by_email(prof_email)
    assert isinstance(loaded_prof, Professor)
    assert loaded_prof.employee_number == emp_num

    # 3. Create Student (requires Group -> Program)
    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"C_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    db_session.add(group)
    await db_session.flush()

    stu_email = f"stu_{uuid.uuid4()}@test.com"
    stu_num = f"STU_{uuid.uuid4()}"[:20]
    student = await repo.create_student(
        email=stu_email,
        hashed_password="hash",
        first_name="Alice",
        last_name="Student",
        student_number=stu_num,
        group_id=group.id,
        enrollment_year=2024,
        level="L3",
    )
    assert isinstance(student, Student)

    loaded_student = await repo.get_by_id(student.id)
    assert isinstance(loaded_student, Student)
    assert loaded_student.student_number == stu_num


@pytest.mark.anyio
async def test_user_repository_email_uniqueness(db_session):
    repo = SQLAlchemyUserRepository(db_session)
    email = f"unique_{uuid.uuid4()}@test.com"

    await repo.create_admin(
        email=email,
        hashed_password="hash",
        first_name="First",
        last_name="User",
    )

    # Creating another user with duplicate email must raise IntegrityError
    async with db_session.begin_nested():
        with pytest.raises(IntegrityError):
            await repo.create_admin(
                email=email,
                hashed_password="hash",
                first_name="Second",
                last_name="User",
            )
