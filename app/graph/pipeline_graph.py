"""
pipeline_graph.py — graph LangGraph unique pour les 2 flux (exercise_setup,
student_evaluation), branchement conditionnel sur flow_type depuis
entry_router_node (cf. diagnostic établi en conversation : les 2 flux sont
déjà représentés partout ailleurs par un seul discriminant flow_type,
jamais deux structures séparées — PipelineState, AgentExecutionContext,
Job.flow_type).

Les deux branches passent par scan_quality_control_node juste après
entry_router_node — contrôle qualité déterministe (netteté/luminosité/
inclinaison, aucun LLM) commun aux deux flows, avant tout appel vision.

Branche exercise_setup, jusqu'au bout — entry -> scan_quality_control ->
structuring (OCR+Document_Structuring_Agent) -> [pause si incomplet] ->
extraction_verification (Extraction_Verification_Agent) -> [pause si
clarification BLOCKING] -> fin.

Branche student_evaluation (câblage Priorité 1 étendu jusqu'à l'évaluation,
puis Partie 2/2 chantier C2PCT jusqu'au profil de compétences) —
entry -> scan_quality_control -> question_attachment (OCR étudiant+
Question_Attachment_Agent) -> pause (attente de vérification étudiant) ->
soit directement comparative_evaluation_node (confirmation simple),
soit contestation_verification_node si la reprise (Command(resume=...), cf.
contestation_tasks.py/job_tasks.py::process_job_resumed) signale une
contestation à traiter -> comparative_evaluation_node (sauf arbitrage
requis, cf. route_after_contestation_verification -> pause à
teacher_arbitration_node, reprise via process_arbitration_resolved,
cf. arbitration_tasks.py, puis comparative_evaluation_node) -> evaluation_node -> competency_
assessment_node (Competency_Assessment_Agent, Niveau 2 par copie entière +
Niveau 3 décroissance temporelle, cf. son docstring pour la décision de
positionnement APRÈS evaluation_node) -> recommendation_node (Recommendation_
Agent, chantier Phase 2 — relit le profil déjà à jour via get_report(),
jamais un recalcul de assess_submission, cf. son docstring) -> feedback_node
(Feedback_Agent, chantier "Feedback Intelligent" §7 — SEUL nœud du pipeline
qui appelle un LLM pour du texte student-facing, cf. son docstring) -> fin.

Avant ce câblage, route_after_student_verification terminait TOUJOURS le
run immédiatement dans le cas "confirmation simple" (aucune contestation) —
jamais d'évaluation possible même pour une soumission sans aucun problème.
Corrigé : les deux chemins convergent désormais vers comparative_evaluation_
node.

Câblage Priorité 2 — sortie de await_variant_candidate_resolution_node
(déclencheur 2.2, reprise après validation professeur d'une méthode
candidate) câblée vers comparative_evaluation_node (cf. routing.py::
VARIANT_CANDIDATE_RESOLUTION_ROUTING_TABLE, désormais non vide). L'entrée de
ce nœud reste sans edge (cf. son docstring — hors périmètre, non inventée).

Toutes les pauses utilisent langgraph.types.interrupt() (nœuds dédiés
await_*_node, cf. leurs docstrings) plutôt qu'un simple retour à END : un
thread interrompu par interrupt() reste RESUMABLE au même point via
Command(resume=...) avec le même thread_id — c'est tout l'intérêt du
checkpointer Postgres (cf. checkpointer.py) par rapport à l'existant
(statuts DB + relance manuelle depuis zéro).
"""
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.graph.nodes.await_clarification_resolution_node import (
    await_clarification_resolution_node,
)
from app.graph.nodes.await_structuring_resolution_node import (
    await_structuring_resolution_node,
)
from app.graph.nodes.await_student_verification_node import await_student_verification_node
from app.graph.nodes.await_variant_candidate_resolution_node import (
    await_variant_candidate_resolution_node,
)
from app.graph.nodes.comparative_evaluation_node import comparative_evaluation_node
from app.graph.nodes.competency_assessment_node import competency_assessment_node
from app.graph.nodes.contestation_verification_node import contestation_verification_node
from app.graph.nodes.document_structuring_node import document_structuring_node
from app.graph.nodes.entry_router_node import entry_router_node
from app.graph.nodes.evaluation_node import evaluation_node
from app.graph.nodes.extraction_verification_node import extraction_verification_node
from app.graph.nodes.feedback_node import feedback_node
from app.graph.nodes.question_attachment_node import question_attachment_node
from app.graph.nodes.reasoning_graph_node import reasoning_graph_node
from app.graph.nodes.recommendation_node import recommendation_node
from app.graph.nodes.solution_variant_generation_node import (
    solution_variant_generation_node,
)
from app.graph.nodes.scan_quality_control_node import scan_quality_control_node
from app.graph.nodes.teacher_arbitration_node import teacher_arbitration_node
from app.graph.routing import (
    route_after_clarification_resolution,
    route_after_comparative_evaluation,
    route_after_contestation_verification,
    route_after_extraction_verification,
    route_after_reasoning_graph,
    route_after_structuring,
    route_after_student_verification,
    route_after_variant_candidate_resolution,
    route_from_entry,
)
from app.graph.state import PipelineState


def build_pipeline_graph() -> StateGraph:
    """
    Construit le graph non compilé — séparé de compile_pipeline_graph() pour
    permettre l'inspection/les tests de structure sans checkpointer réel
    (compile() sans checkpointer utilise un MemorySaver implicite, inutile
    à tester ici puisque interrupt() sans persistance n'a pas de sens).
    """
    graph = StateGraph(PipelineState)

    graph.add_node("entry_router_node", entry_router_node)
    graph.add_node("scan_quality_control_node", scan_quality_control_node)
    graph.add_node("document_structuring_node", document_structuring_node)
    graph.add_node("await_structuring_resolution_node", await_structuring_resolution_node)
    graph.add_node("extraction_verification_node", extraction_verification_node)
    graph.add_node("reasoning_graph_node", reasoning_graph_node)
    graph.add_node("solution_variant_generation_node", solution_variant_generation_node)
    graph.add_node("await_clarification_resolution_node", await_clarification_resolution_node)
    graph.add_node("question_attachment_node", question_attachment_node)
    graph.add_node("await_student_verification_node", await_student_verification_node)
    graph.add_node("contestation_verification_node", contestation_verification_node)
    graph.add_node("teacher_arbitration_node", teacher_arbitration_node)
    graph.add_node("comparative_evaluation_node", comparative_evaluation_node)
    graph.add_node("evaluation_node", evaluation_node)
    graph.add_node("competency_assessment_node", competency_assessment_node)
    graph.add_node("recommendation_node", recommendation_node)
    graph.add_node("feedback_node", feedback_node)
    # Sortie câblée (Priorité 2, cf. routing.py::VARIANT_CANDIDATE_
    # RESOLUTION_ROUTING_TABLE) vers comparative_evaluation_node. L'entrée
    # reste sans edge (déclencheur 2.2 de Solution_Variant_Generation_Agent,
    # hors périmètre de ce ticket — câblage de sortie uniquement, cf. plan ;
    # non inventé, cf. docstring du nœud).
    graph.add_node("await_variant_candidate_resolution_node", await_variant_candidate_resolution_node)

    graph.add_edge(START, "entry_router_node")
    # scan_quality_control_node avant le branchement flow_type : contrôle
    # qualité déterministe commun aux deux flows, avant tout appel à
    # OCR_Extraction_Agent (cf. son propre docstring — défense en
    # profondeur, ne remplace pas le contrôle interne de l'agent).
    graph.add_edge("entry_router_node", "scan_quality_control_node")
    # path_map explicite partout : les fonctions de routing.py retournent
    # `str` (pas Literal[...]), LangGraph ne peut pas déduire les arêtes par
    # inspection de type — sans path_map explicite, add_conditional_edges()
    # compile silencieusement un graph incomplet (constaté : les arêtes
    # inférées manquantes n'apparaissent ni dans get_graph() ni à l'exécution).
    graph.add_conditional_edges(
        "scan_quality_control_node",
        route_from_entry,
        {
            "document_structuring_node": "document_structuring_node",
            "question_attachment_node": "question_attachment_node",
        },
    )
    graph.add_conditional_edges(
        "document_structuring_node",
        route_after_structuring,
        {
            "await_structuring_resolution_node": "await_structuring_resolution_node",
            "extraction_verification_node": "extraction_verification_node",
        },
    )
    graph.add_edge("await_structuring_resolution_node", "extraction_verification_node")
    graph.add_conditional_edges(
        "extraction_verification_node",
        route_after_extraction_verification,
        {
            "await_clarification_resolution_node": "await_clarification_resolution_node",
            "reasoning_graph_node": "reasoning_graph_node",
        },
    )
    graph.add_conditional_edges(
        "reasoning_graph_node",
        route_after_reasoning_graph,
        {
            "await_clarification_resolution_node": "await_clarification_resolution_node",
            "solution_variant_generation_node": "solution_variant_generation_node",
        },
    )
    graph.add_edge("solution_variant_generation_node", END)
    graph.add_conditional_edges(
        "await_clarification_resolution_node",
        route_after_clarification_resolution,
        {
            "reasoning_graph_node": "reasoning_graph_node",
            # Correctif découvertes annexes (priorité 1) — reprise sur
            # comparative_evaluation_node lui-même, cf. CLARIFICATION_
            # RESOLUTION_ROUTING_TABLE (routing.py).
            "comparative_evaluation_node": "comparative_evaluation_node",
        },
    )

    graph.add_edge("question_attachment_node", "await_student_verification_node")
    graph.add_conditional_edges(
        "await_student_verification_node",
        route_after_student_verification,
        {
            "contestation_verification_node": "contestation_verification_node",
            "comparative_evaluation_node": "comparative_evaluation_node",
        },
    )
    graph.add_conditional_edges(
        "contestation_verification_node",
        route_after_contestation_verification,
        {
            "comparative_evaluation_node": "comparative_evaluation_node",
            "teacher_arbitration_node": "teacher_arbitration_node",
        },
    )
    # teacher_arbitration_node construit (2026-08-18) — reprise déclenchée
    # par ArbitrationService.resolve_correction() (process_arbitration_
    # resolved, cf. arbitration_tasks.py) UNIQUEMENT quand plus aucune
    # CorrectionArbitration PENDING ne reste sur cette soumission ; la
    # reprise fait confiance à cette vérification déjà faite côté service
    # (même principe que await_clarification_resolution_node, cf. son
    # docstring) — continuation directe vers comparative_evaluation_node,
    # jamais un second aiguillage ici.
    graph.add_edge("teacher_arbitration_node", "comparative_evaluation_node")
    # Correctif découvertes annexes (priorité 1) — >=1 clarification
    # BLOCKING résolvable -> pause (await_clarification_resolution_node),
    # jamais une continuation silencieuse vers evaluation_node (cf.
    # docstring comparative_evaluation_node.py / routing.py).
    graph.add_conditional_edges(
        "comparative_evaluation_node",
        route_after_comparative_evaluation,
        {
            "await_clarification_resolution_node": "await_clarification_resolution_node",
            "evaluation_node": "evaluation_node",
        },
    )
    # Câblage Partie 2/2 (C2PCT) — competency_assessment_node APRÈS
    # evaluation_node, jamais à l'intérieur de sa boucle par question (cf.
    # docstring competency_assessment_node.py, Niveau 2 nécessite la
    # soumission entièrement notée).
    graph.add_edge("evaluation_node", "competency_assessment_node")
    # Câblage Phase 2 (chantier Recommendation_Agent) — recommendation_node
    # APRÈS competency_assessment_node, jamais avant : a besoin du profil de
    # compétences (Niveau 2 + Niveau 3) entièrement à jour pour cette
    # soumission (cf. docstring recommendation_node.py).
    graph.add_edge("competency_assessment_node", "recommendation_node")
    # Câblage chantier Feedback_Agent — feedback_node APRÈS recommendation_
    # node, jamais avant : a besoin des RecommendedExercise de CETTE
    # soumission déjà persistées pour pouvoir les mentionner en conclusion
    # du texte socratique (cf. docstring feedback_node.py).
    graph.add_edge("recommendation_node", "feedback_node")
    graph.add_edge("feedback_node", END)

    # Câblage Priorité 2 — sortie de await_variant_candidate_resolution_node
    # (entrée toujours sans edge, cf. son docstring).
    graph.add_conditional_edges(
        "await_variant_candidate_resolution_node",
        route_after_variant_candidate_resolution,
        {
            "comparative_evaluation_node": "comparative_evaluation_node",
        },
    )

    return graph


def compile_pipeline_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    """
    Compile le graph avec un checkpointer déjà ouvert (cf.
    app/graph/checkpointer.py::get_checkpointer) — jamais appelé sans
    checkpointer réel : un graph avec des nœuds interrupt() sans checkpointer
    perd l'état de pause au premier ainvoke() (comportement LangGraph par
    défaut sans persistance, inutilisable pour du HITL réel qui doit
    survivre au-delà du process courant).
    """
    return build_pipeline_graph().compile(checkpointer=checkpointer)
