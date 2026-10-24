"""
Nœud LangGraph — await_student_verification_node.

Pas dans la liste des stubs pré-existants — même pattern interrupt() dédié
que les nœuds await_*_resolution_node côté exercise_setup (cf. leurs
docstrings pour le détail). Atteint après question_attachment_node : le
statut PENDING_STUDENT_VERIFICATION déjà posé en base (par
SubmissionOCRPipelineService.run()) est traduit ici en pause de graph
réellement reprenable, plutôt qu'une fin de run + relance manuelle.

Point de reprise UNIQUE pour deux déclencheurs distincts (Command(resume=...)
avec le même thread_id = submission_id) :
  - l'étudiant confirme sa copie sans rien contester -> resume="confirmed",
    fin du graph (rien de plus construit en aval, cf. diagnostic).
  - une contestation est traitée (process_contestation_verification, appel
    HTTP existant, INCHANGÉ, cf. contestation_tasks.py) -> resume=
    "contestation_pending", route vers contestation_verification_node (le
    seul nœud réel pré-existant à ce câblage) pour que son résultat
    (arbitrage nécessaire ou non) soit reflété dans CE thread checkpointé,
    pas seulement en base via l'appel direct.

IMPORTANT — piège constaté en écrivant les tests : Command.resume accepte
soit "un mapping id_interrupt -> valeur" soit "une valeur unique pour le
prochain interrupt" (cf. langgraph.types.Command). Un dict passé en resume
(même non vide) est TOUJOURS interprété comme le premier cas (mapping
d'ids) — jamais comme "une valeur unique qui se trouve être un dict". Un
Command(resume={}) ne résout donc RIEN : l'interrupt reste pending, le nœud
se re-déclenche à l'identique au ainvoke() suivant, silencieusement (aucune
erreur levée). D'où un payload de reprise en chaîne de caractères simple
ici, jamais un dict, pour lever toute ambiguïté à la source plutôt que de
la documenter comme un piège à éviter par convention chez l'appelant.
"""
from datetime import datetime, timezone

from langgraph.types import interrupt

from app.graph.state import PipelineState

RESUME_CONTESTATION_PENDING = "contestation_pending"


async def await_student_verification_node(state: PipelineState) -> PipelineState:
    resume_payload = interrupt(
        {
            "reason": "student_verification",
            "submission_id": state.submission_id,
            "message": (
                "En attente de vérification étudiant — reprise possible sur "
                "confirmation simple ou sur traitement d'une contestation."
            ),
        }
    )
    state.contestation_check_requested = resume_payload == RESUME_CONTESTATION_PENDING
    state.status = "RUNNING"
    state.pending_action = None
    state.updated_at = datetime.now(timezone.utc)
    return state
