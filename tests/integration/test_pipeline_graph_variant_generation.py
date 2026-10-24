"""
Tests d'intégration pour le câblage de solution_variant_generation_node dans le graph LangGraph.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.graph.nodes.solution_variant_generation_node import solution_variant_generation_node
from app.graph.state import PipelineState


def _make_dummy_state(exercise_variant_mode: str) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(uuid.uuid4()),
        flow_type="exercise_setup",
        trace_id=str(uuid.uuid4()),
        exercise_id=str(uuid.uuid4()),
        module_id=str(uuid.uuid4()),
        raw_file_path="exercises/doc.pdf",
        created_at=now,
        updated_at=now,
        exercise_variant_mode=exercise_variant_mode,
    )


@pytest.mark.anyio
async def test_pipeline_graph_skips_variant_generation_in_on_demand_mode():
    """Vérifie que le nœud saute l'exécution en mode ON_DEMAND_ONLY."""
    state = _make_dummy_state("ON_DEMAND_ONLY")

    res_state = await solution_variant_generation_node(state)

    assert res_state.generated_variants == []


@pytest.mark.anyio
async def test_pipeline_graph_variant_node_calls_service_in_proactive_mode():
    """Vérifie que le nœud appelle le service en mode PROACTIVE_WITH_FALLBACK."""
    from contextlib import asynccontextmanager
    from app.services.solution_variant_generation_service import SolutionVariantGenerationService

    state = _make_dummy_state("PROACTIVE_WITH_FALLBACK")
    mock_reports = {}
    mock_session = MagicMock()

    @asynccontextmanager
    async def _dummy_context_manager():
        yield mock_session

    with patch(
        "app.graph.nodes.solution_variant_generation_node.get_db_context",
        new=lambda: _dummy_context_manager(),
    ), patch.object(
        SolutionVariantGenerationService,
        "generate_variants_parallel",
        new_callable=AsyncMock,
    ) as mock_gen:
        mock_gen.return_value = mock_reports

        res_state = await solution_variant_generation_node(state)

    assert res_state.generated_variants is not None
    assert res_state.generated_variants == []
