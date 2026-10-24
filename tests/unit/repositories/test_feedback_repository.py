"""
Tests du FeedbackRepository — couvre toutes les méthodes publiques :
- get_or_create (création, idempotence)
- get_by_id (nominal, non trouvé)
- get_by_submission_and_question (nominal, non trouvé)
- add_version (nominal AI, nominal TEACHER, incrémentation version_number)
- get_latest_version (nominal, vide)
- list_versions (nominal, vide, tri par version_number)
"""
import uuid
from decimal import Decimal

import pytest

from app.domain.models.assessment.feedback import Feedback
from app.domain.models.assessment.feedback_version import FeedbackAuthorType, FeedbackVersion
from app.domain.models.identity.user import Student, Professor, UserRole, AcademicStatus
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.feedback_repository import SQLAlchemyFeedbackRepository
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
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
    prof = Professor(
        id=uuid.uuid4(),
        role=UserRole.PROFESSOR,
        first_name="Bob",
        last_name="Martin",
        email=f"prof_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
        department="Informatique",
        title="Dr",
        employee_number=f"EMP{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prof)
    await db_session.flush()
    return prof


@pytest.fixture
async def student(db_session, group):
    s = Student(
        id=uuid.uuid4(),
        role=UserRole.STUDENT,
        first_name="Alice",
        last_name="Dupont",
        email=f"student_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
        student_number=f"STU{uuid.uuid4().hex[:6]}",
        group_id=group.id,
        enrollment_year=2025,
        academic_status=AcademicStatus.ACTIVE,
        level="L3",
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.fixture
async def exercise(db_session, module, professor):
    repo = SQLAlchemyExerciseRepository(db_session)
    return await repo.create_with_questions(
        module_id=module.id,
        created_by_professor_id=professor.id,
        title="Test Exercise",
        description=None,
        questions_data=[
            {"order": 1, "statement": "Q1", "bareme": {"points": Decimal("5.00"), "criteria": []}},
            {"order": 2, "statement": "Q2", "bareme": {"points": Decimal("5.00"), "criteria": []}},
        ],
    )


@pytest.fixture
async def submission(db_session, exercise, student):
    repo = SQLAlchemySubmissionRepository(db_session)
    return await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)


@pytest.fixture
async def feedback(db_session, submission, exercise):
    repo = SQLAlchemyFeedbackRepository(db_session)
    return await repo.get_or_create(submission_id=submission.id, question_id=exercise.questions[0].id)


@pytest.mark.anyio
class TestFeedbackRepositoryGetOrCreate:
    """Tests de la méthode get_or_create()."""

    async def test_creates_new_feedback(self, db_session, submission, exercise):
        repo = SQLAlchemyFeedbackRepository(db_session)

        feedback = await repo.get_or_create(submission_id=submission.id, question_id=exercise.questions[0].id)

        assert feedback.id is not None
        assert feedback.submission_id == submission.id
        assert feedback.question_id == exercise.questions[0].id

    async def test_returns_existing_feedback(self, db_session, submission, exercise):
        """get_or_create est idempotent : un deuxième appel retourne le même feedback."""
        repo = SQLAlchemyFeedbackRepository(db_session)
        first = await repo.get_or_create(submission_id=submission.id, question_id=exercise.questions[0].id)
        second = await repo.get_or_create(submission_id=submission.id, question_id=exercise.questions[0].id)

        assert first.id == second.id


@pytest.mark.anyio
class TestFeedbackRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(self, db_session, feedback):
        repo = SQLAlchemyFeedbackRepository(db_session)

        found = await repo.get_by_id(feedback.id)

        assert found is not None
        assert found.id == feedback.id

    async def test_get_by_id_not_found_returns_none(self, db_session):
        repo = SQLAlchemyFeedbackRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestFeedbackRepositoryGetBySubmissionAndQuestion:
    """Tests de la méthode get_by_submission_and_question()."""

    async def test_found(self, db_session, submission, exercise):
        repo = SQLAlchemyFeedbackRepository(db_session)
        await repo.get_or_create(submission_id=submission.id, question_id=exercise.questions[0].id)

        found = await repo.get_by_submission_and_question(submission.id, exercise.questions[0].id)

        assert found is not None
        assert found.submission_id == submission.id
        assert found.question_id == exercise.questions[0].id

    async def test_not_found_returns_none(self, db_session, submission, exercise):
        repo = SQLAlchemyFeedbackRepository(db_session)

        found = await repo.get_by_submission_and_question(submission.id, exercise.questions[0].id)

        assert found is None


@pytest.mark.anyio
class TestFeedbackRepositoryAddVersion:
    """Tests de la méthode add_version()."""

    async def test_add_ai_version(self, db_session, feedback):
        repo = SQLAlchemyFeedbackRepository(db_session)
        version = await repo.add_version(
            feedback_id=feedback.id,
            content="Feedback IA initial",
            author_type=FeedbackAuthorType.AI,
            author_user_id=None,
        )

        assert version.id is not None
        assert version.feedback_id == feedback.id
        assert version.version_number == 1
        assert version.content == "Feedback IA initial"
        assert version.author_type == FeedbackAuthorType.AI
        assert version.author_user_id is None

    async def test_add_teacher_version(self, db_session, feedback, professor):
        repo = SQLAlchemyFeedbackRepository(db_session)
        version = await repo.add_version(
            feedback_id=feedback.id,
            content="Feedback modifié par le prof",
            author_type=FeedbackAuthorType.TEACHER,
            author_user_id=professor.id,
        )

        assert version.version_number == 1
        assert version.author_type == FeedbackAuthorType.TEACHER
        assert version.author_user_id == professor.id

    async def test_version_number_increments(self, db_session, feedback):
        """add_version incrémente automatiquement version_number."""
        repo = SQLAlchemyFeedbackRepository(db_session)
        v1 = await repo.add_version(feedback.id, "V1", FeedbackAuthorType.AI, None)
        v2 = await repo.add_version(feedback.id, "V2", FeedbackAuthorType.TEACHER, None)
        v3 = await repo.add_version(feedback.id, "V3", FeedbackAuthorType.AI, None)

        assert v1.version_number == 1
        assert v2.version_number == 2
        assert v3.version_number == 3


@pytest.mark.anyio
class TestFeedbackRepositoryGetLatestVersion:
    """Tests de la méthode get_latest_version()."""

    async def test_empty_returns_none(self, db_session, feedback):
        repo = SQLAlchemyFeedbackRepository(db_session)

        result = await repo.get_latest_version(feedback.id)

        assert result is None

    async def test_returns_latest(self, db_session, feedback):
        """get_latest_version retourne la version avec le plus grand version_number."""
        repo = SQLAlchemyFeedbackRepository(db_session)
        v1 = await repo.add_version(feedback.id, "V1", FeedbackAuthorType.AI, None)
        v2 = await repo.add_version(feedback.id, "V2", FeedbackAuthorType.TEACHER, None)
        v3 = await repo.add_version(feedback.id, "V3", FeedbackAuthorType.AI, None)

        latest = await repo.get_latest_version(feedback.id)

        assert latest is not None
        assert latest.id == v3.id
        assert latest.version_number == 3


@pytest.mark.anyio
class TestFeedbackRepositoryListVersions:
    """Tests de la méthode list_versions()."""

    async def test_empty(self, db_session, feedback):
        repo = SQLAlchemyFeedbackRepository(db_session)

        result = await repo.list_versions(feedback.id)

        assert result == []

    async def test_nominal(self, db_session, feedback):
        """list_versions retourne toutes les versions triées par version_number."""
        repo = SQLAlchemyFeedbackRepository(db_session)
        v1 = await repo.add_version(feedback.id, "V1", FeedbackAuthorType.AI, None)
        v2 = await repo.add_version(feedback.id, "V2", FeedbackAuthorType.TEACHER, None)
        v3 = await repo.add_version(feedback.id, "V3", FeedbackAuthorType.AI, None)

        result = await repo.list_versions(feedback.id)

        assert len(result) == 3
        assert result[0].version_number == 1
        assert result[1].version_number == 2
        assert result[2].version_number == 3


    async def test_excludes_other_feedback(self, db_session, feedback, submission, exercise):
        
   
        repo = SQLAlchemyFeedbackRepository(db_session)

        from app.domain.models.assessment.feedback import Feedback as FeedbackModel
        other = FeedbackModel(submission_id=submission.id, question_id=exercise.questions[1].id)
        db_session.add(other)
        await db_session.flush()

        await repo.add_version(feedback.id, "Mine", FeedbackAuthorType.AI, None)
        await repo.add_version(other.id, "Other", FeedbackAuthorType.AI, None)

        result = await repo.list_versions(feedback.id)

        assert len(result) == 1
        assert result[0].content == "Mine"
            