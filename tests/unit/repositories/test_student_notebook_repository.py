"""
Tests du StudentNotebookRepository — couvre create() et list_by_student().
"""
import uuid

import pytest

from app.domain.models.identity.user import AcademicStatus, UserRole
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
from app.domain.repositories.student_notebook_repository import (
    SQLAlchemyStudentNotebookRepository,
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


@pytest.mark.anyio
class TestStudentNotebookRepositoryCreate:
    async def test_create_nominal_with_submission(self, db_session, student, module, exercise):
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        submission = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(
            student_id=student.id, module_id=module.id,
            notebook_id="nb-abc-123", submission_id=submission.id,
        )

        assert record.id is not None
        assert record.student_id == student.id
        assert record.module_id == module.id
        assert record.submission_id == submission.id
        assert record.notebook_id == "nb-abc-123"

    async def test_create_without_submission(self, db_session, student, module):
        """submission_id nullable — même principe que RecommendedExercise."""
        repo = SQLAlchemyStudentNotebookRepository(db_session)

        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-xyz")

        assert record.submission_id is None


@pytest.mark.anyio
class TestStudentNotebookRepositoryListByStudent:
    async def test_list_empty(self, db_session, student):
        repo = SQLAlchemyStudentNotebookRepository(db_session)

        result = await repo.list_by_student(student.id)

        assert result == []

    async def test_list_excludes_other_student(self, db_session, student, module, group):
        from app.domain.models.identity.user import Student

        other = Student(
            id=uuid.uuid4(), role=UserRole.STUDENT, first_name="Bob", last_name="Martin",
            email=f"other_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
            student_number=f"STU{uuid.uuid4().hex[:6]}", group_id=group.id,
            enrollment_year=2025, academic_status=AcademicStatus.ACTIVE, level="L3",
        )
        db_session.add(other)
        await db_session.flush()

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        await repo.create(student_id=other.id, module_id=module.id, notebook_id="nb-other")
        mine = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-mine")

        result = await repo.list_by_student(student.id)

        assert len(result) == 1
        assert result[0].id == mine.id


@pytest.mark.anyio
class TestStudentNotebookRepositoryArtifactUpdates:
    """Câblage formats de sortie (§7, Partie 2/2)."""

    async def test_update_audio_overview_path(self, db_session, student, module):
        from app.domain.models.assessment.student_notebook import GenerationStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        await repo.update_audio_overview_path(record.id, "notebooklm/audio/abc.mp3")

        refreshed = await repo.get_by_id(record.id)
        assert refreshed.audio_overview_path == "notebooklm/audio/abc.mp3"
        assert refreshed.audio_overview_status == GenerationStatus.READY
        assert refreshed.flashcards_path is None

    async def test_update_flashcards_path(self, db_session, student, module):
        from app.domain.models.assessment.student_notebook import GenerationStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        await repo.update_flashcards_path(record.id, "notebooklm/flashcards/abc.json")

        refreshed = await repo.get_by_id(record.id)
        assert refreshed.flashcards_path == "notebooklm/flashcards/abc.json"
        assert refreshed.flashcards_status == GenerationStatus.READY

    async def test_audio_and_flashcards_status_default_to_not_requested(self, db_session, student, module):
        from app.domain.models.assessment.student_notebook import GenerationStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        assert record.audio_overview_status == GenerationStatus.NOT_REQUESTED
        assert record.flashcards_status == GenerationStatus.NOT_REQUESTED

    async def test_update_audio_overview_status_to_pending_then_failed(self, db_session, student, module):
        from app.domain.models.assessment.student_notebook import GenerationStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        await repo.update_audio_overview_status(record.id, GenerationStatus.PENDING)
        refreshed = await repo.get_by_id(record.id)
        assert refreshed.audio_overview_status == GenerationStatus.PENDING
        assert refreshed.audio_overview_path is None

        await repo.update_audio_overview_status(record.id, GenerationStatus.FAILED)
        refreshed = await repo.get_by_id(record.id)
        assert refreshed.audio_overview_status == GenerationStatus.FAILED

    async def test_update_flashcards_status_to_pending_then_failed(self, db_session, student, module):
        from app.domain.models.assessment.student_notebook import GenerationStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        await repo.update_flashcards_status(record.id, GenerationStatus.PENDING)
        refreshed = await repo.get_by_id(record.id)
        assert refreshed.flashcards_status == GenerationStatus.PENDING

        await repo.update_flashcards_status(record.id, GenerationStatus.FAILED)
        refreshed = await repo.get_by_id(record.id)
        assert refreshed.flashcards_status == GenerationStatus.FAILED

    async def test_video_overview_status_defaults_to_not_requested(self, db_session, student, module):
        from app.domain.models.assessment.student_notebook import VideoOverviewStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        assert record.video_overview_status == VideoOverviewStatus.NOT_REQUESTED
        assert record.video_overview_path is None

    async def test_update_video_overview_status_to_pending_without_path(self, db_session, student, module):
        from app.domain.models.assessment.student_notebook import VideoOverviewStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        await repo.update_video_overview_status(record.id, VideoOverviewStatus.PENDING)

        refreshed = await repo.get_by_id(record.id)
        assert refreshed.video_overview_status == VideoOverviewStatus.PENDING
        assert refreshed.video_overview_path is None

    async def test_update_video_overview_status_to_ready_with_path(self, db_session, student, module):
        from app.domain.models.assessment.student_notebook import VideoOverviewStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")
        await repo.update_video_overview_status(record.id, VideoOverviewStatus.PENDING)

        await repo.update_video_overview_status(
            record.id, VideoOverviewStatus.READY, path="notebooklm/video/abc.mp4",
        )

        refreshed = await repo.get_by_id(record.id)
        assert refreshed.video_overview_status == VideoOverviewStatus.READY
        assert refreshed.video_overview_path == "notebooklm/video/abc.mp4"

    async def test_repli_video_overview_status_to_not_requested_on_real_failure(self, db_session, student, module):
        """Un échec réel ne doit jamais laisser le statut bloqué sur pending indéfiniment (cf. docstring modèle)."""
        from app.domain.models.assessment.student_notebook import VideoOverviewStatus

        repo = SQLAlchemyStudentNotebookRepository(db_session)
        record = await repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")
        await repo.update_video_overview_status(record.id, VideoOverviewStatus.PENDING)

        await repo.update_video_overview_status(record.id, VideoOverviewStatus.NOT_REQUESTED)

        refreshed = await repo.get_by_id(record.id)
        assert refreshed.video_overview_status == VideoOverviewStatus.NOT_REQUESTED
