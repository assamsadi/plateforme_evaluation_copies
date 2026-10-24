"""
Test unitaires pour le fallback automatique du ModelRegistry (Groq -> OpenAI sur timeout/5xx).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.core.exceptions import VisionProviderError
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import ModelProvider, ModelSpec, TaskType
from app.model_registry.registry import ModelRegistry


@pytest.mark.anyio
async def test_automatic_fallback_from_groq_to_openai_on_timeout():
    """Vérifie que si le fournisseur principal (Groq) échoue par timeout, le système bascule automatiquement sur OpenAI."""
    groq_spec = ModelSpec(provider=ModelProvider.GROQ, model_name="llama-3.2-90b-vision-preview")
    openai_spec = ModelSpec(provider=ModelProvider.OPENAI, model_name="gpt-4o-mini")

    mock_registry = ModelRegistry(config={
        TaskType.OCR_VISION: [groq_spec, openai_spec]
    })

    # Groq LLM mock qui lève un TimeoutError sur ainvoke
    groq_llm_mock = AsyncMock()
    groq_llm_mock.ainvoke.side_effect = TimeoutError("Groq timeout")
    groq_llm_mock.with_structured_output.return_value.ainvoke.side_effect = TimeoutError("Groq timeout")

    # OpenAI LLM mock qui réussit
    openai_llm_mock = AsyncMock()
    fake_result = MagicMock()
    fake_result.response_metadata = {"token_usage": {"total_tokens": 150}}
    openai_llm_mock.ainvoke.return_value = fake_result
    openai_llm_mock.with_structured_output.return_value.ainvoke.return_value = fake_result

    def mock_create_llm(spec):
        if spec.provider == ModelProvider.GROQ:
            return groq_llm_mock, AsyncMock()
        return openai_llm_mock, AsyncMock()

    with patch("app.llm.client.registry", mock_registry), \
         patch("app.model_registry.registry.create_llm_from_spec", side_effect=mock_create_llm):

        res, used_spec, fallback_occurred, tokens = await invoke_llm_with_fallback(
            task_type=TaskType.OCR_VISION,
            messages=[{"role": "user", "content": "test"}],
        )

        assert fallback_occurred is True
        assert used_spec.provider == ModelProvider.OPENAI
        assert used_spec.model_name == "gpt-4o-mini"
