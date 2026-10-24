"""
Test du bug corrigé dans SQLAlchemyCorrectionArbitrationRepository.create_and_apply_verdict :
un verdict ACCEPTED doit écrire la décision du professeur dans verified_content,
jamais dans human_correction (§9bis — human_correction reste la réclamation
ORIGINALE de l'étudiant, jamais écrasée, cf. docstring de ExtractionCorrection).
"""
import uuid
from decimal import Decimal

import pytest

from app.domain.models.assessment.correction_arbitration import ArbitrationStatus, ArbitrationVerdict
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ExtractionContentType,
    ExtractionCorrection,
    ExtractionEvidenceLevel,
)
from app.domain.models.shared.constants import CONTESTATION_RESOLVED_CONFIDENCE_SCORE
from app.domain.models.assessment.submission import Submission
from app.domain.models.identity.user import AcademicStatus, Professor, Student, UserRole
from app.domain.repositories.correction_arbitration_repository import (
    SQLAlchemyCorrectionArbitrationRepository,
)
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
async def exercise(db_session, module, professor):
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


@pytest.fixture
async def extraction_correction(db_session, submission, exercise):
    """
    human_correction porte déjà la réclamation ORIGINALE de l'étudiant, posée
    avant l'arbitrage du professeur — c'est cette valeur qui doit rester
    intacte après un verdict ACCEPTED.
    """
    correction = ExtractionCorrection(
        submission_id=submission.id,
        question_id=exercise.questions[0].id,
        image_crop_path="submissions/test/crop1.png",
        content_type=ExtractionContentType.TEXT,
        prediction_ocr="réponse initiale de l'OCR",
        human_correction="réclamation originale de l'étudiant",
        confidence_score=Decimal("0.400"),
        bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
        evidence_level=ExtractionEvidenceLevel.AMBIGU,
    )
    db_session.add(correction)
    await db_session.flush()
    return correction


@pytest.mark.anyio
class TestCorrectionArbitrationRepositoryCreateAndApplyVerdict:
    async def test_accepted_verdict_writes_verified_content_not_human_correction(
        self, db_session, extraction_correction, professor,
    ):
        """
        Bug corrigé : un verdict ACCEPTED doit écrire la décision du
        professeur dans verified_content. human_correction (la réclamation
        d'origine de l'étudiant) ne doit JAMAIS être écrasé (§9bis).
        """
        repo = SQLAlchemyCorrectionArbitrationRepository(db_session)
        original_human_correction = extraction_correction.human_correction
        professor_decision = "version tranchée par le professeur"

        await repo.create_and_apply_verdict(
            extraction_correction_id=extraction_correction.id,
            teacher_professor_id=professor.id,
            verdict=ArbitrationVerdict.ACCEPTED,
            comment="Confirmé après relecture",
            claimed_correction=professor_decision,
        )

        refreshed = await db_session.get(ExtractionCorrection, extraction_correction.id)
        assert refreshed.human_correction == original_human_correction, (
            "human_correction a été écrasé — régression du bug §9bis"
        )
        assert refreshed.verified_content == professor_decision
        assert refreshed.contestation_status == ContestationStatus.RESOLVED
        assert refreshed.confidence_score == CONTESTATION_RESOLVED_CONFIDENCE_SCORE

    async def test_rejected_verdict_leaves_verified_content_none_but_elevates_confidence(
        self, db_session, extraction_correction, professor,
    ):
        """
        REJECTED ne pose jamais verified_content (rien n'est confirmé), mais
        §7 exige quand même l'élévation de confidence_score et le passage à
        RESOLVED : la décision humaine est la nouvelle source de vérité,
        qu'elle confirme OU infirme l'étudiant.
        """
        repo = SQLAlchemyCorrectionArbitrationRepository(db_session)
        original_human_correction = extraction_correction.human_correction

        await repo.create_and_apply_verdict(
            extraction_correction_id=extraction_correction.id,
            teacher_professor_id=professor.id,
            verdict=ArbitrationVerdict.REJECTED,
            comment="Non retenu",
            claimed_correction="version proposée mais rejetée",
        )

        refreshed = await db_session.get(ExtractionCorrection, extraction_correction.id)
        assert refreshed.human_correction == original_human_correction
        assert refreshed.verified_content is None
        assert refreshed.contestation_status == ContestationStatus.RESOLVED
        assert refreshed.confidence_score == CONTESTATION_RESOLVED_CONFIDENCE_SCORE


@pytest.mark.anyio
class TestCorrectionArbitrationRepositoryCreatePending:
    async def test_creates_pending_row_with_null_teacher_fields(
        self, db_session, extraction_correction,
    ):
        repo = SQLAlchemyCorrectionArbitrationRepository(db_session)

        arbitration = await repo.create_pending(extraction_correction.id)

        assert arbitration.status == ArbitrationStatus.PENDING
        assert arbitration.teacher_professor_id is None
        assert arbitration.verdict is None
        assert arbitration.extraction_correction_id == extraction_correction.id

    async def test_resolution_updates_existing_pending_row_not_a_duplicate(
        self, db_session, extraction_correction, professor,
    ):
        """
        create_pending() (agent AMBIGU) puis create_and_apply_verdict()
        (professeur) doivent porter sur la MÊME ligne — jamais une seconde
        ligne en double pour la même contestation.
        """
        repo = SQLAlchemyCorrectionArbitrationRepository(db_session)
        pending = await repo.create_pending(extraction_correction.id)

        resolved = await repo.create_and_apply_verdict(
            extraction_correction_id=extraction_correction.id,
            teacher_professor_id=professor.id,
            verdict=ArbitrationVerdict.ACCEPTED,
            comment="Confirmé",
            claimed_correction="version du professeur",
        )

        assert resolved.id == pending.id
        assert resolved.status == ArbitrationStatus.RESOLVED
        assert resolved.teacher_professor_id == professor.id
        assert resolved.verdict == ArbitrationVerdict.ACCEPTED

        # Une seule ligne pour cette contestation, pas un doublon.
        found = await repo.get_by_extraction_correction(extraction_correction.id)
        assert found.id == pending.id
