"""
Test d'intégration — recommendation_node.py, câblage Kafka en notification
pure. Contre une vraie DB, recommendation_node() appelé directement (pas
besoin du graph compilé entier : ce nœud ne dépend que de state.student_id/
state.module_id/state.submission_id + de l'historique StudentCompetency
Observation déjà en base, jamais recalculé par ce nœud lui-même).

Décision actée vérifiée par ces tests (strictement le même pattern que
test_evaluation_node_kafka_notification.py pour evaluation-completed.v1) :
Kafka est un mécanisme de notification PURE, jamais un déclencheur —
publish_notification_best_effort (event_publisher_service.py) absorbe tout
échec de publication, jamais propagé, la persistance des recommandations
doit toujours aboutir.

Couvre :
  1. Publication réussie -> EventPublisherService.publish_recommendation_
     generated appelé avec le bon contenu (student_id/module_id/
     submission_id/recommendation_count, cohérent avec les RecommendedExercise
     réellement persistées), pipeline continue.
  2. Publication échouée (broker Kafka simulé indisponible, exception levée
     par le mock) -> AUCUNE exception ne remonte de recommendation_node(),
     RecommendedExercise quand même persistées en base.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseDifficulty, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.recommended_exercise import RecommendedExercise
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_observation import (
    StudentCompetencyObservation,
)
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.graph.nodes.recommendation_node import recommendation_node
from app.graph.state import PipelineState
from app.services.event_publisher_service import EventPublisherService

AS = C2PCTSkillCode.ALGORITHMIC_STRUCTURING


async def _seed_weak_competency_with_library_match(db_session):
    """
    Une soumission déjà notée (EVALUATED) + une StudentCompetencyObservation
    faible pour AS (performance_copie basse -> mastery_level bas ->
    RecommendationAgent produit >=1 recommandation) + un exercice de Library
    couvrant réellement cette compétence (candidat de matching).
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
        first_name="Prof", last_name="Kafka", department="Info", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Kafka", student_number=f"STU_{uuid.uuid4()}"[:20],
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
        question_ids=[], subquestion_outcomes=[], decision_reasons=[],
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


@pytest.mark.anyio
async def test_publish_recommendation_generated_success_carries_correct_payload(db_session):
    module, student, submission = await _seed_weak_competency_with_library_match(db_session)
    state = _make_state(module, student, submission)

    mock_publish = AsyncMock(return_value="event-id-456")
    with (
        patch("app.graph.nodes.recommendation_node.get_db_context", lambda: _reuse_session(db_session)),
        patch.object(EventPublisherService, "publish_recommendation_generated", mock_publish),
    ):
        await recommendation_node(state)

    mock_publish.assert_awaited_once()
    payload = mock_publish.await_args.args[0]
    assert payload.student_id == student.id
    assert payload.module_id == module.id
    assert payload.submission_id == submission.id

    persisted = (
        await db_session.execute(
            select(RecommendedExercise).where(RecommendedExercise.student_id == student.id)
        )
    ).scalars().all()
    assert len(persisted) >= 1
    assert payload.recommendation_count == len(persisted)


@pytest.mark.anyio
async def test_kafka_publish_failure_does_not_block_recommendation_persistence(db_session):
    """
    Broker Kafka simulé indisponible (le mock lève une exception, comme le
    ferait un vrai producer aiokafka en cas de timeout/broker down) —
    recommendation_node() ne doit JAMAIS propager cette exception, et les
    RecommendedExercise doivent quand même être persistées (Kafka =
    notification pure, décision actée).
    """
    module, student, submission = await _seed_weak_competency_with_library_match(db_session)
    state = _make_state(module, student, submission)

    mock_publish = AsyncMock(side_effect=RuntimeError("Kafka broker indisponible (simulé)"))
    with (
        patch("app.graph.nodes.recommendation_node.get_db_context", lambda: _reuse_session(db_session)),
        patch.object(EventPublisherService, "publish_recommendation_generated", mock_publish),
    ):
        result_state = await recommendation_node(state)  # ne doit lever AUCUNE exception

    mock_publish.assert_awaited_once()
    assert result_state.recommended_exercise_ids  # le pipeline a bien continué normalement

    persisted = (
        await db_session.execute(
            select(RecommendedExercise).where(RecommendedExercise.student_id == student.id)
        )
    ).scalars().all()
    assert len(persisted) >= 1
