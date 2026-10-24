"""
Nœud LangGraph — solution_variant_generation_node.

Appelé après reasoning_graph_node dans le flux exercise_setup.
Génère de manière proactive les variantes alternatives de résolution pour les questions
de l'exercice si le mode PROACTIVE_WITH_FALLBACK est actif.
"""
from datetime import datetime, timezone
import logging
import uuid

from app.core.database import get_db_context
from app.graph.state import PipelineState
from app.services.solution_variant_generation_service import SolutionVariantGenerationService

logger = logging.getLogger(__name__)


async def solution_variant_generation_node(state: PipelineState) -> PipelineState:
    """Nœud de génération proactive de variantes de solution."""
    # Si le mode est "ON_DEMAND_ONLY", aucune génération à froid n'est effectuée.
    if state.exercise_variant_mode == "ON_DEMAND_ONLY":
        logger.info("Mode ON_DEMAND_ONLY actif pour l'exercice %s : pas de génération proactive de variantes.", state.exercise_id)
        state.generated_variants = []
        state.updated_at = datetime.now(timezone.utc)
        return state

    exercise_id = uuid.UUID(state.exercise_id)

    async with get_db_context() as db:
        service = SolutionVariantGenerationService(db)
        reports_by_question = await service.generate_variants_parallel(
            exercise_id=exercise_id,
            trace_id=state.trace_id,
        )

        all_generated: list[dict] = []
        for qid, report in reports_by_question.items():
            for cand in report.candidates:
                all_generated.append({
                    "question_id": str(qid),
                    "strategy_name": cand.strategy_name,
                    "content": cand.content,
                    "reasoning_summary": cand.reasoning_summary,
                    "difficulty_level": cand.difficulty_level.value,
                    "outside_academic_envelope": cand.outside_academic_envelope,
                    "outside_concepts": cand.outside_concepts,
                })

    state.generated_variants = all_generated
    state.updated_at = datetime.now(timezone.utc)
    return state
