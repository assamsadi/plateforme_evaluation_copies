"""
Tests d'intégration de EvaluationService.list_evaluations()/get_evaluation()
— DB réelle. Couvre le gap fermé (espace étudiant) : Evaluation n'a aucune
relation ORM "criteria" déclarée, une Evaluation relue depuis la DB (jamais
mockée) faisait échouer la validation Pydantic EvaluationRead.criteria
(champ requis) à chaque appel réel — jamais détecté par les tests unitaires
existants (tous mockent evaluation_repo).
"""
import uuid
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.identity.user import UserRole
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.services.evaluation_service import EvaluationService


async def _seed_evaluated_submission(db_session):
    """Exercice + question + barème réel (2 critères) + soumission + évaluation notée."""
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
        title="Exercice noté",
        description=None,
        questions_data=[
            {
                "order": 1,
                "statement": "Question notée.",
                "bareme": {
                    "points": Decimal("10.00"),
                    "criteria": [
                        {"label": "Exactitude", "points": Decimal("5")},
                        {"label": "Justification", "points": Decimal("5")},
                    ],
                },
            },
        ],
    )
    exercise = await exercise_repo.publish(
        exercise_id=exercise.id, status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
        course_id=None, deadline=None, difficulty_level="facile",
    )
    question = exercise.questions[0]
    real_criterion_ids = [c["id"] for c in question.bareme.criteria]

    submission = await submission_repo.create(exercise.id, student.id, attempt_number=1)

    await evaluation_repo.create_with_criteria(
        submission_id=submission.id,
        question_id=question.id,
        score=Decimal("7.50"),
        classic_criteria_observed=[],
        criteria_data=[
            {"bareme_id": question.bareme.id, "criterion_id": real_criterion_ids[0], "points_awarded": Decimal("4.00")},
            {"bareme_id": question.bareme.id, "criterion_id": real_criterion_ids[1], "points_awarded": Decimal("3.50")},
        ],
    )

    service = EvaluationService(evaluation_repo, submission_repo, exercise_repo, user_repo)
    return service, submission, question


@pytest.mark.anyio
async def test_list_evaluations_resolves_real_criteria(db_session):
    service, submission, question = await _seed_evaluated_submission(db_session)

    result = await service.list_evaluations(submission.id)

    assert len(result) == 1
    evaluation = result[0]
    assert evaluation.score == Decimal("7.50")
    assert len(evaluation.criteria) == 2
    labels = {c.criterion_label for c in evaluation.criteria}
    assert labels == {"Exactitude", "Justification"}
    points = sorted(c.points_awarded for c in evaluation.criteria)
    assert points == [Decimal("3.50"), Decimal("4.00")]


@pytest.mark.anyio
async def test_get_evaluation_resolves_real_criteria(db_session):
    service, submission, question = await _seed_evaluated_submission(db_session)
    evaluations = await service._evaluation_repo.list_by_submission(submission.id)
    evaluation_id = evaluations[0].id
    exercise = await service._exercise_repo.get_by_id(submission.exercise_id)

    requesting_professor = MagicMock(role=UserRole.PROFESSOR, id=exercise.created_by_professor_id)

    result = await service.get_evaluation(evaluation_id, requesting_professor)

    assert len(result.criteria) == 2
    assert {c.criterion_label for c in result.criteria} == {"Exactitude", "Justification"}
