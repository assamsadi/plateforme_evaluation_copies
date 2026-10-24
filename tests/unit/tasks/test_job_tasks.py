"""
Test de job_tasks.resume_thread — remise à zéro de llm_call_count à chaque
reprise (audit "garanties transverses", Plan D), symétrique à
entry_router_node (qui, lui, ne se réexécute jamais sur une reprise).
"""
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.system_infrastructure.job import JobFlowType, JobStatus
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.tasks import job_tasks


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
        first_name="Prof", last_name="Resume", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice resume_thread", status=ExerciseStatus.DRAFT,
    )
    db_session.add(exercise)
    await db_session.flush()
    return exercise


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


@pytest.mark.anyio
async def test_resume_thread_resets_llm_call_count(db_session):
    exercise = await _seed_exercise(db_session)
    job_repo = SQLAlchemyJobRepository(db_session)
    job = await job_repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=exercise.id)
    await job_repo.increment_llm_call_count(exercise.id)
    await job_repo.increment_llm_call_count(exercise.id)
    await job_repo.update_status(job.id, JobStatus.INTERRUPTED)
    reloaded = await job_repo.get_by_id(job.id)
    assert reloaded.llm_call_count == 2

    fake_graph = AsyncMock()
    fake_graph.ainvoke = AsyncMock(return_value={})
    fake_graph.aget_state = AsyncMock(return_value=MagicMock(next=()))

    fake_checkpointer_ctx = MagicMock()
    fake_checkpointer_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_checkpointer_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tasks.job_tasks.get_db_context", lambda: _reuse_session(db_session)),
        patch("app.tasks.job_tasks.get_checkpointer", return_value=fake_checkpointer_ctx),
        patch("app.tasks.job_tasks.compile_pipeline_graph", return_value=fake_graph),
        patch("app.tasks.job_tasks.sync_job_after_graph_run", new_callable=AsyncMock),
    ):
        await job_tasks.resume_thread(str(exercise.id), "confirmed")

    reloaded_after = await job_repo.get_by_id(job.id)
    assert reloaded_after.llm_call_count == 0


@pytest.mark.anyio
async def test_resume_thread_no_active_job_does_not_crash(db_session):
    """thread_id sans Job actif (cas limite) -> le reset est un no-op silencieux, pas une erreur."""
    thread_id = str(uuid.uuid4())

    fake_graph = AsyncMock()
    fake_graph.ainvoke = AsyncMock(return_value={})
    fake_graph.aget_state = AsyncMock(return_value=MagicMock(next=()))

    fake_checkpointer_ctx = MagicMock()
    fake_checkpointer_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_checkpointer_ctx.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.tasks.job_tasks.get_db_context", lambda: _reuse_session(db_session)),
        patch("app.tasks.job_tasks.get_checkpointer", return_value=fake_checkpointer_ctx),
        patch("app.tasks.job_tasks.compile_pipeline_graph", return_value=fake_graph),
        patch("app.tasks.job_tasks.sync_job_after_graph_run", new_callable=AsyncMock),
    ):
        await job_tasks.resume_thread(thread_id, "confirmed")  # ne doit pas lever
