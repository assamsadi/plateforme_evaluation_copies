import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository


async def seed_exercise_and_student(db_session):
    """Helper to create necessary parent entities in DB."""
    user_repo = SQLAlchemyUserRepository(db_session)
    
    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add_all([group, module])
    await db_session.flush()

    prof = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com",
        hashed_password="hash",
        first_name="Prof",
        last_name="Doc",
        department="CS",
        title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com",
        hashed_password="hash",
        first_name="Bob",
        last_name="Student",
        student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id,
        enrollment_year=2024,
        level="L3",
    )

    exercise = Exercise(
        module_id=module.id,
        created_by_professor_id=prof.id,
        title="Test Exercise",
        status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    return exercise, student


@pytest.mark.anyio
async def test_submission_repository_attempt_increment_and_uniqueness(db_session):
    exercise, student = await seed_exercise_and_student(db_session)
    repo = SQLAlchemySubmissionRepository(db_session)

    # First attempt should be 1
    next_att = await repo.get_next_attempt_number(exercise.id, student.id)
    assert next_att == 1

    sub1 = await repo.create(exercise.id, student.id, attempt_number=1)
    assert sub1.attempt_number == 1
    assert sub1.status == SubmissionStatus.PENDING_OCR

    # Second attempt should be 2
    next_att2 = await repo.get_next_attempt_number(exercise.id, student.id)
    assert next_att2 == 2

    sub2 = await repo.create(exercise.id, student.id, attempt_number=2)
    assert sub2.attempt_number == 2

    assert await repo.count_attempts(exercise.id, student.id) == 2

    # Creating another submission with duplicate attempt number 1 must raise IntegrityError
    async with db_session.begin_nested():
        with pytest.raises(IntegrityError):
            await repo.create(exercise.id, student.id, attempt_number=1)


@pytest.mark.anyio
async def test_submission_repository_update_status(db_session):
    exercise, student = await seed_exercise_and_student(db_session)
    repo = SQLAlchemySubmissionRepository(db_session)

    sub = await repo.create(exercise.id, student.id, attempt_number=1)
    assert sub.status == SubmissionStatus.PENDING_OCR

    updated = await repo.update_status(sub.id, SubmissionStatus.EVALUATED)
    assert updated is not None
    assert updated.status == SubmissionStatus.EVALUATED

    reloaded = await repo.get_by_id(sub.id)
    assert reloaded.status == SubmissionStatus.EVALUATED
