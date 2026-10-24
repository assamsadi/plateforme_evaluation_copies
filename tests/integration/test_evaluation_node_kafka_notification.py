"""
Test d'intégration — evaluation_node.py, câblage Kafka en notification pure
(correctif découvertes annexes). Contre une vraie DB, evaluation_node()
appelé directement (pas besoin du graph compilé entier : ce nœud ne dépend
que de state.submission_id/state.comparison_results, déjà posés ici sans
faire tourner OCR/comparative_evaluation_node).

Décision actée vérifiée par ces tests : Kafka est un mécanisme de
notification PURE, jamais un déclencheur — publish_notification_best_effort
(event_publisher_service.py) absorbe tout échec de publication, jamais
propagé, la persistance de la note doit toujours aboutir.

Couvre :
  1. Publication réussie -> EventPublisherService.publish_evaluation_completed
     appelé avec le bon contenu (submission_id/question_id/evaluation_id/
     score, lus sur l'EvaluationRead réellement persisté), pipeline continue.
  2. Publication échouée (broker Kafka simulé indisponible, exception levée
     par le mock) -> AUCUNE exception ne remonte de evaluation_node(),
     Evaluation quand même persistée en base.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.agents.Extraction_Verification_Agent import CorrectionMode
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.bareme import Bareme, BaremeValidationStatus
from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.graph.nodes.evaluation_node import evaluation_node
from app.graph.state import PipelineState
from app.services.event_publisher_service import EventPublisherService


async def _seed_submission(db_session):
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
        first_name="Prof", last_name="Kafka", department="Info", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Kafka", student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id, enrollment_year=2024, level="L3",
    )
    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice Kafka", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()
    question = Question(exercise_id=exercise.id, order=1, statement="Q1", covered_subquestions=["1.1"])
    db_session.add(question)
    await db_session.flush()
    bareme = Bareme(
        question_id=question.id, points=Decimal("4.00"),
        criteria=[{
            "id": "crit-1", "label": "exactitude", "points": 4.0,
            "correction_mode": CorrectionMode.CRITERIA_BASED.value,
            "verifiable_conditions": ["Calcule correctement"], "disqualifying": False,
            "test_cases": [], "reference_code": None, "expected_complexity": None,
        }],
        validation_status=BaremeValidationStatus.CONFIRMED,
    )
    db_session.add(bareme)
    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.PENDING_EVALUATION, document_path="x",
        document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()
    return exercise, question, bareme, submission


def _make_state(exercise, submission, question, bareme) -> PipelineState:
    """
    Bareme classique (CRITERIA_BASED, cf. _seed_submission ci-dessus, jamais
    du C2PCT natif) — pas de subquestion_points -> routage evaluation_node
    vers le mécanisme classique (calcul de note classique, ticket dédié) :
    "criteria"/"criterion_results" projetés pour être joints par
    criterion_id, score_ratio=1.0 pour retomber sur le même total (4.00)
    que ce que testait ce fixture avant ce câblage (Kafka reste le seul
    objet réel de ce test, pas le détail du calcul de note).
    """
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(submission.id), flow_type="student_evaluation", trace_id=str(submission.id),
        exercise_id=str(exercise.id), submission_id=str(submission.id),
        module_id=str(exercise.module_id), student_id=str(submission.student_id),
        raw_file_path=submission.document_path, mime_type=submission.document_mime_type,
        created_at=now, updated_at=now,
        comparison_results=[{
            "question_id": str(question.id),
            "bareme_id": str(bareme.id),
            "bareme_points": str(bareme.points),
            "covered_subquestions": [],
            "subquestion_points": None,
            "subquestion_judgments": [],
            "blocking": False,
            "decision_entries": [],
            "consigne_respected": None,
            "criteria": [
                {
                    "id": "crit-1", "label": "exactitude", "points": "4.0",
                    "correction_mode": CorrectionMode.CRITERIA_BASED.value,
                    "disqualifying": False,
                },
            ],
            "criterion_results": [
                {"criterion_id": "crit-1", "score_ratio": 1.0, "is_satisfied": True, "justification": "ok"},
            ],
        }],
    )


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


@pytest.mark.anyio
async def test_publish_evaluation_completed_success_carries_correct_payload(db_session):
    exercise, question, bareme, submission = await _seed_submission(db_session)
    state = _make_state(exercise, submission, question, bareme)

    mock_publish = AsyncMock(return_value="event-id-123")
    with (
        patch("app.graph.nodes.evaluation_node.get_db_context", lambda: _reuse_session(db_session)),
        patch.object(EventPublisherService, "publish_evaluation_completed", mock_publish),
    ):
        await evaluation_node(state)

    mock_publish.assert_awaited_once()
    payload = mock_publish.await_args.args[0]
    assert payload.submission_id == submission.id
    assert payload.question_id == question.id
    assert payload.score == Decimal("4.00")

    evaluations = (
        await db_session.execute(select(Evaluation).where(Evaluation.submission_id == submission.id))
    ).scalars().all()
    assert len(evaluations) == 1
    assert evaluations[0].score == Decimal("4.00")
    assert payload.evaluation_id == evaluations[0].id


@pytest.mark.anyio
async def test_kafka_publish_failure_does_not_block_evaluation_persistence(db_session):
    """
    Broker Kafka simulé indisponible (le mock lève une exception, comme le
    ferait un vrai producer aiokafka en cas de timeout/broker down) —
    evaluation_node() ne doit JAMAIS propager cette exception, et la note
    doit quand même être persistée (Kafka = notification pure, décision
    actée).
    """
    exercise, question, bareme, submission = await _seed_submission(db_session)
    state = _make_state(exercise, submission, question, bareme)

    mock_publish = AsyncMock(side_effect=RuntimeError("Kafka broker indisponible (simulé)"))
    with (
        patch("app.graph.nodes.evaluation_node.get_db_context", lambda: _reuse_session(db_session)),
        patch.object(EventPublisherService, "publish_evaluation_completed", mock_publish),
    ):
        result_state = await evaluation_node(state)  # ne doit lever AUCUNE exception

    mock_publish.assert_awaited_once()
    assert result_state.status == "RUNNING"

    evaluations = (
        await db_session.execute(select(Evaluation).where(Evaluation.submission_id == submission.id))
    ).scalars().all()
    assert len(evaluations) == 1
    assert evaluations[0].score == Decimal("4.00")
