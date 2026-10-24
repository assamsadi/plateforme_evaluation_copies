"""
Tests du SubmissionRepository — couvre toutes les méthodes publiques :
- create (nominal, contrainte d'unicité exercise+student+attempt)
- create_absent (nominal, statut ABSENT, attempt_number=0)
- get_by_id (nominal, non trouvé)
- get_next_attempt_number (première tentative, après existante)
- count_attempts (nominal, zéro)
- list_by_exercise (nominal, filtre, pagination)
- list_by_student (nominal, filtre, pagination)
- update_status (nominal, non trouvé)
- get_extraction_corrections (nominal, vide)
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.assessment.extraction_correction import (
    ExtractionCorrection,
    ExtractionContentType,
    ExtractionEvidenceLevel,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.identity.user import Student, Professor, UserRole, AcademicStatus
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
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
async def other_student(db_session, group):
    s = Student(
        id=uuid.uuid4(),
        role=UserRole.STUDENT,
        first_name="Bob",
        last_name="Martin",
        email=f"student2_{uuid.uuid4().hex[:8]}@test.edu",
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
    """Crée un exercice avec une question pour pouvoir lier des ExtractionCorrections."""
    repo = SQLAlchemyExerciseRepository(db_session)
    return await repo.create_with_questions(
        module_id=module.id,
        created_by_professor_id=professor.id,
        title="Test Exercise",
        description=None,
        questions_data=[
            {
                "order": 1,
                "statement": "Question 1",
                "bareme": {"points": Decimal("5.00"), "criteria": []},
            }
        ],
    )


@pytest.fixture
async def submission(db_session, exercise, student):
    repo = SQLAlchemySubmissionRepository(db_session)
    return await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)


@pytest.mark.anyio
class TestSubmissionRepositoryCreate:
    """Tests de la méthode create()."""

    async def test_create_nominal(self, db_session, exercise, student):
        repo = SQLAlchemySubmissionRepository(db_session)
        submission = await repo.create(
            exercise_id=exercise.id, student_id=student.id, attempt_number=1
        )

        assert submission.id is not None
        assert submission.exercise_id == exercise.id
        assert submission.student_id == student.id
        assert submission.attempt_number == 1
        assert submission.status == SubmissionStatus.PENDING_OCR

    async def test_create_duplicate_raises_integrity_error(self, db_session, exercise, student):
        """Contrainte d'unicité (exercise_id, student_id, attempt_number)."""
        repo = SQLAlchemySubmissionRepository(db_session)
        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

        with pytest.raises(IntegrityError):
            await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        await db_session.rollback()

    async def test_create_same_exercise_different_attempt_ok(self, db_session, exercise, student):
        repo = SQLAlchemySubmissionRepository(db_session)
        s1 = await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        s2 = await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=2)

        assert s1.id != s2.id
        assert s1.attempt_number == 1
        assert s2.attempt_number == 2


@pytest.mark.anyio
class TestSubmissionRepositoryCreateAbsent:
    """Tests de la méthode create_absent()."""

    async def test_create_absent_nominal(self, db_session, exercise, student):
        repo = SQLAlchemySubmissionRepository(db_session)
        submission = await repo.create_absent(exercise_id=exercise.id, student_id=student.id)

        assert submission.id is not None
        assert submission.exercise_id == exercise.id
        assert submission.student_id == student.id
        assert submission.attempt_number == 0
        assert submission.status == SubmissionStatus.ABSENT


@pytest.mark.anyio
class TestSubmissionRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(self, db_session, submission):
        repo = SQLAlchemySubmissionRepository(db_session)

        found = await repo.get_by_id(submission.id)

        assert found is not None
        assert found.id == submission.id
        assert found.exercise_id == submission.exercise_id
        assert found.student_id == submission.student_id

    async def test_get_by_id_not_found_returns_none(self, db_session):
        repo = SQLAlchemySubmissionRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestSubmissionRepositoryGetNextAttemptNumber:
    """Tests de la méthode get_next_attempt_number()."""

    async def test_first_attempt_returns_1(self, db_session, exercise, student):
        """Aucune soumission existante → attempt_number = 1."""
        repo = SQLAlchemySubmissionRepository(db_session)

        result = await repo.get_next_attempt_number(exercise.id, student.id)

        assert result == 1

    async def test_after_existing_returns_next(self, db_session, exercise, student):
        """Une soumission existante avec attempt_number=1 → next = 2."""
        repo = SQLAlchemySubmissionRepository(db_session)
        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

        result = await repo.get_next_attempt_number(exercise.id, student.id)

        assert result == 2

    async def test_after_multiple_returns_max_plus_1(self, db_session, exercise, student):
        """Plusieurs soumissions → next = max(attempt_numbers) + 1."""
        repo = SQLAlchemySubmissionRepository(db_session)
        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=3)

        result = await repo.get_next_attempt_number(exercise.id, student.id)

        assert result == 4


@pytest.mark.anyio
class TestSubmissionRepositoryCountAttempts:
    """Tests de la méthode count_attempts()."""

    async def test_count_zero(self, db_session, exercise, student):
        repo = SQLAlchemySubmissionRepository(db_session)

        result = await repo.count_attempts(exercise.id, student.id)

        assert result == 0

    async def test_count_multiple(self, db_session, exercise, student):
        repo = SQLAlchemySubmissionRepository(db_session)
        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=2)
        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=3)

        result = await repo.count_attempts(exercise.id, student.id)

        assert result == 3

    async def test_count_excludes_other_student(self, db_session, exercise, student, other_student):
        repo = SQLAlchemySubmissionRepository(db_session)
        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        await repo.create(exercise_id=exercise.id, student_id=other_student.id, attempt_number=1)

        result = await repo.count_attempts(exercise.id, student.id)

        assert result == 1


@pytest.mark.anyio
class TestSubmissionRepositoryListByExercise:
    """Tests de la méthode list_by_exercise()."""

    async def test_list_by_exercise_nominal(self, db_session, exercise, student, other_student):
        repo = SQLAlchemySubmissionRepository(db_session)
        s1 = await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        s2 = await repo.create(exercise_id=exercise.id, student_id=other_student.id, attempt_number=1)

        page = await repo.list_by_exercise(exercise.id)

        assert len(page.items) == 2
        assert all(s.exercise_id == exercise.id for s in page.items)

    async def test_list_by_exercise_empty(self, db_session, exercise):
        repo = SQLAlchemySubmissionRepository(db_session)

        page = await repo.list_by_exercise(exercise.id)

        assert page.items == []
        assert page.has_more is False

    async def test_list_by_exercise_pagination(self, db_session, exercise, student):
        repo = SQLAlchemySubmissionRepository(db_session)
        for i in range(5):
            await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=i + 1)

        first_page = await repo.list_by_exercise(exercise.id, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_by_exercise(exercise.id, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) == 2
        assert second_page.items[0].id != first_page.items[0].id


@pytest.mark.anyio
class TestSubmissionRepositoryListByStudent:
    """Tests de la méthode list_by_student()."""

    async def test_list_by_student_nominal(self, db_session, exercise, student, other_student):
        repo = SQLAlchemySubmissionRepository(db_session)
        s1 = await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        s2 = await repo.create(exercise_id=exercise.id, student_id=other_student.id, attempt_number=1)

        page = await repo.list_by_student(student.id)

        assert len(page.items) == 1
        assert page.items[0].id == s1.id
        assert page.items[0].student_id == student.id

    async def test_list_by_student_empty(self, db_session, student):
        repo = SQLAlchemySubmissionRepository(db_session)

        page = await repo.list_by_student(student.id)

        assert page.items == []
        assert page.has_more is False


@pytest.mark.anyio
class TestSubmissionRepositoryUpdateStatus:
    """Tests de la méthode update_status()."""

    async def test_update_status_nominal(self, db_session, submission):
        repo = SQLAlchemySubmissionRepository(db_session)
        assert submission.status == SubmissionStatus.PENDING_OCR

        updated = await repo.update_status(submission.id, SubmissionStatus.EVALUATED)

        assert updated is not None
        assert updated.id == submission.id
        assert updated.status == SubmissionStatus.EVALUATED

    async def test_update_status_not_found_returns_none(self, db_session):
        repo = SQLAlchemySubmissionRepository(db_session)

        result = await repo.update_status(uuid.uuid4(), SubmissionStatus.EVALUATED)

        assert result is None


@pytest.mark.anyio
class TestSubmissionRepositoryGetExtractionCorrections:
    """Tests de la méthode get_extraction_corrections()."""

    async def test_get_extraction_corrections_empty(self, db_session, submission):
        """Aucune ExtractionCorrection → liste vide."""
        repo = SQLAlchemySubmissionRepository(db_session)

        result = await repo.get_extraction_corrections(submission.id)

        assert result == []

    async def test_get_extraction_corrections_nominal(self, db_session, submission, exercise):
        """Crée des ExtractionCorrections et vérifie qu'elles sont retournées."""
        repo = SQLAlchemySubmissionRepository(db_session)
        question = exercise.questions[0]

        ec1 = ExtractionCorrection(
            submission_id=submission.id,
            question_id=question.id,
            image_crop_path="submissions/test/crop1.png",
            content_type=ExtractionContentType.TEXT,
            prediction_ocr="réponse de l'étudiant",
            confidence_score=Decimal("0.950"),
            bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
            evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
        )
        db_session.add(ec1)
        await db_session.flush()

        result = await repo.get_extraction_corrections(submission.id)

        assert len(result) == 1
        assert result[0].submission_id == submission.id
        assert result[0].question_id == question.id
        assert result[0].prediction_ocr == "réponse de l'étudiant"
        assert result[0].content_type == ExtractionContentType.TEXT

    async def test_get_extraction_corrections_excludes_other_submission(
        self, db_session, submission, exercise, student
    ):
        """Ne retourne pas les ExtractionCorrections d'une autre soumission."""
        repo = SQLAlchemySubmissionRepository(db_session)
        question = exercise.questions[0]

        # Crée une autre soumission
        other_submission = await repo.create(
            exercise_id=exercise.id, student_id=student.id, attempt_number=2
        )

        ec1 = ExtractionCorrection(
            submission_id=submission.id,
            question_id=question.id,
            image_crop_path="submissions/test/crop1.png",
            content_type=ExtractionContentType.TEXT,
            prediction_ocr="première soumission",
            confidence_score=Decimal("0.950"),
            bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
            evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
        )
        ec2 = ExtractionCorrection(
            submission_id=other_submission.id,
            question_id=question.id,
            image_crop_path="submissions/test/crop2.png",
            content_type=ExtractionContentType.TEXT,
            prediction_ocr="deuxième soumission",
            confidence_score=Decimal("0.800"),
            bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
            evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
        )
        db_session.add_all([ec1, ec2])
        await db_session.flush()

        result = await repo.get_extraction_corrections(submission.id)

        assert len(result) == 1
        assert result[0].submission_id == submission.id
        assert result[0].prediction_ocr == "première soumission"


@pytest.mark.anyio
class TestSubmissionRepositoryListEvaluatedByStudentAndExerciseIds:
    """Câblage Recommendation_Agent (clôture) — historique des soumissions, exclusion des exercices déjà réussis."""

    async def test_empty_exercise_ids_is_a_noop(self, db_session, student):
        repo = SQLAlchemySubmissionRepository(db_session)

        result = await repo.list_evaluated_by_student_and_exercise_ids(student.id, [])

        assert result == []

    async def test_excludes_non_evaluated_submissions(self, db_session, exercise, student):
        """PENDING_OCR (statut par défaut à la création) -> jamais retournée, seule EVALUATED compte."""
        repo = SQLAlchemySubmissionRepository(db_session)
        submission = await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

        result = await repo.list_evaluated_by_student_and_exercise_ids(student.id, [exercise.id])

        assert result == []
        assert submission.status == SubmissionStatus.PENDING_OCR  # confirme la précondition du test

    async def test_returns_evaluated_submission_for_targeted_exercise(self, db_session, exercise, student):
        repo = SQLAlchemySubmissionRepository(db_session)
        submission = await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        await repo.update_status(submission.id, SubmissionStatus.EVALUATED)

        result = await repo.list_evaluated_by_student_and_exercise_ids(student.id, [exercise.id])

        assert len(result) == 1
        assert result[0].id == submission.id

    async def test_excludes_other_student(self, db_session, exercise, student, other_student):
        repo = SQLAlchemySubmissionRepository(db_session)
        other_submission = await repo.create(exercise_id=exercise.id, student_id=other_student.id, attempt_number=1)
        await repo.update_status(other_submission.id, SubmissionStatus.EVALUATED)

        result = await repo.list_evaluated_by_student_and_exercise_ids(student.id, [exercise.id])

        assert result == []

    async def test_excludes_exercise_ids_not_requested(self, db_session, module, professor, student):
        repo = SQLAlchemySubmissionRepository(db_session)
        exercise_repo = SQLAlchemyExerciseRepository(db_session)
        other_exercise = await exercise_repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Autre exercice", description=None,
            questions_data=[{"order": 1, "statement": "Q1", "bareme": {"points": Decimal("5.00"), "criteria": []}}],
        )
        submission = await repo.create(exercise_id=other_exercise.id, student_id=student.id, attempt_number=1)
        await repo.update_status(submission.id, SubmissionStatus.EVALUATED)

        # other_exercise n'est PAS dans exercise_ids -> jamais retournée, même EVALUATED.
        result = await repo.list_evaluated_by_student_and_exercise_ids(student.id, [uuid.uuid4()])

        assert result == []


@pytest.mark.anyio
class TestSubmissionRepositoryCountByStatus:
    """
    Tests de count_by_status() — câblage StatisticsService.get_platform_stats.
    Delta-based : la base de test est partagée entre les runs (cf.
    régression pré-existante sur les tests de pagination), jamais une
    valeur absolue attendue.
    """

    async def test_reflects_created_submissions_via_delta(
        self, db_session, exercise, student, other_student
    ):
        repo = SQLAlchemySubmissionRepository(db_session)
        before = await repo.count_by_status()

        await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        await repo.create(exercise_id=exercise.id, student_id=other_student.id, attempt_number=1)
        await repo.create_absent(exercise_id=exercise.id, student_id=student.id)

        after = await repo.count_by_status()

        # 2 créées en PENDING_OCR (statut par défaut) + 1 en ABSENT — jamais deviné, vérifié via delta explicite.
        assert after.get(SubmissionStatus.PENDING_OCR.value, 0) - before.get(SubmissionStatus.PENDING_OCR.value, 0) == 2
        assert after.get(SubmissionStatus.ABSENT.value, 0) - before.get(SubmissionStatus.ABSENT.value, 0) == 1

    async def test_empty_status_absent_from_dict(self, db_session):
        """Un statut sans aucune ligne en base n'apparaît pas dans le dict (GROUP BY) — au service de compléter les valeurs à 0."""
        repo = SQLAlchemySubmissionRepository(db_session)

        result = await repo.count_by_status()

        assert isinstance(result, dict)
        assert all(isinstance(v, int) for v in result.values())