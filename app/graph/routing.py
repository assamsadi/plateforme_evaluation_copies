"""
Fonctions de routage LangGraph — edges conditionnelles de pipeline_graph.py.

Pures : lisent PipelineState, retournent le nom du nœud suivant. Aucun effet
de bord ici — la mutation d'état vit dans les nœuds eux-mêmes
(entry_router_node, document_structuring_node, extraction_verification_node,
...), jamais dans une fonction de routage. Plus aucune de ces fonctions ne
retourne langgraph.graph.END directement (2026-08-18 — teacher_arbitration_
node construit, dernière route qui y menait) ; END reste utilisé directement
dans pipeline_graph.py pour les arêtes non conditionnelles de fin de branche.
"""
from app.graph.state import PipelineState


def route_from_entry(state: PipelineState) -> str:
    """
    Branchement initial, depuis entry_router_node. flow_type est le seul
    discriminant entre les 2 flux (cf. diagnostic pipeline_graph : jamais
    deux structures parallèles pour les représenter).
    """
    if state.flow_type == "exercise_setup":
        return "document_structuring_node"
    return "question_attachment_node"


def route_after_structuring(state: PipelineState) -> str:
    """
    INCOMPLETE -> pause (await_structuring_resolution_node). Jamais de
    continuation silencieuse : c'est déjà un verrou bloquant côté service
    (StructuringIncompleteError, cf. document_structuring_node), la edge ne
    fait que traduire ce verrou en pause de graph plutôt qu'en exception qui
    remonterait jusqu'à la tâche Celery.
    """
    if state.structuring_status == "INCOMPLETE":
        return "await_structuring_resolution_node"
    return "extraction_verification_node"


def route_after_extraction_verification(state: PipelineState) -> str:
    """
    >=1 ClarificationRequest BLOCKING -> pause (await_clarification_resolution_node).
    Sinon -> reasoning_graph_node pour construire le graphe de raisonnement de référence.
    """
    if state.blocking_clarification_count > 0:
        return "await_clarification_resolution_node"
    return "reasoning_graph_node"


def route_after_reasoning_graph(state: PipelineState) -> str:
    """
    >=1 ClarificationRequest BLOCKING -> pause (await_clarification_resolution_node).
    Sinon -> solution_variant_generation_node pour la génération proactive de variantes.
    """
    if state.blocking_clarification_count > 0:
        return "await_clarification_resolution_node"
    return "solution_variant_generation_node"


def route_after_student_verification(state: PipelineState) -> str:
    """
    Payload de reprise demandant une vérification de contestation
    (state.contestation_check_requested, posé par await_student_verification_node
    à partir de Command(resume=...)) -> contestation_verification_node.
    Sinon (confirmation simple de l'étudiant) -> comparative_evaluation_node
    directement (câblage Priorité 1 : avant ce câblage, ce cas terminait le
    run immédiatement sans jamais atteindre l'évaluation — corrigé ici, une
    soumission non contestée doit être évaluée comme les autres).
    """
    if state.contestation_check_requested:
        return "contestation_verification_node"
    return "comparative_evaluation_node"


def route_after_contestation_verification(state: PipelineState) -> str:
    """
    Câblage Priorité 1, étendu (2026-08-18, teacher_arbitration_node
    construit — cf. son docstring) — state.arbitration_required est posé par
    contestation_verification_node. Une soumission nécessitant un arbitrage
    professeur ne doit JAMAIS atteindre comparative_evaluation_node
    (défense en profondeur, doublée dans le nœud lui-même) — route vers
    teacher_arbitration_node (pause interrupt(), reprise déclenchée par
    ArbitrationService.resolve_correction() via process_arbitration_resolved,
    cf. arbitration_tasks.py) plutôt que END. Sinon -> comparative_evaluation_node.
    """
    if state.arbitration_required:
        return "teacher_arbitration_node"
    return "comparative_evaluation_node"


def route_after_comparative_evaluation(state: PipelineState) -> str:
    """
    Correctif découvertes annexes (priorité 1) — >=1 clarification BLOCKING
    résolvable (cf. docstring comparative_evaluation_node.py, uniquement le
    sous-cas MULTIPLE_DISTINCT_ANSWERS/COHERENT/aucun match RAG, jamais
    AMBIGUOUS_COHERENCE qui n'a aucun point de résolution) -> pause
    (await_clarification_resolution_node). Avant ce correctif, cette edge
    était inconditionnelle vers evaluation_node — une copie pouvait être
    notée (partiellement, la question bloquante étant exclue) sans que
    personne ne soit jamais notifié qu'un point restait ambigu.
    """
    if state.blocking_clarification_count > 0:
        return "await_clarification_resolution_node"
    return "evaluation_node"


CLARIFICATION_RESOLUTION_ROUTING_TABLE = {
    "extraction_verification_node": "reasoning_graph_node",
    "reasoning_graph_node": "reasoning_graph_node",
    # Correctif découvertes annexes (priorité 1) — reprise sur LUI-MÊME
    # (même pattern que reasoning_graph_node ci-dessus, pas une invention) :
    # comparative_evaluation_node doit être RE-EXÉCUTÉ, pas sauté, pour que
    # la résolution du prof (indexée dans ValidatedAlternativeAnswer via
    # /clarifications/{id}/validate-alternative-answer) soit effectivement
    # relue par la recherche RAG (search_similar) au prochain passage —
    # sauter directement à evaluation_node laisserait la question encore
    # marquée "blocking" dans une projection jamais recalculée.
    "comparative_evaluation_node": "comparative_evaluation_node",
}


def route_after_clarification_resolution(state: PipelineState) -> str:
    """
    Route de manière stricte après la résolution d'une clarification HITL.
    Vérifie state.paused_at_node dans la table de routage. Lève une ValueError si inconnu.
    """
    paused_node = state.paused_at_node
    if not paused_node:
        raise ValueError(
            "Reprise de clarification demandée mais state.paused_at_node est vide ou None."
        )
    if paused_node not in CLARIFICATION_RESOLUTION_ROUTING_TABLE:
        raise ValueError(
            f"Nœud de pause '{paused_node}' inconnu dans la table de routage après clarification."
        )
    return CLARIFICATION_RESOLUTION_ROUTING_TABLE[paused_node]


# Câblage Priorité 2 — Comparative_Evaluation_Agent existe et
# comparative_evaluation_node est câblé (Priorité 1) : la reprise après
# await_variant_candidate_resolution_node (déclencheur 2.2) route désormais
# vers comparative_evaluation_node, exactement comme n'importe quelle autre
# soumission une fois la méthode candidate tranchée par le professeur.
# Clé = state.paused_at_node tel que posé PAR await_variant_candidate_
# resolution_node lui-même à la reprise (cf. son docstring — ce nœud est à
# la fois producteur et point de pause, contrairement au couple extraction_
# verification_node/await_clarification_resolution_node qui sépare les deux
# rôles sur deux nœuds distincts).
VARIANT_CANDIDATE_RESOLUTION_ROUTING_TABLE: dict[str, str] = {
    "await_variant_candidate_resolution_node": "comparative_evaluation_node",
}


def route_after_variant_candidate_resolution(state: PipelineState) -> str:
    """
    Même pattern strict que route_after_clarification_resolution : lève une
    ValueError explicite plutôt que de deviner une destination si
    state.paused_at_node est vide ou absent de la table (jamais un mapping
    inventé vers END ou un autre nœud).
    """
    paused_node = state.paused_at_node
    if not paused_node:
        raise ValueError(
            "Reprise de méthode candidate demandée mais state.paused_at_node est vide ou None."
        )
    if paused_node not in VARIANT_CANDIDATE_RESOLUTION_ROUTING_TABLE:
        raise ValueError(
            f"Nœud de pause '{paused_node}' inconnu dans la table de routage après résolution "
            f"de méthode candidate."
        )
    return VARIANT_CANDIDATE_RESOLUTION_ROUTING_TABLE[paused_node]

