from decimal import Decimal
import uuid
import pytest

from app.domain.models.assessment.bareme import Bareme
from app.domain.models.assessment.question import Question
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from tests.integration.repositories.test_submission_repository import seed_exercise_and_student


@pytest.mark.anyio
async def test_evaluation_repository_create_and_score_sum(db_session):
    exercise, student = await seed_exercise_and_student(db_session)
    sub_repo = SQLAlchemySubmissionRepository(db_session)
    submission = await sub_repo.create(exercise.id, student.id, attempt_number=1)

    # Create Question + Bareme
    q1 = Question(exercise_id=exercise.id, order=1, statement="Calculate perimeter")
    q2 = Question(exercise_id=exercise.id, order=2, statement="Calculate area")
    db_session.add_all([q1, q2])
    await db_session.flush()

    crit_id1 = str(uuid.uuid4())
    crit_id2 = str(uuid.uuid4())

    bareme1 = Bareme(
        question_id=q1.id,
        points=Decimal("10.0"),
        criteria=[{"id": crit_id1, "label": "Formula", "points": 5.0}],
    )
    bareme2 = Bareme(
        question_id=q2.id,
        points=Decimal("10.0"),
        criteria=[{"id": crit_id2, "label": "Result", "points": 5.0}],
    )
    db_session.add_all([bareme1, bareme2])
    await db_session.flush()

    eval_repo = SQLAlchemyEvaluationRepository(db_session)

    # Eval for Q1: score = 8.5
    eval1 = await eval_repo.create_with_criteria(
        submission_id=submission.id,
        question_id=q1.id,
        score=Decimal("8.50"),
        classic_criteria_observed=[{"criterion": "exactitude", "score": 85, "justification": "Good"}],
        criteria_data=[{"bareme_id": bareme1.id, "criterion_id": crit_id1, "points_awarded": Decimal("4.25")}],
    )
    assert eval1.id is not None
    assert eval1.score == Decimal("8.50")

    # Eval for Q2: score = 9.0
    eval2 = await eval_repo.create_with_criteria(
        submission_id=submission.id,
        question_id=q2.id,
        score=Decimal("9.00"),
        classic_criteria_observed=[{"criterion": "exactitude", "score": 90, "justification": "Great"}],
        criteria_data=[{"bareme_id": bareme2.id, "criterion_id": crit_id2, "points_awarded": Decimal("4.50")}],
    )

    # Test list_by_submission
    evals = await eval_repo.list_by_submission(submission.id)
    assert len(evals) == 2

    # Test get_by_submission_and_question
    single_eval = await eval_repo.get_by_submission_and_question(submission.id, q1.id)
    assert single_eval is not None
    assert single_eval.id == eval1.id

    # Test get_total_score_for_submission (SUM == 8.5 + 9.0 = 17.5)
    total_score = await eval_repo.get_total_score_for_submission(submission.id)
    assert Decimal(str(total_score)) == Decimal("17.50")
