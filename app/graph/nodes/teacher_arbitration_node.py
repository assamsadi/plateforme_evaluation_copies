"""
Nœud LangGraph — teacher_arbitration_node.

Comble le trou d'architecture documenté depuis le début de ce fichier (0
octet, jamais construit) et confirmé par un test réel (2026-08-18,
tests/integration/test_arbitration_service_e2e.py) : sans ce nœud,
route_after_contestation_verification routait directement vers END dès
qu'une soumission nécessitait un arbitrage professeur — le run se
terminait, ArbitrationService.resolve_correction() ne relançait jamais rien
et Submission.status restait bloqué à PENDING_ARBITRATION pour toujours.

Même pattern interrupt() dédié que await_clarification_resolution_node (cf.
son docstring pour le détail du mécanisme général) — même limite assumée
IDENTIQUE : la reprise fait confiance au signal (ArbitrationService.
resolve_correction() a déjà vérifié, avant de déclencher process_
arbitration_resolved, cf. son docstring, qu'AUCUNE CorrectionArbitration
PENDING ne reste sur cette soumission), ce nœud ne revérifie rien en base —
cette vérification est l'affaire de l'appelant qui déclenche la reprise,
pas de ce nœud (cf. app/tasks/arbitration_tasks.py).

state.arbitration_required est remis à False ici (jamais dans le résolveur
côté service, qui ne touche jamais PipelineState — seul un nœud de graph le
fait, cf. tous les autres await_*_node) pour que route_after_contestation_
verification ne route plus jamais vers ce nœud si jamais ce même state était
réévalué (défensif, ne devrait pas arriver : un thread repris continue après
ce nœud, jamais en arrière).
"""
from datetime import datetime, timezone

from langgraph.types import interrupt

from app.graph.state import PipelineState


async def teacher_arbitration_node(state: PipelineState) -> PipelineState:
    interrupt(
        {
            "reason": "teacher_arbitration",
            "submission_id": state.submission_id,
            "message": (
                "Au moins une extraction contestée reste AMBIGUË — en attente "
                "d'un arbitrage du professeur (POST /arbitrations/corrections/"
                "{id}/resolve)."
            ),
        }
    )
    state.arbitration_required = False
    state.status = "RUNNING"
    state.pending_action = None
    state.updated_at = datetime.now(timezone.utc)
    return state
