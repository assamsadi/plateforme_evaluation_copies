"""
Nœud LangGraph — reasoning_graph_node.

Appelé après extraction_verification_node (quand aucune clarification bloquante d'extraction n'est en attente).
Construit et persiste le graphe de raisonnement (DAG) pour la/les SolutionVariant(s)
de référence du professeur pour l'exercice.

Si au moins une ClarificationRequest BLOCKING est générée par Reasoning_Graph_Agent
(seuils de confiance/couverture, cycle non résolu après retry, etc.), bascule state.status à PAUSED
et state.pending_action à clarification_review pour interruption HITL sur await_clarification_resolution_node.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import get_db_context
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.solution_variant import SolutionVariant
from app.graph.state import PipelineState
from app.services.reasoning_graph_service import ReasoningGraphService


MAX_RETRIES = 3


async def reasoning_graph_node(state: PipelineState) -> PipelineState:
    exercise_id = uuid.UUID(state.exercise_id)

    async with get_db_context() as db:
        stmt = (
            select(SolutionVariant)
            .join(Question, Question.id == SolutionVariant.question_id)
            .where(Question.exercise_id == exercise_id, SolutionVariant.is_reference == True)
        )
        result = await db.execute(stmt)
        ref_variants = list(result.scalars().all())

        # Si des cibles spécifiques étaient en attente suite à une pause précédente,
        # on ne traite QUE ces cibles (reprise ciblée).
        is_resume = bool(state.pending_reasoning_graph_variant_ids)
        if is_resume:
            pending_set = set(state.pending_reasoning_graph_variant_ids)
            target_variants = [v for v in ref_variants if str(v.id) in pending_set]
        else:
            target_variants = ref_variants

        service = ReasoningGraphService(db)
        total_blocking = 0
        still_pending_variant_ids: list[str] = []

        for variant in target_variants:
            variant_str = str(variant.id)

            # Garde-fou anti-boucle : incrémenter le compteur si on est en reprise sur ce variant
            if is_resume or state.paused_at_node == "reasoning_graph_node":
                retry_count = state.reasoning_graph_retry_counts.get(variant_str, 0) + 1
                state.reasoning_graph_retry_counts[variant_str] = retry_count
                if retry_count > MAX_RETRIES:
                    raise RuntimeError(
                        f"Nombre maximal de retentatives HITL ({MAX_RETRIES}) dépassé "
                        f"pour la variante de référence {variant.id}"
                    )

            read_model = await service.build_graph_for_variant(
                variant_id=variant.id,
                trace_id=state.trace_id,
            )

            if read_model.blocking_clarification_count > 0:
                total_blocking += read_model.blocking_clarification_count
                still_pending_variant_ids.append(variant_str)

    state.pending_reasoning_graph_variant_ids = still_pending_variant_ids
    state.blocking_clarification_count = total_blocking

    if still_pending_variant_ids:
        state.status = "PAUSED"
        state.pending_action = "clarification_review"
        state.paused_at_node = "reasoning_graph_node"
    else:
        state.status = "RUNNING"
        state.pending_action = None
        state.paused_at_node = None

    state.updated_at = datetime.now(timezone.utc)
    return state

