"""
Test d'intégration de GradeAppealRepository.create() — DB réelle. Couvre le
gap fermé : une contestation portant sur toute la copie (evaluation_id=None)
renvoyait toujours original_score=0, jamais le total réel de la soumission,
alors que le docstring du module l'annonçait déjà comme un TODO jamais
implémenté. Le calcul reste dans le repository (jamais transmis par le
service) pour préserver l'invariant "original_score non falsifiable depuis
l'extérieur" documenté en tête de module.
"""
import uuid
from decimal import Decimal

import pytest

from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.grade_appeal_repository import SQLAlchemyGradeAppealRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository


async def _seed_submission_with_two_evaluations(db_session):
    user_repo = SQLAlchemyUserRepository(db_session)
    exercise_repo = SQLAlchemyExerciseRepository(db_session)
    submission_repo = SQLAlchemySubmissionRepository(db_session)
    evaluation_repo = SQLAlchemyEvaluationRepository(db_session)

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

    exercise = await exercise_repo.create_with_questions(
        module_id=module.id,
        created_by_professor_id=prof.id,
        title="Exercice contesté",
        description=None,
        questions_data=[
            {"order": 1, "statement": "Q1.", "bareme": {"points": Decimal("10"), "criteria": []}},
            {"order": 2, "statement": "Q2.", "bareme": {"points": Decimal("10"), "criteria": []}},
        ],
    )
    exercise = await exercise_repo.publish(
        exercise_id=exercise.id, status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
        course_id=None, deadline=None, difficulty_level="facile",
    )

    submission = await submission_repo.create(exercise.id, student.id, attempt_number=1)

    evaluation1 = await evaluation_repo.create_with_criteria(
        submission_id=submission.id, question_id=exercise.questions[0].id,
        score=Decimal("4.00"), classic_criteria_observed=[], criteria_data=[],
    )
    await evaluation_repo.create_with_criteria(
        submission_id=submission.id, question_id=exercise.questions[1].id,
        score=Decimal("3.50"), classic_criteria_observed=[], criteria_data=[],
    )

    return submission, student, evaluation1


@pytest.mark.anyio
async def test_whole_copy_appeal_uses_real_total_score(db_session):
    submission, student, _ = await _seed_submission_with_two_evaluations(db_session)
    appeal_repo = SQLAlchemyGradeAppealRepository(db_session)

    appeal = await appeal_repo.create(
        submission_id=submission.id, student_id=student.id,
        reason="Ma copie entière mérite mieux.", evaluation_id=None,
    )

    assert appeal.original_score == Decimal("7.50")


@pytest.mark.anyio
async def test_single_question_appeal_uses_that_evaluation_score(db_session):
    submission, student, evaluation1 = await _seed_submission_with_two_evaluations(db_session)
    appeal_repo = SQLAlchemyGradeAppealRepository(db_session)

    appeal = await appeal_repo.create(
        submission_id=submission.id, student_id=student.id,
        reason="Cette question a été mal notée.", evaluation_id=evaluation1.id,
    )

    assert appeal.original_score == Decimal("4.00")
