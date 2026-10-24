"""
Test de SQLAlchemyTeacherCorrectionBlockRepository — raw_text bien persisté
par create() et bulk_create_for_exercise() (colonne ajoutée pour
Extraction_Verification_Agent, qui en a besoin pour décomposer/noter une
correction TEXTE — structured_content étant réservé aux blocs STRUCTURE/EQUATION).
"""
import uuid
from decimal import Decimal

import pytest

from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.assessment.teacher_correction_block import BlockEvidenceLevel
from app.domain.models.identity.user import Professor, UserRole
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
from app.domain.repositories.teacher_correction_block_repository import (
    SQLAlchemyTeacherCorrectionBlockRepository,
)


@pytest.fixture
async def program(db_session):
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Test Program {uuid.uuid4().hex[:8]}", code=f"TP{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def module(db_session, program):
    repo = SQLAlchemyModuleRepository(db_session)
    return await repo.create(program_id=program.id, name=f"Test Module {uuid.uuid4().hex[:8]}", code=f"TM{uuid.uuid4().hex[:6]}")


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


@pytest.mark.anyio
class TestCreateRawText:
    async def test_create_persists_raw_text(self, db_session, exercise):
        repo = SQLAlchemyTeacherCorrectionBlockRepository(db_session)

        block = await repo.create(
            exercise_id=exercise.id,
            content_type=ExtractionContentType.TEXT,
            evidence_level=BlockEvidenceLevel.LABEL_EXPLICITE,
            justification="Rattaché via label explicite Q1.",
            question_id=exercise.questions[0].id,
            raw_text="Aire = 12 cm2. Barème : 5 points.",
        )

        assert block.raw_text == "Aire = 12 cm2. Barème : 5 points."

    async def test_create_raw_text_defaults_to_none(self, db_session, exercise):
        repo = SQLAlchemyTeacherCorrectionBlockRepository(db_session)

        block = await repo.create(
            exercise_id=exercise.id,
            content_type=ExtractionContentType.STRUCTURE,
            evidence_level=BlockEvidenceLevel.UNRESOLVED_NO_LABEL,
            justification="Aucun label détecté.",
            structured_content={"rows": []},
        )

        assert block.raw_text is None


@pytest.mark.anyio
class TestBulkCreateRawText:
    async def test_bulk_create_persists_raw_text_per_block(self, db_session, exercise):
        repo = SQLAlchemyTeacherCorrectionBlockRepository(db_session)

        created = await repo.bulk_create_for_exercise(
            exercise_id=exercise.id,
            blocks=[
                {
                    "content_type": ExtractionContentType.TEXT,
                    "evidence_level": BlockEvidenceLevel.LABEL_EXPLICITE,
                    "justification": "Rattaché Q1.",
                    "question_id": exercise.questions[0].id,
                    "raw_text": "Correction texte du bloc 1.",
                },
                {
                    "content_type": ExtractionContentType.TEXT,
                    "evidence_level": BlockEvidenceLevel.UNRESOLVED_NO_LABEL,
                    "justification": "Aucun label.",
                    # raw_text absent volontairement — doit rester None, pas d'erreur.
                },
            ],
        )

        assert len(created) == 2
        by_justification = {b.justification: b for b in created}
        assert by_justification["Rattaché Q1."].raw_text == "Correction texte du bloc 1."
        assert by_justification["Aucun label."].raw_text is None
