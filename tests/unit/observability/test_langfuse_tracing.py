"""
Tests unitaires de création et d'enregistrement des métriques Langfuse.
"""
from unittest.mock import MagicMock, patch
import pytest

from app.observability.langfuse import AgentTraceSpan


def test_agent_trace_span_records_metrics_and_flushes():
    """Vérifie qu'un span AgentTraceSpan enregistre la durée et les métriques avant flush."""
    mock_trace = MagicMock()
    mock_langfuse = MagicMock()
    mock_langfuse.trace.return_value = mock_trace

    with patch("app.observability.langfuse.langfuse", mock_langfuse):
        with AgentTraceSpan(agent_name="TestAgent", trace_id="trace-12345", metadata={"key": "val"}) as span:
            span.record_metrics(
                page_count=2,
                total_block_count=10,
                provider_used="groq",
            )

        mock_langfuse.trace.assert_called_once_with(
            id="trace-12345",
            name="TestAgent",
            metadata={"key": "val"},
        )
        mock_trace.update.assert_called_once()
        update_kwargs = mock_trace.update.call_args.kwargs
        assert update_kwargs["output"]["page_count"] == 2
        assert update_kwargs["output"]["total_block_count"] == 10
        assert update_kwargs["output"]["provider_used"] == "groq"
        assert update_kwargs["output"]["status"] == "SUCCESS"
        assert "total_duration_ms" in update_kwargs["output"]
        mock_langfuse.flush.assert_called_once()
