"""
Tests d'intégration de SubmissionService.create_submission() — DB réelle
(contrairement aux tests unitaires qui mockent user_repo et masquent donc
tout vrai comportement de lazy-loading SQLAlchemy).
"""
import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.repositories.course_repository import SQLAlchemyCourseRepository
from app.domain.repositories.enrollment_repository import SQLAlchemyEnrollmentRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.services.submission_service import SubmissionService


async def _seed_library_exercise_and_enrolled_student(db_session):
    """Étudiant réel + module + exercice ARCHIVED_IN_LIBRARY + inscription réelle."""
    user_repo = SQLAlchemyUserRepository(db_session)

    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add_all([group, module])
    await db_session.flush()

    prof = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Doc", department="CS", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Student", student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id, enrollment_year=2024, level="L3",
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=prof.id,
        title="Exercice Library", status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
    )
    db_session.add(exercise)
    await db_session.flush()

    enrollment_repo = SQLAlchemyEnrollmentRepository(db_session)
    await enrollment_repo.create(student.id, module.id)

    return exercise, student, enrollment_repo


@pytest.mark.anyio
async def test_create_submission_reads_real_student_academic_status(db_session):
    """
    Bug corrigé (espace étudiant, trouvé en testant un vrai dépôt de copie
    de bout en bout) : create_submission lisait user.academic_status après
    un user_repo.get_by_id() simple (table users de base uniquement) — un
    Student RÉEL chargé depuis la DB nécessite un lazy-load pour ce champ
    spécifique au sous-type, ce qui plante en async (sqlalchemy.exc.
    MissingGreenlet: "greenlet_spawn has not been called"). Jamais détecté
    avant : tous les tests unitaires mockent user_repo avec un objet où
    academic_status est déjà un attribut Python plat. Corrigé en utilisant
    get_by_id_with_role_details() (eager load via with_polymorphic).
    """
    exercise, student, enrollment_repo = await _seed_library_exercise_and_enrolled_student(db_session)

    service = SubmissionService(
        submission_repo=SQLAlchemySubmissionRepository(db_session),
        exercise_repo=SQLAlchemyExerciseRepository(db_session),
        course_repo=SQLAlchemyCourseRepository(db_session),
        user_repo=SQLAlchemyUserRepository(db_session),
        enrollment_repo=enrollment_repo,
        storage_service=AsyncMock(),
        event_publisher=AsyncMock(),
    )

    result = await service.create_submission(
        exercise_id=exercise.id, student_id=student.id,
        document_bytes=b"%PDF-1.4 fake", mime_type="application/pdf",
    )

    assert result.status == SubmissionStatus.PENDING_OCR
    assert result.exercise_id == exercise.id
    assert result.student_id == student.id


@pytest.mark.anyio
async def test_create_submission_survives_event_publish_failure(db_session):
    """
    Bug corrigé (espace étudiant) : publish_submission_created() n'était
    pas protégé — un broker Kafka injoignable faisait échouer TOUTE la
    requête en 500, alors que la Submission ET le document étaient déjà
    persistés avec succès. Une nouvelle tentative de l'étudiant aurait
    alors échoué sur AlreadySubmittedError (ligne déjà créée), un état
    confus (la copie EST déposée mais le client voit une erreur). Best-
    effort désormais : la soumission doit réussir même si l'événement échoue.
    """
    exercise, student, enrollment_repo = await _seed_library_exercise_and_enrolled_student(db_session)

    failing_publisher = AsyncMock()
    failing_publisher.publish_submission_created.side_effect = ConnectionError("Kafka injoignable")

    service = SubmissionService(
        submission_repo=SQLAlchemySubmissionRepository(db_session),
        exercise_repo=SQLAlchemyExerciseRepository(db_session),
        course_repo=SQLAlchemyCourseRepository(db_session),
        user_repo=SQLAlchemyUserRepository(db_session),
        enrollment_repo=enrollment_repo,
        storage_service=AsyncMock(),
        event_publisher=failing_publisher,
    )

    result = await service.create_submission(
        exercise_id=exercise.id, student_id=student.id,
        document_bytes=b"%PDF-1.4 fake", mime_type="application/pdf",
    )

    assert result.status == SubmissionStatus.PENDING_OCR
    failing_publisher.publish_submission_created.assert_awaited_once()
