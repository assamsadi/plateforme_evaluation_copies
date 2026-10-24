"""
Tests de SQLAlchemyModelConfigurationRepository (chantier "Configuration
des modèles IA") — get_all/get_by_task_type/upsert/delete. task_type est
la clé primaire (une ligne par TaskType) — chaque test choisit un
TaskType puis le nettoie en fin de test (delete), la table étant partagée
entre runs (PK par valeur d'enum, jamais un UUID généré à chaque test).
"""
import pytest

from app.domain.repositories.model_configuration_repository import SQLAlchemyModelConfigurationRepository
from app.model_registry.models import ModelProvider, TaskType


@pytest.fixture
async def repo(db_session):
    return SQLAlchemyModelConfigurationRepository(db_session)


@pytest.mark.anyio
class TestModelConfigurationRepositoryUpsert:
    async def test_creates_new_row(self, repo):
        result = await repo.upsert(
            task_type=TaskType.FEEDBACK_GENERATION, provider=ModelProvider.OPENAI,
            model_name="gpt-4o", timeout_seconds=60,
        )

        assert result.task_type == TaskType.FEEDBACK_GENERATION
        assert result.provider == ModelProvider.OPENAI
        assert result.model_name == "gpt-4o"
        assert result.timeout_seconds == 60

    async def test_upsert_on_existing_row_updates_in_place(self, repo):
        await repo.upsert(
            task_type=TaskType.FEEDBACK_GENERATION, provider=ModelProvider.OPENAI,
            model_name="gpt-4o", timeout_seconds=60,
        )

        updated = await repo.upsert(
            task_type=TaskType.FEEDBACK_GENERATION, provider=ModelProvider.GROQ,
            model_name="llama-3.3-70b-versatile", timeout_seconds=45,
        )

        assert updated.provider == ModelProvider.GROQ
        assert updated.model_name == "llama-3.3-70b-versatile"
        assert updated.timeout_seconds == 45

        all_rows = await repo.get_all()
        matching = [r for r in all_rows if r.task_type == TaskType.FEEDBACK_GENERATION]
        assert len(matching) == 1  # jamais une deuxième ligne pour le même task_type


@pytest.mark.anyio
class TestModelConfigurationRepositoryGetByTaskType:
    async def test_found(self, repo):
        await repo.upsert(
            task_type=TaskType.REASONING_GRAPH, provider=ModelProvider.OPENAI,
            model_name="gpt-4o", timeout_seconds=50,
        )

        found = await repo.get_by_task_type(TaskType.REASONING_GRAPH)

        assert found is not None
        assert found.model_name == "gpt-4o"

    async def test_not_found_returns_none(self, repo):
        found = await repo.get_by_task_type(TaskType.COMPETENCY_ASSESSMENT)
        assert found is None


@pytest.mark.anyio
class TestModelConfigurationRepositoryDelete:
    async def test_delete_removes_row(self, repo):
        await repo.upsert(
            task_type=TaskType.EXTRACTION_VERIFICATION, provider=ModelProvider.OPENAI,
            model_name="gpt-4o", timeout_seconds=50,
        )

        await repo.delete(TaskType.EXTRACTION_VERIFICATION)

        assert await repo.get_by_task_type(TaskType.EXTRACTION_VERIFICATION) is None

    async def test_delete_not_found_is_noop(self, repo):
        # Ne doit lever aucune exception.
        await repo.delete(TaskType.SOLUTION_VARIANT_GENERATION)


@pytest.mark.anyio
class TestModelConfigurationRepositoryGetAll:
    async def test_reflects_upserted_rows_via_delta(self, repo):
        before = await repo.get_all()
        before_task_types = {r.task_type for r in before}

        await repo.upsert(
            task_type=TaskType.PEDAGOGICAL_EVALUATION, provider=ModelProvider.OPENAI,
            model_name="gpt-4o", timeout_seconds=50,
        )

        after = await repo.get_all()
        after_task_types = {r.task_type for r in after}

        assert TaskType.PEDAGOGICAL_EVALUATION in after_task_types
        assert TaskType.PEDAGOGICAL_EVALUATION not in before_task_types
