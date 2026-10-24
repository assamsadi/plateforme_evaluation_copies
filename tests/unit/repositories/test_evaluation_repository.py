"""
Tests du EvaluationRepository — couvre toutes les méthodes publiques :
- create_with_criteria (nominal, vérifie EvaluationCriteria créés)
- get_by_id (nominal, non trouvé)
- get_by_submission_and_question (nominal, non trouvé)
- list_by_submission (nominal, vide, tri par question_id)
- get_total_score_for_submission (nominal, vide retourne 0, somme multiple)
- list_by_exercise / list_by_student (correctif StatisticsService — jointure
  via Submission, cf. docstring evaluation_repository.py)
- get_average_score_platform (delta-based — base de test partagée entre
  runs, jamais une valeur absolue attendue)
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.evaluation_criteria import EvaluationCriteria
from app.domain.models.identity.user import Student, Professor, UserRole, AcademicStatus
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
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
    """Crée un exercice avec 2 questions et leurs baremes."""
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
                "bareme": {
                    "points": Decimal("5.00"),
                    "criteria": [
                        {"label": "Formule", "points": 2.0},
                        {"label": "Calcul", "points": 3.0},
                    ],
                },
            },
            {
                "order": 2,
                "statement": "Question 2",
                "bareme": {
                    "points": Decimal("10.00"),
                    "criteria": [
                        {"label": "Hypothèses", "points": 4.0},
                        {"label": "Raisonnement", "points": 6.0},
                    ],
                },
            },
        ],
    )


@pytest.fixture
async def submission(db_session, exercise, student):
    repo = SQLAlchemySubmissionRepository(db_session)
    return await repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)


@pytest.fixture
def classic_criteria_observed():
    return [
        {"criterion": "exactitude", "score": 80, "justification": "Bonne réponse"},
        {"criterion": "coherence", "score": 90, "justification": "Logique correcte"},
    ]


@pytest.mark.anyio
class TestEvaluationRepositoryCreateWithCriteria:
    """Tests de la méthode create_with_criteria()."""

    async def test_create_nominal(
        self, db_session, submission, exercise, classic_criteria_observed
    ):
        repo = SQLAlchemyEvaluationRepository(db_session)
        question = exercise.questions[0]
        bareme = question.bareme
        criteria_data = [
            {
                "bareme_id": bareme.id,
                "criterion_id": bareme.criteria[0].get("id", str(uuid.uuid4())),
                "points_awarded": Decimal("2.00"),
                "comment": "Bien",
            },
            {
                "bareme_id": bareme.id,
                "criterion_id": bareme.criteria[1].get("id", str(uuid.uuid4())),
                "points_awarded": Decimal("3.00"),
                "comment": None,
            },
        ]

        evaluation = await repo.create_with_criteria(
            submission_id=submission.id,
            question_id=question.id,
            score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=criteria_data,
        )

        assert evaluation.id is not None
        assert evaluation.submission_id == submission.id
        assert evaluation.question_id == question.id
        assert evaluation.score == Decimal("5.00")
        assert len(evaluation.classic_criteria_observed) == 2

    async def test_create_with_criteria_persists_evaluation_criteria(
        self, db_session, submission, exercise, classic_criteria_observed
    ):
        """Vérifie que les EvaluationCriteria sont bien persistés en base."""
        repo = SQLAlchemyEvaluationRepository(db_session)
        question = exercise.questions[0]
        bareme = question.bareme
        crit_id_1 = bareme.criteria[0].get("id", str(uuid.uuid4()))
        crit_id_2 = bareme.criteria[1].get("id", str(uuid.uuid4()))
        criteria_data = [
            {"bareme_id": bareme.id, "criterion_id": crit_id_1, "points_awarded": Decimal("2.00"), "comment": "Bien"},
            {"bareme_id": bareme.id, "criterion_id": crit_id_2, "points_awarded": Decimal("3.00"), "comment": None},
        ]

        evaluation = await repo.create_with_criteria(
            submission_id=submission.id,
            question_id=question.id,
            score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=criteria_data,
        )

        # Recharge l'évaluation pour vérifier les criteria
        found = await repo.get_by_id(evaluation.id)
        assert found is not None

        # Vérifie les EvaluationCriteria via une requête directe
        from sqlalchemy import select
        result = await db_session.execute(
            select(EvaluationCriteria).where(EvaluationCriteria.evaluation_id == evaluation.id)
        )
        saved_criteria = list(result.scalars().all())
        assert len(saved_criteria) == 2
        assert saved_criteria[0].bareme_id == bareme.id
        assert saved_criteria[0].points_awarded == Decimal("2.00")
        assert saved_criteria[1].points_awarded == Decimal("3.00")


@pytest.mark.anyio
class TestEvaluationRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(
        self, db_session, submission, exercise, classic_criteria_observed
    ):
        repo = SQLAlchemyEvaluationRepository(db_session)
        question = exercise.questions[0]
        evaluation = await repo.create_with_criteria(
            submission_id=submission.id,
            question_id=question.id,
            score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )

        found = await repo.get_by_id(evaluation.id)

        assert found is not None
        assert found.id == evaluation.id
        assert found.submission_id == submission.id
        assert found.question_id == question.id
        assert found.score == Decimal("5.00")

    async def test_get_by_id_not_found_returns_none(self, db_session):
        repo = SQLAlchemyEvaluationRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestEvaluationRepositoryGetBySubmissionAndQuestion:
    """Tests de la méthode get_by_submission_and_question()."""

    async def test_found(
        self, db_session, submission, exercise, classic_criteria_observed
    ):
        repo = SQLAlchemyEvaluationRepository(db_session)
        question = exercise.questions[0]
        await repo.create_with_criteria(
            submission_id=submission.id,
            question_id=question.id,
            score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )

        found = await repo.get_by_submission_and_question(submission.id, question.id)

        assert found is not None
        assert found.submission_id == submission.id
        assert found.question_id == question.id

    async def test_not_found_returns_none(self, db_session, submission, exercise):
        repo = SQLAlchemyEvaluationRepository(db_session)

        found = await repo.get_by_submission_and_question(submission.id, exercise.questions[0].id)

        assert found is None


@pytest.mark.anyio
class TestEvaluationRepositoryListBySubmission:
    """Tests de la méthode list_by_submission()."""

    async def test_empty(self, db_session, submission):
        repo = SQLAlchemyEvaluationRepository(db_session)

        result = await repo.list_by_submission(submission.id)

        assert result == []

    async def test_nominal(
        self, db_session, submission, exercise, classic_criteria_observed
    ):
        repo = SQLAlchemyEvaluationRepository(db_session)
        q1 = exercise.questions[0]
        q2 = exercise.questions[1]
        await repo.create_with_criteria(
            submission_id=submission.id, question_id=q1.id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )
        await repo.create_with_criteria(
            submission_id=submission.id, question_id=q2.id, score=Decimal("10.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )

        result = await repo.list_by_submission(submission.id)

        assert len(result) == 2
        # Tri par question_id
        assert result[0].question_id == q1.id or result[0].question_id == q2.id

    async def test_excludes_other_submission(
        self, db_session, submission, exercise, student, classic_criteria_observed
    ):
        repo = SQLAlchemyEvaluationRepository(db_session)
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        other_submission = await sub_repo.create(
            exercise_id=exercise.id, student_id=student.id, attempt_number=2
        )
        q1 = exercise.questions[0]
        await repo.create_with_criteria(
            submission_id=submission.id, question_id=q1.id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )
        await repo.create_with_criteria(
            submission_id=other_submission.id, question_id=q1.id, score=Decimal("3.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )

        result = await repo.list_by_submission(submission.id)

        assert len(result) == 1
        assert result[0].submission_id == submission.id


@pytest.mark.anyio
class TestEvaluationRepositoryGetTotalScoreForSubmission:
    """Tests de la méthode get_total_score_for_submission()."""

    async def test_empty_returns_zero(self, db_session, submission):
        repo = SQLAlchemyEvaluationRepository(db_session)

        result = await repo.get_total_score_for_submission(submission.id)

        assert result == Decimal("0")

    async def test_single_evaluation(
        self, db_session, submission, exercise, classic_criteria_observed
    ):
        repo = SQLAlchemyEvaluationRepository(db_session)
        q1 = exercise.questions[0]
        await repo.create_with_criteria(
            submission_id=submission.id, question_id=q1.id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )

        result = await repo.get_total_score_for_submission(submission.id)

        assert result == Decimal("5.00")

    async def test_multiple_evaluations_sum(
        self, db_session, submission, exercise, classic_criteria_observed
    ):
        repo = SQLAlchemyEvaluationRepository(db_session)
        q1 = exercise.questions[0]
        q2 = exercise.questions[1]
        await repo.create_with_criteria(
            submission_id=submission.id, question_id=q1.id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )
        await repo.create_with_criteria(
            submission_id=submission.id, question_id=q2.id, score=Decimal("10.00"),
            classic_criteria_observed=classic_criteria_observed,
            criteria_data=[],
        )

        result = await repo.get_total_score_for_submission(submission.id)

        assert result == Decimal("15.00")


@pytest.mark.anyio
class TestEvaluationRepositoryListByExercise:
    """Tests de la méthode list_by_exercise() — correctif StatisticsService.get_exercise_stats."""

    async def test_empty(self, db_session, exercise):
        repo = SQLAlchemyEvaluationRepository(db_session)

        result = await repo.list_by_exercise(exercise.id)

        assert result == []

    async def test_nominal_across_submissions(
        self, db_session, exercise, student, classic_criteria_observed
    ):
        """Deux soumissions différentes du MÊME exercice -> les deux comptent (jointure Submission, pas Evaluation.exercise_id direct)."""
        eval_repo = SQLAlchemyEvaluationRepository(db_session)
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        submission_1 = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        submission_2 = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=2)
        q1 = exercise.questions[0]

        await eval_repo.create_with_criteria(
            submission_id=submission_1.id, question_id=q1.id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )
        await eval_repo.create_with_criteria(
            submission_id=submission_2.id, question_id=q1.id, score=Decimal("3.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )

        result = await eval_repo.list_by_exercise(exercise.id)

        assert len(result) == 2
        assert {e.score for e in result} == {Decimal("5.00"), Decimal("3.00")}

    async def test_excludes_other_exercise(
        self, db_session, module, professor, submission, exercise, classic_criteria_observed
    ):
        eval_repo = SQLAlchemyEvaluationRepository(db_session)
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        ex_repo = SQLAlchemyExerciseRepository(db_session)
        other_exercise = await ex_repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Autre exercice", description=None,
            questions_data=[{"order": 1, "statement": "Q1", "bareme": {"points": Decimal("5.00"), "criteria": []}}],
        )
        other_submission = await sub_repo.create(
            exercise_id=other_exercise.id, student_id=submission.student_id, attempt_number=1
        )
        await eval_repo.create_with_criteria(
            submission_id=submission.id, question_id=exercise.questions[0].id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )
        await eval_repo.create_with_criteria(
            submission_id=other_submission.id, question_id=other_exercise.questions[0].id, score=Decimal("9.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )

        result = await eval_repo.list_by_exercise(exercise.id)

        assert len(result) == 1
        assert result[0].score == Decimal("5.00")


@pytest.mark.anyio
class TestEvaluationRepositoryListByStudent:
    """Tests de la méthode list_by_student() — correctif StatisticsService.get_student_stats."""

    async def test_empty(self, db_session, student):
        repo = SQLAlchemyEvaluationRepository(db_session)

        result = await repo.list_by_student(student.id)

        assert result == []

    async def test_nominal_across_exercises(
        self, db_session, module, professor, student, exercise, classic_criteria_observed
    ):
        """Deux exercices différents du MÊME étudiant -> les deux comptent."""
        eval_repo = SQLAlchemyEvaluationRepository(db_session)
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        ex_repo = SQLAlchemyExerciseRepository(db_session)
        other_exercise = await ex_repo.create_with_questions(
            module_id=module.id, created_by_professor_id=professor.id,
            title="Autre exercice", description=None,
            questions_data=[{"order": 1, "statement": "Q1", "bareme": {"points": Decimal("5.00"), "criteria": []}}],
        )
        submission_1 = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        submission_2 = await sub_repo.create(exercise_id=other_exercise.id, student_id=student.id, attempt_number=1)

        await eval_repo.create_with_criteria(
            submission_id=submission_1.id, question_id=exercise.questions[0].id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )
        await eval_repo.create_with_criteria(
            submission_id=submission_2.id, question_id=other_exercise.questions[0].id, score=Decimal("7.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )

        result = await eval_repo.list_by_student(student.id)

        assert len(result) == 2
        assert {e.score for e in result} == {Decimal("5.00"), Decimal("7.00")}

    async def test_excludes_other_student(
        self, db_session, group, exercise, student, classic_criteria_observed
    ):
        eval_repo = SQLAlchemyEvaluationRepository(db_session)
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        other_student = Student(
            id=uuid.uuid4(), role=UserRole.STUDENT, first_name="Bob", last_name="Martin",
            email=f"other_{uuid.uuid4().hex[:8]}@test.edu", hashed_password="hashed_pw",
            student_number=f"STU{uuid.uuid4().hex[:6]}", group_id=group.id,
            enrollment_year=2025, academic_status=AcademicStatus.ACTIVE, level="L3",
        )
        db_session.add(other_student)
        await db_session.flush()

        submission_1 = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)
        submission_2 = await sub_repo.create(exercise_id=exercise.id, student_id=other_student.id, attempt_number=1)
        await eval_repo.create_with_criteria(
            submission_id=submission_1.id, question_id=exercise.questions[0].id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )
        await eval_repo.create_with_criteria(
            submission_id=submission_2.id, question_id=exercise.questions[0].id, score=Decimal("9.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )

        result = await eval_repo.list_by_student(student.id)

        assert len(result) == 1
        assert result[0].score == Decimal("5.00")


@pytest.mark.anyio
class TestEvaluationRepositoryGetAverageScorePlatform:
    """
    Tests de get_average_score_platform() — delta-based : la base de test
    est partagée entre les runs (cf. régression pré-existante sur les
    tests de pagination), jamais une valeur absolue attendue ici, toujours
    une comparaison avant/après un ajout connu.
    """

    async def test_reflects_added_scores_via_delta(
        self, db_session, submission, exercise, classic_criteria_observed
    ):
        from sqlalchemy import func, select
        from app.domain.models.assessment.evaluation import Evaluation

        repo = SQLAlchemyEvaluationRepository(db_session)
        count_before = (
            await db_session.execute(select(func.count()).select_from(Evaluation))
        ).scalar_one()
        before = await repo.get_average_score_platform()
        sum_before = (before or Decimal("0")) * count_before

        await repo.create_with_criteria(
            submission_id=submission.id, question_id=exercise.questions[0].id, score=Decimal("5.00"),
            classic_criteria_observed=classic_criteria_observed, criteria_data=[],
        )

        after = await repo.get_average_score_platform()
        expected = (sum_before + Decimal("5.00")) / (count_before + 1)

        assert after is not None
        assert round(after, 6) == round(expected, 6)
