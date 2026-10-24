"""
Tests du plafond d'appels LLM par thread dans invoke_llm_with_fallback
(audit "garanties transverses", Plan D) — vérifié avant toute tentative,
incrémenté à CHAQUE tentative (succès ou échec, fallback inclus).
"""
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.context import AgentExecutionContext
from app.core.exceptions import LLMBudgetExceededError
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import ModelProvider, ModelSpec, TaskType


def _make_context(submission_id: uuid.UUID) -> AgentExecutionContext:
    return AgentExecutionContext(
        trace_id=str(submission_id), flow_type="student_evaluation", submission_id=submission_id,
    )


@asynccontextmanager
async def _fake_db_context():
    yield MagicMock()


@pytest.mark.anyio
async def test_no_context_skips_budget_check_entirely():
    """Sans context (appel hors graph, ex. tests), aucun accès DB, aucun garde-fou."""
    fake_spec = ModelSpec(provider=ModelProvider.GROQ, model_name="llama-3.3-70b-versatile")
    fake_llm = AsyncMock()
    fake_llm.ainvoke.return_value = MagicMock(content="ok", response_metadata={})
    fake_http_client = AsyncMock()

    with patch("app.llm.client.registry.get_llm_chain", return_value=[(fake_llm, fake_spec, fake_http_client)]):
        with patch("app.llm.client.get_db_context") as mock_db_ctx:
            result, spec, fallback, tokens = await invoke_llm_with_fallback(
                task_type=TaskType.DOCUMENT_STRUCTURING, messages=[], context=None,
            )

    mock_db_ctx.assert_not_called()
    assert spec == fake_spec


@pytest.mark.anyio
async def test_raises_when_budget_already_exceeded():
    submission_id = uuid.uuid4()
    context = _make_context(submission_id)

    fake_job = MagicMock(llm_call_count=30)
    job_repo = AsyncMock()
    job_repo.get_active_job_for_thread.return_value = fake_job

    with patch("app.llm.client.get_db_context", _fake_db_context):
        with patch("app.llm.client.SQLAlchemyJobRepository", return_value=job_repo):
            with pytest.raises(LLMBudgetExceededError) as exc_info:
                await invoke_llm_with_fallback(
                    task_type=TaskType.DOCUMENT_STRUCTURING, messages=[], context=context,
                )

    assert exc_info.value.max_calls == 30
    job_repo.increment_llm_call_count.assert_not_awaited()  # jamais tenté, refusé avant


@pytest.mark.anyio
async def test_no_active_job_skips_budget_check():
    """context fourni mais aucun Job actif (ex. appel de test isolé) -> pas de garde-fou, pas de crash."""
    context = _make_context(uuid.uuid4())
    job_repo = AsyncMock()
    job_repo.get_active_job_for_thread.return_value = None

    fake_spec = ModelSpec(provider=ModelProvider.GROQ, model_name="llama-3.3-70b-versatile")
    fake_llm = AsyncMock()
    fake_llm.ainvoke.return_value = MagicMock(content="ok", response_metadata={})
    fake_http_client = AsyncMock()

    with patch("app.llm.client.registry.get_llm_chain", return_value=[(fake_llm, fake_spec, fake_http_client)]):
        with patch("app.llm.client.get_db_context", _fake_db_context):
            with patch("app.llm.client.SQLAlchemyJobRepository", return_value=job_repo):
                result, spec, fallback, tokens = await invoke_llm_with_fallback(
                    task_type=TaskType.DOCUMENT_STRUCTURING, messages=[], context=context,
                )

    assert spec == fake_spec


@pytest.mark.anyio
async def test_increments_call_count_per_attempt_including_failed_fallback():
    """Chaque tentative compte, même celle qui échoue avant le fallback réussi."""
    submission_id = uuid.uuid4()
    context = _make_context(submission_id)

    fake_job = MagicMock(llm_call_count=0)
    job_repo = AsyncMock()
    job_repo.get_active_job_for_thread.return_value = fake_job

    fake_spec_1 = ModelSpec(provider=ModelProvider.GROQ, model_name="llama-3.3-70b-versatile")
    fake_spec_2 = ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini")
    failing_llm = AsyncMock()
    failing_llm.ainvoke.side_effect = RuntimeError("panne fournisseur")
    ok_llm = AsyncMock()
    ok_llm.ainvoke.return_value = MagicMock(content="ok", response_metadata={})
    failing_http_client = AsyncMock()
    ok_http_client = AsyncMock()

    with patch(
        "app.llm.client.registry.get_llm_chain",
        return_value=[(failing_llm, fake_spec_1, failing_http_client), (ok_llm, fake_spec_2, ok_http_client)],
    ):
        with patch("app.llm.client.get_db_context", _fake_db_context):
            with patch("app.llm.client.SQLAlchemyJobRepository", return_value=job_repo):
                result, spec, fallback, tokens = await invoke_llm_with_fallback(
                    task_type=TaskType.DOCUMENT_STRUCTURING, messages=[], context=context,
                )

    assert fallback is True
    assert spec == fake_spec_2
    assert job_repo.increment_llm_call_count.await_count == 2  # 1 échec + 1 succès
