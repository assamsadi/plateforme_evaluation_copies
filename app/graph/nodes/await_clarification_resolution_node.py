"""
Nœud LangGraph — await_clarification_resolution_node.

Même rôle et même raison d'être qu'await_structuring_resolution_node (cf.
son docstring pour le détail du pattern interrupt() dédié) : atteint
quand un nœud producteur a posé state.blocking_clarification_count > 0
(edge conditionnelle, pipeline_graph.py) — trois producteurs possibles
aujourd'hui, distingués par state.paused_at_node (cf. CLARIFICATION_
RESOLUTION_ROUTING_TABLE, routing.py) : extraction_verification_node,
reasoning_graph_node, et comparative_evaluation_node (correctif
découvertes annexes, priorité 1 — clarification "réponse alternative
inédite" MULTIPLE_DISTINCT_ANSWERS, résolvable via /clarifications/{id}/
validate-alternative-answer).

Limite assumée identique : la reprise fait confiance au signal (le prof a
répondu aux ReasoningClarificationRequest BLOCKING via l'API dédiée,
cf. ExtractionVerificationService.get_pending_blocking_clarifications), ne
revérifie pas ici qu'elles sont toutes effectivement ANSWERED — cette
vérification est l'affaire de l'appelant qui déclenche la reprise (le futur
process_job_resumed), pas de ce nœud.
"""
from datetime import datetime, timezone

from langgraph.types import interrupt

from app.graph.state import PipelineState


async def await_clarification_resolution_node(state: PipelineState) -> PipelineState:
    interrupt(
        {
            "reason": "clarification_review",
            "exercise_id": state.exercise_id,
            "paused_at_node": state.paused_at_node,
            "blocking_clarification_count": state.blocking_clarification_count,
            "message": (
                "Au moins une clarification BLOCKING (barème proposé non "
                "confirmé, récurrence incomplète, mode test sans matériel, "
                "ou réponse alternative inédite à valider) attend une "
                "réponse du professeur."
            ),
        }
    )
    state.blocking_clarification_count = 0
    state.status = "RUNNING"
    state.pending_action = None
    state.updated_at = datetime.now(timezone.utc)
    return state
