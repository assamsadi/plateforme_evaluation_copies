"""
Tests de SQLAlchemyJobRepository.increment_llm_call_count /
.reset_llm_call_count (audit "garanties transverses", Plan D) — plafond
d'appels LLM par thread, jamais cumulatif à travers les reprises.
"""
import uuid

import pytest

from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.system_infrastructure.job import JobFlowType, JobStatus
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository


async def _seed_exercise(db_session) -> Exercise:
    """Job.exercise_id est une vraie FK vers exercises.id — pas un UUID arbitraire."""
    user_repo = SQLAlchemyUserRepository(db_session)
    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add(module)
    await db_session.flush()

    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Job", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice job repo", status=ExerciseStatus.DRAFT,
    )
    db_session.add(exercise)
    await db_session.flush()
    return exercise


@pytest.mark.anyio
class TestJobRepositoryLLMCallCount:
    async def test_increment_llm_call_count_increases_by_one(self, db_session):
        exercise = await _seed_exercise(db_session)
        repo = SQLAlchemyJobRepository(db_session)
        job = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=exercise.id)
        assert job.llm_call_count == 0

        updated = await repo.increment_llm_call_count(exercise.id)
        assert updated.llm_call_count == 1

        updated_again = await repo.increment_llm_call_count(exercise.id)
        assert updated_again.llm_call_count == 2

    async def test_increment_llm_call_count_no_active_job_returns_none(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        result = await repo.increment_llm_call_count(uuid.uuid4())
        assert result is None

    async def test_reset_llm_call_count_zeroes_existing_count(self, db_session):
        exercise = await _seed_exercise(db_session)
        repo = SQLAlchemyJobRepository(db_session)
        job = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=exercise.id)
        await repo.increment_llm_call_count(exercise.id)
        await repo.increment_llm_call_count(exercise.id)
        reloaded = await repo.get_by_id(job.id)
        assert reloaded.llm_call_count == 2

        await repo.reset_llm_call_count(job.id)

        reloaded_after_reset = await repo.get_by_id(job.id)
        assert reloaded_after_reset.llm_call_count == 0

    async def test_reset_llm_call_count_not_found_is_noop(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        # Ne doit lever aucune exception.
        await repo.reset_llm_call_count(uuid.uuid4())


@pytest.mark.anyio
class TestJobRepositoryCountByStatus:
    """
    Câblage JobSupervisionService.get_overview. Delta-based : la base de
    test est partagée entre les runs, jamais une valeur absolue attendue
    (cf. régression pré-existante sur les tests de pagination).
    """

    async def test_reflects_created_jobs_via_delta(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        before = await repo.count_by_status()

        ex1 = await _seed_exercise(db_session)
        ex2 = await _seed_exercise(db_session)
        ex3 = await _seed_exercise(db_session)
        job1 = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex1.id)
        job2 = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex2.id)
        job3 = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex3.id)
        await repo.update_status(job2.id, JobStatus.FAILED, error_message="boom")
        await repo.update_status(job3.id, JobStatus.INTERRUPTED, current_node="teacher_validation")

        after = await repo.count_by_status()

        assert after.get(JobStatus.PENDING.value, 0) - before.get(JobStatus.PENDING.value, 0) == 1
        assert after.get(JobStatus.FAILED.value, 0) - before.get(JobStatus.FAILED.value, 0) == 1
        assert after.get(JobStatus.INTERRUPTED.value, 0) - before.get(JobStatus.INTERRUPTED.value, 0) == 1

    async def test_returns_dict_of_ints(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        result = await repo.count_by_status()
        assert isinstance(result, dict)
        assert all(isinstance(v, int) for v in result.values())


@pytest.mark.anyio
class TestJobRepositoryListByStatus:
    async def test_filters_by_status(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        ex1 = await _seed_exercise(db_session)
        ex2 = await _seed_exercise(db_session)
        job1 = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex1.id)
        job2 = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex2.id)
        await repo.update_status(job2.id, JobStatus.INTERRUPTED, current_node="teacher_validation")

        page = await repo.list_by_status(JobStatus.INTERRUPTED, limit=200)

        assert any(j.id == job2.id for j in page.items)
        assert all(j.status == JobStatus.INTERRUPTED for j in page.items)
        assert not any(j.id == job1.id for j in page.items)

    async def test_empty_when_no_job_in_status(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        ex1 = await _seed_exercise(db_session)
        await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex1.id)  # reste PENDING

        page = await repo.list_by_status(JobStatus.CANCELLED, limit=200)

        assert page.items == [] or all(j.status == JobStatus.CANCELLED for j in page.items)

    async def test_pagination_cursor(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        jobs = []
        for _ in range(3):
            ex = await _seed_exercise(db_session)
            job = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex.id)
            await repo.update_status(job.id, JobStatus.RETRYING)
            jobs.append(job)

        first_page = await repo.list_by_status(JobStatus.RETRYING, limit=2)
        assert len(first_page.items) == 2
        assert first_page.has_more is True

        second_page = await repo.list_by_status(JobStatus.RETRYING, cursor=first_page.next_cursor, limit=2)
        assert len(second_page.items) >= 1
        assert second_page.items[0].id != first_page.items[0].id


@pytest.mark.anyio
class TestJobRepositoryListRecent:
    async def test_orders_by_most_recently_updated_first(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        ex1 = await _seed_exercise(db_session)
        ex2 = await _seed_exercise(db_session)
        job1 = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex1.id)
        job2 = await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex2.id)

        # job1 mis à jour APRÈS job2 -> doit apparaître avant dans list_recent (updated_at desc).
        await repo.update_status(job1.id, JobStatus.RUNNING)

        recent = await repo.list_recent(limit=200)
        recent_ids = [j.id for j in recent]

        assert recent_ids.index(job1.id) < recent_ids.index(job2.id)

    async def test_respects_limit(self, db_session):
        repo = SQLAlchemyJobRepository(db_session)
        for _ in range(3):
            ex = await _seed_exercise(db_session)
            await repo.create(flow_type=JobFlowType.EXERCISE_SETUP, exercise_id=ex.id)

        recent = await repo.list_recent(limit=2)

        assert len(recent) == 2
