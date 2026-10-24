"""
Test de entry_router_node — remise à zéro de llm_call_count à chaque run
frais (audit "garanties transverses", Plan D). Le reste du comportement du
nœud (création/réutilisation de Job) est déjà couvert par les tests
d'intégration du graph.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.system_infrastructure.job import JobFlowType, JobStatus
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.graph.nodes.entry_router_node import entry_router_node
from app.graph.state import PipelineState


async def _seed_exercise(db_session) -> Exercise:
    user_repo = SQLAlchemyUserRepository(db_session)
    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add(module)
    await db_session.flush()

    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Router", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice entry router", status=ExerciseStatus.DRAFT,
    )
    db_session.add(exercise)
    await db_session.flush()
    return exercise


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


def _make_state(exercise: Exercise) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(exercise.id),
        flow_type="exercise_setup",
        trace_id=str(exercise.id),
        exercise_id=str(exercise.id),
        module_id=str(exercise.module_id),
        raw_file_path="exercises/doc.pdf",
        created_at=now,
        updated_at=now,
    )


@pytest.mark.anyio
async def test_entry_router_node_resets_existing_job_llm_call_count(db_session):
    exercise = await _seed_exercise(db_session)
    job_repo = SQLAlchemyJobRepository(db_session)
    job = await job_repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=exercise.id)
    await job_repo.increment_llm_call_count(exercise.id)
    await job_repo.increment_llm_call_count(exercise.id)
    reloaded = await job_repo.get_by_id(job.id)
    assert reloaded.llm_call_count == 2

    with patch(
        "app.graph.nodes.entry_router_node.get_db_context",
        lambda: _reuse_session(db_session),
    ):
        await entry_router_node(_make_state(exercise))

    reloaded_after = await job_repo.get_by_id(job.id)
    assert reloaded_after.llm_call_count == 0
    assert reloaded_after.status == JobStatus.RUNNING


@pytest.mark.anyio
async def test_entry_router_node_new_job_starts_at_zero(db_session):
    exercise = await _seed_exercise(db_session)

    with patch(
        "app.graph.nodes.entry_router_node.get_db_context",
        lambda: _reuse_session(db_session),
    ):
        await entry_router_node(_make_state(exercise))

    job_repo = SQLAlchemyJobRepository(db_session)
    job = await job_repo.get_active_job_for_thread(exercise.id)
    assert job is not None
    assert job.llm_call_count == 0
