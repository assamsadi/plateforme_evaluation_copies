"""
Tests de SQLAlchemyExtractionCorrectionRepository.apply_contestation_verdict,
.apply_fusion_verdict et .file_contestation — persistance des verdicts et de
l'intake de Contestation_Verification_Agent (§2/§5/§6/§7 du doc de référence agent).
"""
import uuid
from decimal import Decimal

import pytest

from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
    ExtractionContentType,
    ExtractionCorrection,
    ExtractionEvidenceLevel,
)
from app.domain.models.identity.user import AcademicStatus, Professor, Student, UserRole
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.extraction_correction_repository import (
    SQLAlchemyExtractionCorrectionRepository,
)
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
            {"order": 1, "statement": "Question 1", "bareme": {"points": Decimal("5.00"), "criteria": []}},
        ],
    )


@pytest.fixture
async def submission(db_session, exercise, student):
    repo = SQLAlchemySubmissionRepository(db_session)
    return await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)


def _make_correction(submission_id: uuid.UUID, question_id, page_number=1, prediction_ocr="texte") -> ExtractionCorrection:
    return ExtractionCorrection(
        submission_id=submission_id,
        question_id=question_id,
        image_crop_path=f"submissions/test/{uuid.uuid4().hex[:8]}.png",
        page_number=page_number,
        content_type=ExtractionContentType.TEXT,
        prediction_ocr=prediction_ocr,
        confidence_score=Decimal("0.400"),
        bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
        evidence_level=ExtractionEvidenceLevel.AMBIGU,
        contestation_status=ContestationStatus.PENDING_VERIFICATION,
    )


@pytest.mark.anyio
class TestApplyContestationVerdict:
    async def test_plausible_elevates_confidence_score(self, db_session, submission, exercise):
        correction = _make_correction(submission.id, exercise.questions[0].id)
        db_session.add(correction)
        await db_session.flush()
        repo = SQLAlchemyExtractionCorrectionRepository(db_session)

        result = await repo.apply_contestation_verdict(
            correction_id=correction.id,
            contestation_status=ContestationStatus.PLAUSIBLE,
            verified_content="réponse confirmée",
            confidence_score=Decimal("0.950"),
        )

        assert result.contestation_status == ContestationStatus.PLAUSIBLE
        assert result.verified_content == "réponse confirmée"
        assert result.confidence_score == Decimal("0.950")

    async def test_ambigu_leaves_confidence_score_untouched(self, db_session, submission, exercise):
        correction = _make_correction(submission.id, exercise.questions[0].id)
        db_session.add(correction)
        await db_session.flush()
        original_confidence = correction.confidence_score
        repo = SQLAlchemyExtractionCorrectionRepository(db_session)

        result = await repo.apply_contestation_verdict(
            correction_id=correction.id,
            contestation_status=ContestationStatus.AMBIGU,
            verified_content=None,
            confidence_score=None,
        )

        assert result.contestation_status == ContestationStatus.AMBIGU
        assert result.verified_content is None
        assert result.confidence_score == original_confidence

    async def test_not_found_returns_none(self, db_session):
        repo = SQLAlchemyExtractionCorrectionRepository(db_session)
        result = await repo.apply_contestation_verdict(
            correction_id=uuid.uuid4(),
            contestation_status=ContestationStatus.PLAUSIBLE,
            verified_content="x",
            confidence_score=Decimal("0.9"),
        )
        assert result is None


@pytest.mark.anyio
class TestApplyFusionVerdict:
    async def test_defusion_clears_fused_ids_on_whole_group(self, db_session, submission, exercise):
        question_id = exercise.questions[0].id
        survivor = _make_correction(submission.id, question_id, page_number=1)
        consumed = _make_correction(submission.id, question_id, page_number=2)
        db_session.add_all([survivor, consumed])
        await db_session.flush()
        survivor.fused_extraction_correction_ids = [str(consumed.id)]
        await db_session.flush()

        repo = SQLAlchemyExtractionCorrectionRepository(db_session)
        result = await repo.apply_fusion_verdict(
            group_ids=[survivor.id, consumed.id],
            defusion_applied=True,
            contestation_status=ContestationStatus.PLAUSIBLE,
            confidence_score=Decimal("0.950"),
        )

        assert len(result) == 2
        for correction in result:
            assert correction.fused_extraction_correction_ids is None
            assert correction.contestation_status == ContestationStatus.PLAUSIBLE
            assert correction.confidence_score == Decimal("0.950")

    async def test_confirmed_fusion_resets_survivor_reference(self, db_session, submission, exercise):
        question_id = exercise.questions[0].id
        block_a = _make_correction(submission.id, question_id, page_number=1)
        block_b = _make_correction(submission.id, question_id, page_number=2)
        db_session.add_all([block_a, block_b])
        await db_session.flush()

        repo = SQLAlchemyExtractionCorrectionRepository(db_session)
        result = await repo.apply_fusion_verdict(
            group_ids=[block_a.id, block_b.id],
            defusion_applied=False,
            contestation_status=ContestationStatus.IMPLAUSIBLE,
            confidence_score=Decimal("0.950"),
        )

        survivor = next(c for c in result if c.id == block_a.id)  # premier par page
        other = next(c for c in result if c.id == block_b.id)
        assert survivor.fused_extraction_correction_ids == [str(block_b.id)]
        assert other.fused_extraction_correction_ids is None
        assert all(c.contestation_status == ContestationStatus.IMPLAUSIBLE for c in result)

    async def test_empty_group_returns_empty_list(self, db_session):
        repo = SQLAlchemyExtractionCorrectionRepository(db_session)
        result = await repo.apply_fusion_verdict(
            group_ids=[uuid.uuid4()],
            defusion_applied=True,
            contestation_status=ContestationStatus.PLAUSIBLE,
            confidence_score=None,
        )
        assert result == []


@pytest.mark.anyio
class TestFileContestation:
    async def test_sets_pending_verification_and_intake_fields(self, db_session, submission, exercise):
        correction = _make_correction(submission.id, exercise.questions[0].id)
        correction.contestation_status = None
        db_session.add(correction)
        await db_session.flush()
        repo = SQLAlchemyExtractionCorrectionRepository(db_session)

        result = await repo.file_contestation(
            correction_id=correction.id,
            contestation_type=ContestationType.CONTENT,
            claimed_content="ce que l'étudiant affirme avoir écrit",
            contested_element_id=None,
            claimed_question_id=None,
            claimed_section_id=None,
        )

        assert result.contestation_type == ContestationType.CONTENT
        assert result.contestation_status == ContestationStatus.PENDING_VERIFICATION
        assert result.human_correction == "ce que l'étudiant affirme avoir écrit"

    async def test_not_found_returns_none(self, db_session):
        repo = SQLAlchemyExtractionCorrectionRepository(db_session)
        result = await repo.file_contestation(
            correction_id=uuid.uuid4(),
            contestation_type=ContestationType.CONTENT,
            claimed_content="x",
            contested_element_id=None,
            claimed_question_id=None,
            claimed_section_id=None,
        )
        assert result is None


def _make_block_dict(image_crop_path: str, prediction_ocr: str = "texte", confidence: str = "0.500") -> dict:
    return {
        "image_crop_path": image_crop_path,
        "page_number": 1,
        "content_type": "TEXT",
        "prediction_ocr": prediction_ocr,
        "structured_output": None,
        "confidence_score": Decimal(confidence),
        "bounding_box": {"x": 0, "y": 0, "width": 10, "height": 10},
        "evidence_level": "ambigu",
        "question_id": None,
    }


@pytest.mark.anyio
class TestBulkCreateForSubmissionUpsert:
    """Priorité 2 (audit doc restauré, point 2) : upsert par
    (submission_id, image_crop_path), jamais un INSERT pur — un
    redéclenchement de la pipeline OCR pour la même soumission ne doit
    jamais dupliquer de lignes."""

    async def test_second_call_same_crop_path_updates_in_place_no_duplicate(self, db_session, submission):
        repo = SQLAlchemyExtractionCorrectionRepository(db_session)
        crop_path = "submissions/test/block1.png"
        blocks = [_make_block_dict(crop_path, prediction_ocr="première version")]

        first = await repo.bulk_create_for_submission(submission_id=submission.id, blocks=blocks)
        assert len(first) == 1

        blocks[0]["prediction_ocr"] = "version corrigée"
        blocks[0]["confidence_score"] = Decimal("0.900")
        await repo.bulk_create_for_submission(submission_id=submission.id, blocks=blocks)

        all_corrections = await repo.get_by_submission_id(submission.id)
        assert len(all_corrections) == 1  # pas de doublon
        assert all_corrections[0].prediction_ocr == "version corrigée"
        assert all_corrections[0].confidence_score == Decimal("0.900")

    async def test_new_crop_path_inserts_alongside_existing(self, db_session, submission):
        repo = SQLAlchemyExtractionCorrectionRepository(db_session)
        block_a = _make_block_dict("submissions/test/a.png")
        await repo.bulk_create_for_submission(submission_id=submission.id, blocks=[block_a])

        block_b = _make_block_dict("submissions/test/b.png")
        await repo.bulk_create_for_submission(submission_id=submission.id, blocks=[block_a, block_b])

        all_corrections = await repo.get_by_submission_id(submission.id)
        assert len(all_corrections) == 2
