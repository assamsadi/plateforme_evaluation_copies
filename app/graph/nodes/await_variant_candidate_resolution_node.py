"""
Nœud LangGraph — await_variant_candidate_resolution_node.

Point de pause du déclencheur à la demande (2.2) de
Solution_Variant_Generation_Agent (cf. audit Solution_Variant_Generation_Agent
§1b/§2.2) : quand Comparative_Evaluation_Agent ne trouve aucune correspondance
entre une réponse étudiante et les variantes existantes d'une question, il
transmettrait la méthode candidate précise de l'étudiant ici
(state.student_candidate_method) pour vérification, ce qui mettrait la
soumission en pause le temps de la validation professeur — même mécanisme
interrupt()/checkpointer que await_clarification_resolution_node, aucune
nouvelle infrastructure de pause.

État de câblage (câblage Priorité 2) — SORTIE câblée : à la reprise,
state.paused_at_node est posé ICI (pas par un nœud producteur séparé — ce
nœud cumule les rôles de producteur ET de point de pause, contrairement au
couple extraction_verification_node/await_clarification_resolution_node qui
sépare les deux sur deux nœuds distincts) pour permettre à route_after_
variant_candidate_resolution (routing.py) de router vers
comparative_evaluation_node juste après.

ENTRÉE toujours sans edge : le déclencheur 2.2 lui-même (Comparative_
Evaluation_Agent détectant une méthode candidate non reconnue au sein de
comparative_evaluation_node, puis routant ici plutôt que de continuer)
reste hors périmètre de ce ticket (câblage de sortie uniquement, cf. plan
Priorité 2) — non inventé ici. LangGraph n'exige pas qu'un nœud soit
atteignable pour compiler (StateGraph.validate() ne vérifie que les cibles
d'edges existantes, jamais l'accessibilité globale) : ce nœud reste donc
prêt à être câblé côté entrée dès que ce déclencheur existera, testé ici en
isolation via un micro-graph dédié ET via le graph complet (cf.
tests/integration/test_await_variant_candidate_resolution_node.py).
"""
from datetime import datetime, timezone

from langgraph.types import interrupt

from app.graph.state import PipelineState


async def await_variant_candidate_resolution_node(state: PipelineState) -> PipelineState:
    interrupt(
        {
            "reason": "variant_candidate_review",
            "submission_id": state.submission_id,
            "student_candidate_method": state.student_candidate_method,
            "message": (
                "Une méthode candidate d'étudiant non reconnue par les variantes "
                "existantes attend une vérification (validité mathématique + "
                "distinction structurelle) puis une décision du professeur "
                "(accepter/refuser) avant reprise de la correction de cette copie."
            ),
        }
    )
    state.status = "RUNNING"
    state.pending_action = None
    # Posé (pas remis à None) : lu juste après par route_after_variant_
    # candidate_resolution (cf. docstring module ci-dessus) — même principe
    # de staleness assumée que extraction_verification_node/reasoning_graph_
    # node sur ce même champ (jamais nettoyé avant d'avoir été consommé par
    # la edge conditionnelle qui suit immédiatement ce nœud).
    state.paused_at_node = "await_variant_candidate_resolution_node"
    state.student_candidate_method = None
    state.updated_at = datetime.now(timezone.utc)
    return state
