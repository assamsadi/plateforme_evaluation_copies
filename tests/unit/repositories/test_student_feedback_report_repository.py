"""
Tests du StudentFeedbackReportRepository (chantier Feedback_Agent, §7) —
couvre create() et get_by_submission().
"""
import uuid

import pytest

from app.domain.models.identity.user import AcademicStatus, UserRole
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
from app.domain.repositories.student_feedback_report_repository import (
    SQLAlchemyStudentFeedbackReportRepository,
)
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository


@pytest.fixture
async def program(db_session):
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Test Program {uuid.uuid4().hex[:8]}", code=f"TP{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def module(db_session, program):
    repo = SQLAlchemyModuleRepository(db_session)
    return await repo.create(program_id=program.id, name=f"Test Module {uuid.uuid4().hex[:8]}", code=f"TM{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def group(db_session, program):
    repo = SQLAlchemyGroupRepository(db_session)
    return await repo.create(program_id=program.id, label=f"G{uuid.uuid4().hex[:6]}", academic_year="2025-2026")


@pytest.fixture
async def professor(db_session):
    from app.domain.models.identity.user import Professor

    p = Professor(
        id=uuid.uuid4(), role=UserRole.PROFESSOR, first_name="Bob", last_name="Martin",
        email=f"prof_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
        department="Informatique", title="Dr", employee_number=f"EMP{uuid.uuid4().hex[:6]}",
    )
    db_session.add(p)
    await db_session.flush()
    return p


@pytest.fixture
async def student(db_session, group):
    from app.domain.models.identity.user import Student

    s = Student(
        id=uuid.uuid4(), role=UserRole.STUDENT, first_name="Alice", last_name="Dupont",
        email=f"student_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
        student_number=f"STU{uuid.uuid4().hex[:6]}", group_id=group.id,
        enrollment_year=2025, academic_status=AcademicStatus.ACTIVE, level="L3",
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.fixture
async def exercise(db_session, module, professor):
    from app.domain.models.assessment.exercise import Exercise, ExerciseStatus

    e = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice test", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(e)
    await db_session.flush()
    return e


@pytest.fixture
async def submission(db_session, student, exercise):
    sub_repo = SQLAlchemySubmissionRepository(db_session)
    return await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)


@pytest.mark.anyio
class TestStudentFeedbackReportRepositoryCreate:
    async def test_create_nominal(self, db_session, student, module, submission):
        repo = SQLAlchemyStudentFeedbackReportRepository(db_session)

        record = await repo.create(
            student_id=student.id, module_id=module.id, submission_id=submission.id,
            feedback_text="Relis ta boucle : que vérifies-tu avant d'y entrer ?",
            competencies_addressed=["algorithmic_structuring"],
        )

        assert record.id is not None
        assert record.student_id == student.id
        assert record.module_id == module.id
        assert record.submission_id == submission.id
        assert "?" in record.feedback_text
        assert record.competencies_addressed == ["algorithmic_structuring"]


@pytest.mark.anyio
class TestStudentFeedbackReportRepositoryGetBySubmission:
    async def test_returns_none_when_absent(self, db_session):
        repo = SQLAlchemyStudentFeedbackReportRepository(db_session)

        result = await repo.get_by_submission(uuid.uuid4())

        assert result is None

    async def test_returns_the_report_for_that_submission(self, db_session, student, module, submission):
        repo = SQLAlchemyStudentFeedbackReportRepository(db_session)
        created = await repo.create(
            student_id=student.id, module_id=module.id, submission_id=submission.id,
            feedback_text="Une question ?", competencies_addressed=["data_and_planning"],
        )

        result = await repo.get_by_submission(submission.id)

        assert result is not None
        assert result.id == created.id

    async def test_does_not_return_another_submissions_report(
        self, db_session, student, module, exercise, submission,
    ):
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        other_submission = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=2)

        repo = SQLAlchemyStudentFeedbackReportRepository(db_session)
        await repo.create(
            student_id=student.id, module_id=module.id, submission_id=submission.id,
            feedback_text="Une question sur la première tentative ?", competencies_addressed=[],
        )

        result = await repo.get_by_submission(other_submission.id)

        assert result is None
