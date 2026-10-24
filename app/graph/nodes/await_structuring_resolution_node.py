"""
Nœud LangGraph — await_structuring_resolution_node.

Pas dans la liste des 23 stubs pré-existants (aucun ne correspondait à ce
rôle) : nœud dédié à la pause via langgraph.types.interrupt(), pattern
idiomatique LangGraph pour un HITL réellement repris au même point plutôt
qu'un simple "fin de run + relance depuis zéro".

Pourquoi un nœud séparé plutôt qu'un interrupt() directement dans
document_structuring_node : au resume (Command(resume=...)), LangGraph
RÉEXÉCUTE la fonction du nœud depuis le début jusqu'à l'appel interrupt()
qui a suspendu — si l'appel avait lieu après avoir déjà relancé OCR+
structuration, un resume rejouerait ces deux agents inutilement (coût LLM
dupliqué, risque de double persistance). Ce nœud ne fait rien d'autre
qu'interrupt() : le rejouer au resume est gratuit.

Atteint uniquement quand document_structuring_node a posé
state.structuring_status == "INCOMPLETE" (edge conditionnelle,
pipeline_graph.py). Le contenu réel (quels blocs/sections manquent) est
déjà en base (StructuringReport toujours persisté, cf. docstring
ExerciseOCRPipelineService) — la valeur passée à interrupt() est un signal
pour l'appelant de ainvoke()/l'outillage d'observation, pas la source de
vérité.

Limite assumée, à ne pas lire comme un oubli : la reprise (Command(resume=...))
fait confiance au signal de reprise lui-même — elle ne relance PAS
Document_Structuring_Agent pour re-vérifier que la structuration est
réellement complète après l'intervention du prof. Aucun service existant
n'expose aujourd'hui "vérifier la complétude sans tout rejouer" comme
opération isolée (ExerciseOCRPipelineService.run() rejoue OCR+structuration
en bloc) ; construire cette vérification isolée est un incrément futur
distinct, pas fabriqué ici sans mandat.
"""
from datetime import datetime, timezone

from langgraph.types import interrupt

from app.graph.state import PipelineState


async def await_structuring_resolution_node(state: PipelineState) -> PipelineState:
    interrupt(
        {
            "reason": "structuring_incomplete",
            "exercise_id": state.exercise_id,
            "message": (
                "Structuration incomplète — blocs non rattachés, sections vides "
                "ou conflits de label à résoudre avant de poursuivre."
            ),
        }
    )
    # Atteint seulement après reprise (Command(resume=...)) — l'appel
    # interrupt() ci-dessus ne retourne jamais lors du premier passage.
    state.structuring_status = "COMPLETE"
    state.status = "RUNNING"
    state.pending_action = None
    state.updated_at = datetime.now(timezone.utc)
    return state
