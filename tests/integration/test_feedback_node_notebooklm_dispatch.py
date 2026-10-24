"""
Test d'intégration — feedback_node.py, câblage NotebookLM (§7, "Feedback
Intelligent" — chantier Feedback_Agent). Contre une vraie DB.

Remplace test_recommendation_node_notebooklm_dispatch.py (supprimé) : le
déclenchement de generate_notebook_for_recommendations_task a été déplacé
de recommendation_node.py vers feedback_node.py (cf. docstring des deux
nœuds) — feedback_node peut désormais transmettre feedback_text comme
source principale du notebook, ce que recommendation_node ne pouvait pas
faire (exécuté AVANT Feedback_Agent).

Couvre le contrat non négociable du chantier :
  1. La tâche Celery est bien déclenchée en `.delay()` (détaché — jamais un
     `.apply()`/exécution inline, jamais attendu) avec le bon payload
     JSON-safe, dérivé des données RÉELLEMENT disponibles à cet endroit du
     pipeline (report.lines de CompetencyAssessmentService + les
     RecommendedExerciseRead déjà persistées PAR recommendation_node en
     amont) + feedback_text produit par Feedback_Agent (seul appel LLM
     mocké ici).
  2. Un broker Celery injoignable au moment du `.delay()` (mocké, comme un
     vrai Redis down le ferait) ne fait JAMAIS échouer feedback_node()
     — best-effort, même niveau de preuve que le câblage Kafka.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseDifficulty, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.recommended_exercise import (
    RecommendationCategory,
    RecommendationStatus,
    RecommendedExercise,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_observation import (
    StudentCompetencyObservation,
)
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.graph.nodes.feedback_node import feedback_node
from app.graph.state import PipelineState

AS = C2PCTSkillCode.ALGORITHMIC_STRUCTURING


async def _seed_weak_competency_with_recommendation(db_session):
    """
    Même scénario que l'ancien test (compétence faible + exercice de
    bibliothèque assorti), MAIS seed en plus la RecommendedExercise déjà
    persistée avec submission_id posé — feedback_node ne recalcule jamais
    les recommandations (déjà faites par recommendation_node en amont dans
    le vrai run de graph, cf. docstring feedback_node.py), il les relit.
    """
    user_repo = SQLAlchemyUserRepository(db_session)

    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add_all([group, module])
    await db_session.flush()

    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Notebook", department="Info", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Notebook", student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id, enrollment_year=2024, level="L3",
    )

    graded_exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice note", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(graded_exercise)
    await db_session.flush()
    submission = Submission(
        exercise_id=graded_exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.EVALUATED, document_path="x", document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    db_session.add(StudentCompetencyObservation(
        student_id=student.id, module_id=module.id, competency_code=AS,
        submission_id=submission.id, performance_copie=Decimal("0.20000"),
        subquestions_covered_count=1, subquestions_succeeded_count=0,
        question_ids=[], subquestion_outcomes=[{"subquestion_id": "3.1", "addressed": True, "is_correct": False}],
        decision_reasons=[],
    ))

    library_exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exo bibliotheque", status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
        difficulty_level=ExerciseDifficulty.FACILE,
    )
    db_session.add(library_exercise)
    await db_session.flush()
    db_session.add(Question(
        exercise_id=library_exercise.id, order=1, statement="Q1", covered_subquestions=["3.1"],
    ))
    await db_session.flush()

    db_session.add(RecommendedExercise(
        student_id=student.id, module_id=module.id, competency_code=AS,
        category=RecommendationCategory.REMEDIATION, status=RecommendationStatus.ACTIVE,
        submission_id=submission.id, exercise_id=library_exercise.id,
        reason="Faiblesse persistante en algorithmic_structuring.", relevance_score=Decimal("0.80"),
    ))
    await db_session.flush()

    return module, student, submission


def _make_state(module, student, submission) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(submission.id), flow_type="student_evaluation", trace_id=str(submission.id),
        exercise_id=str(submission.exercise_id), submission_id=str(submission.id),
        module_id=str(module.id), student_id=str(student.id),
        raw_file_path=submission.document_path, mime_type=submission.document_mime_type,
        created_at=now, updated_at=now,
    )


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


def _mock_feedback_llm_response(text: str):
    fake_response = MagicMock()
    fake_response.content = text
    fake_spec = MagicMock()
    fake_spec.provider = "groq"
    fake_spec.model_name = "llama-3.3-70b-versatile"
    return (fake_response, fake_spec, False, {"total_tokens": 80})


@pytest.mark.anyio
async def test_notebooklm_task_dispatched_detached_with_real_data_and_feedback_text(db_session):
    module, student, submission = await _seed_weak_competency_with_recommendation(db_session)
    state = _make_state(module, student, submission)
    socratic_text = "Relis ta réponse à la question 3.1 : que vérifies-tu avant la boucle ?"

    with (
        patch("app.graph.nodes.feedback_node.get_db_context", lambda: _reuse_session(db_session)),
        patch(
            "app.agents.Feedback_Agent.invoke_llm_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_feedback_llm_response(socratic_text),
        ),
        patch(
            "app.graph.nodes.feedback_node.generate_notebook_for_recommendations_task.delay",
        ) as mock_delay,
    ):
        await feedback_node(state)

    # `.delay()` — jamais `.apply()`/exécution synchrone : la seule preuve
    # possible que le nœud ne s'est PAS bloqué en attendant la génération
    # NotebookLM réelle (aucun appel réseau n'a pu se produire ici).
    mock_delay.assert_called_once()
    kwargs = mock_delay.call_args.kwargs
    assert kwargs["student_id"] == str(student.id)
    assert kwargs["module_id"] == str(module.id)
    assert kwargs["submission_id"] == str(submission.id)

    # feedback_text réel (chantier Feedback_Agent) transmis tel quel — plus
    # jamais None à cet endroit une fois Feedback_Agent construit.
    assert kwargs["feedback_text"] == socratic_text

    assert kwargs["competency_lines_data"], "le profil de compétences doit être transmis"
    line = kwargs["competency_lines_data"][0]
    assert line["competency"] == "algorithmic_structuring"

    assert kwargs["recommendations_data"], "au moins une recommandation doit être transmise"
    rec = kwargs["recommendations_data"][0]
    assert rec["exercise_title"] == "Exo bibliotheque"
    assert rec["difficulty_level"] == "facile"


@pytest.mark.anyio
async def test_celery_broker_failure_never_blocks_feedback_node(db_session):
    """
    Broker Celery injoignable au moment du `.delay()` (mocké, comme un vrai
    Redis down le ferait) — feedback_node() ne doit JAMAIS propager cette
    exception, et le StudentFeedbackReport doit quand même être persisté
    (best-effort réservé à l'intégration NotebookLM, jamais à la génération
    du feedback lui-même — cf. docstring module).
    """
    from sqlalchemy import select

    from app.domain.models.assessment.student_feedback_report import StudentFeedbackReport

    module, student, submission = await _seed_weak_competency_with_recommendation(db_session)
    state = _make_state(module, student, submission)

    with (
        patch("app.graph.nodes.feedback_node.get_db_context", lambda: _reuse_session(db_session)),
        patch(
            "app.agents.Feedback_Agent.invoke_llm_with_fallback",
            new_callable=AsyncMock,
            return_value=_mock_feedback_llm_response("Une question malgré tout ?"),
        ),
        patch(
            "app.graph.nodes.feedback_node.generate_notebook_for_recommendations_task.delay",
            side_effect=RuntimeError("Broker Celery indisponible (simulé)"),
        ) as mock_delay,
    ):
        result_state = await feedback_node(state)  # ne doit lever AUCUNE exception

    mock_delay.assert_called_once()
    assert result_state.updated_at is not None  # le nœud a bien terminé normalement

    persisted = (
        await db_session.execute(
            select(StudentFeedbackReport).where(StudentFeedbackReport.submission_id == submission.id)
        )
    ).scalars().all()
    assert len(persisted) == 1
