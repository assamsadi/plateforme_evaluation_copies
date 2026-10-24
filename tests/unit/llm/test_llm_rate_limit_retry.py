"""
Tests du retry sur rate limit fournisseur (429/413 "rate_limit_exceeded")
dans invoke_llm_with_fallback — distinct d'infrastructure_retry (réseau/5xx,
backoff court) : un plafond TPM se libère sur une fenêtre ~1 minute, jamais
résolu par quelques secondes. Réessaie le MÊME fournisseur avant de
basculer sur le suivant de la chaîne.
"""
import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.context import AgentExecutionContext
from app.llm.client import _is_rate_limit_error, invoke_llm_with_fallback
from app.model_registry.models import ModelProvider, ModelSpec, TaskType


class _FakeProviderError(Exception):
    """Simule groq.APIStatusError/openai.APIStatusError — status_code posé à l'instance."""
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


def _rate_limit_error(status_code: int = 413) -> _FakeProviderError:
    return _FakeProviderError(
        f"Error code: {status_code} - {{'error': {{'code': 'rate_limit_exceeded', "
        f"'message': 'Request too large... tokens per minute (TPM)'}}}}",
        status_code=status_code,
    )


@asynccontextmanager
async def _fake_db_context():
    yield MagicMock()


class TestIsRateLimitError:
    def test_detects_via_status_code_attribute(self):
        assert _is_rate_limit_error(_rate_limit_error(413)) is True
        assert _is_rate_limit_error(_rate_limit_error(429)) is True

    def test_detects_via_message_when_status_code_attribute_absent(self):
        """SDK réel : status_code posé à l'instance, jamais garanti par hasattr sur la classe — repli sur le message formaté."""
        exc = Exception("Error code: 413 - {'error': {'code': 'rate_limit_exceeded', 'message': '...'}}")
        assert _is_rate_limit_error(exc) is True

    def test_generic_413_without_rate_limit_marker_is_not_a_rate_limit(self):
        """Un 413 réellement définitif (image trop grande, etc.) ne doit jamais être confondu avec un rate limit."""
        exc = _FakeProviderError("Error code: 413 - image payload too large", status_code=413)
        assert _is_rate_limit_error(exc) is False

    def test_unrelated_error_is_not_a_rate_limit(self):
        assert _is_rate_limit_error(RuntimeError("panne fournisseur quelconque")) is False


@pytest.mark.anyio
class TestRateLimitRetryInFallbackChain:
    async def test_retries_same_provider_after_rate_limit_then_succeeds(self):
        """
        2 échecs rate limit puis succès -> même fournisseur (llm) rappelé 3
        fois, jamais basculé sur le suivant. LLM_RATE_LIMIT_MAX_RETRIES fixé
        explicitement à 3 ici (indépendant du défaut de production, réduit à
        1 depuis — cf. app/core/config.py — un 413 Groq "Request too large"
        constaté en usage réel n'étant PAS un quota temporaire, retenter ne
        change jamais son issue) : ce test vérifie le MÉCANISME de retry
        lui-même, pas la valeur de configuration par défaut.
        """
        context = AgentExecutionContext(trace_id="t1", flow_type="student_evaluation", submission_id=None)
        fake_spec = ModelSpec(provider=ModelProvider.GROQ, model_name="qwen/qwen3.6-27b")
        fake_llm = AsyncMock()
        fake_llm.ainvoke.side_effect = [
            _rate_limit_error(413), _rate_limit_error(413),
            MagicMock(content="ok", response_metadata={}),
        ]
        fake_http_client = AsyncMock()

        with patch("app.llm.client.registry.get_llm_chain", return_value=[(fake_llm, fake_spec, fake_http_client)]):
            with patch("app.llm.client.settings.LLM_RATE_LIMIT_MAX_RETRIES", 3):
                with patch("app.llm.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                    result, spec, fallback, _tokens = await invoke_llm_with_fallback(
                        task_type=TaskType.OCR_VISION, messages=[], context=context,
                    )

        assert fake_llm.ainvoke.await_count == 3
        assert fallback is False  # jamais basculé — succès sur le fournisseur d'origine
        assert spec == fake_spec
        assert mock_sleep.await_count == 2  # une attente entre chaque tentative ratée

    async def test_gives_up_on_this_provider_after_max_retries_then_falls_back(self):
        """Rate limit persistant au-delà du plafond de tentatives -> bascule sur le fournisseur suivant, comportement de repli existant préservé."""
        context = AgentExecutionContext(trace_id="t2", flow_type="student_evaluation", submission_id=None)
        fake_spec_1 = ModelSpec(provider=ModelProvider.GROQ, model_name="qwen/qwen3.6-27b")
        fake_spec_2 = ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini")

        always_limited_llm = AsyncMock()
        always_limited_llm.ainvoke.side_effect = _rate_limit_error(413)
        ok_llm = AsyncMock()
        ok_llm.ainvoke.return_value = MagicMock(content="ok", response_metadata={})

        with patch(
            "app.llm.client.registry.get_llm_chain",
            return_value=[
                (always_limited_llm, fake_spec_1, AsyncMock()),
                (ok_llm, fake_spec_2, AsyncMock()),
            ],
        ):
            with patch("app.llm.client.settings.LLM_RATE_LIMIT_MAX_RETRIES", 3):
                with patch("app.llm.client.asyncio.sleep", new_callable=AsyncMock):
                    result, spec, fallback, _tokens = await invoke_llm_with_fallback(
                        task_type=TaskType.OCR_VISION, messages=[], context=context,
                    )

        assert always_limited_llm.ainvoke.await_count == 3  # LLM_RATE_LIMIT_MAX_RETRIES fixé à 3 pour ce test
        assert fallback is True
        assert spec == fake_spec_2

    async def test_non_rate_limit_error_fails_over_immediately_without_sleeping(self):
        """Non-régression — une erreur qui n'est PAS un rate limit bascule tout de suite, jamais d'attente inutile."""
        context = AgentExecutionContext(trace_id="t3", flow_type="student_evaluation", submission_id=None)
        fake_spec_1 = ModelSpec(provider=ModelProvider.GROQ, model_name="qwen/qwen3.6-27b")
        fake_spec_2 = ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini")

        failing_llm = AsyncMock()
        failing_llm.ainvoke.side_effect = RuntimeError("panne réseau quelconque")
        ok_llm = AsyncMock()
        ok_llm.ainvoke.return_value = MagicMock(content="ok", response_metadata={})

        with patch(
            "app.llm.client.registry.get_llm_chain",
            return_value=[(failing_llm, fake_spec_1, AsyncMock()), (ok_llm, fake_spec_2, AsyncMock())],
        ):
            with patch("app.llm.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result, spec, fallback, _tokens = await invoke_llm_with_fallback(
                    task_type=TaskType.OCR_VISION, messages=[], context=context,
                )

        assert failing_llm.ainvoke.await_count == 1  # aucun retry sur ce fournisseur
        mock_sleep.assert_not_awaited()
        assert fallback is True
        assert spec == fake_spec_2

    async def test_default_config_falls_over_after_single_rate_limit_attempt(self):
        """
        Valeur de production réelle (LLM_RATE_LIMIT_MAX_RETRIES=1, jamais
        patchée ici) : un 413 rate-limit Groq bascule sur le fournisseur
        suivant dès la 1ère tentative, sans attente — cf. app/core/config.py,
        un 413 "Request too large" constaté en usage réel n'est pas un quota
        temporaire qui se libère avec le temps, retenter le même fournisseur
        avec la même requête échoue systématiquement.
        """
        context = AgentExecutionContext(trace_id="t4", flow_type="student_evaluation", submission_id=None)
        fake_spec_1 = ModelSpec(provider=ModelProvider.GROQ, model_name="qwen/qwen3.6-27b")
        fake_spec_2 = ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini")

        limited_llm = AsyncMock()
        limited_llm.ainvoke.side_effect = _rate_limit_error(413)
        ok_llm = AsyncMock()
        ok_llm.ainvoke.return_value = MagicMock(content="ok", response_metadata={})

        with patch(
            "app.llm.client.registry.get_llm_chain",
            return_value=[(limited_llm, fake_spec_1, AsyncMock()), (ok_llm, fake_spec_2, AsyncMock())],
        ):
            with patch("app.llm.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                result, spec, fallback, _tokens = await invoke_llm_with_fallback(
                    task_type=TaskType.OCR_VISION, messages=[], context=context,
                )

        assert limited_llm.ainvoke.await_count == 1
        mock_sleep.assert_not_awaited()
        assert fallback is True
        assert spec == fake_spec_2
