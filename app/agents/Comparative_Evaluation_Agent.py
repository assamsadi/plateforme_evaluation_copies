"""
Agent — Comparative_Evaluation_Agent (Phase 3/5).

Implémente les 7 modes de correction (§5 du document d'architecture) :
1. SOLUTION_WORKED : comparaison par graphe de raisonnement / solution travaillée.
2. CRITERIA_BASED : évaluation par conditions vérifiables atomiques (garde-fou anti-biais).
3. BINARY_CHECKLIST : verdict booléen strict par critère / condition.
4. MULTIPLE_DISTINCT_ANSWERS : RAG sémantique + filtre de cohérence + clarification HITL.
5. RUBRIC_LEVELS : classification ancrée sur les descriptions textuelles du professeur.
6. PROCEDURAL_SEQUENCE : 2 signaux distincts (présence des étapes & respect de l'ordre).
7. TEST_CASE_BASED : exécution déléguée à Judge0SandboxService (distinction visibles/cachés,
   indication explicite mock vs judge0_remote dans tools_consulted, complexité informative).

Traçabilité (§0 du document) : Produit un AgentDecisionLog pour CHAQUE mode d'évaluation.
Dispatcher : Si correction_mode est inconnu, lève UnknownCorrectionModeError (pas de repli par défaut).

Correctifs (ticket bugs critiques, cf. diagnostic Phases 1-3) :
- Tous les appels LLM passent par _call_llm_json, qui utilise la VRAIE
  signature de invoke_llm_with_fallback (messages/response_schema/context,
  retour 4-tuple) — cf. Reasoning_Graph_Agent.py:142 comme référence exacte.
  Un seul point d'appel : un futur bug de signature ne peut plus se
  reproduire sur un seul site sans affecter tous les autres.
- SOLUTION_WORKED : implémentation réelle (plus un stub), verdict PAR ÉTAPE
  étudiante, jamais un verdict global. downstream_step_refs côté étudiant
  est calculé LOCALEMENT ici (networkx.descendants, même algorithme que
  Reasoning_Graph_Agent, mais dupliqué — aucune bibliothèque partagée
  n'existe encore, cf. diagnostic ; Reasoning_Graph_Agent lui-même reste
  scopé exclusivement aux SolutionVariant, jamais aux réponses d'étudiants,
  donc pas question de l'y faire transiter). canonical_form réutilisé via
  ExtractionVerificationAgent._compute_canonical_form (réutilisation directe
  d'une fonction pure existante, pas une duplication). numeric_tolerance
  n'est PAS parsé algorithmiquement (texte libre, décision produit
  explicitement différée ailleurs dans le codebase) — transmis en contexte
  au LLM pour son jugement qualitatif quand canonical_form ne suffit pas.
- MULTIPLE_DISTINCT_ANSWERS : filtre de cohérence à 3 statuts (CoherenceStatus),
  jamais un booléen à 2 états. AMBIGUOUS_COHERENCE -> ClarificationRequest
  BLOCKING (jamais un verdict tranché en zone d'incertitude, cf. §0), jamais
  INFORMATIONAL (qui signifierait au contraire "aucun impact, aucune action
  requise" — l'inverse de ce qui est demandé ici). Câblage Priorité 3 : la
  recherche RAG cible validated_alternative_answers (réponses étudiantes
  validées par un professeur, filtrées par question_id/criterion_id), plus
  reasoning_clarification_requests (mécanisme few-shot de Reasoning_Graph_
  Agent — table sémantiquement différente, jamais un match croisé possible
  désormais, cf. _eval_multiple_distinct_answers).

Mécanisme de résolution AMBIGUOUS_COHERENCE (correctif découvertes annexes,
suite au ticket pause HITL) — EvaluationRequest.coherence_ambiguity_
resolutions (clé=criterion_id) permet à comparative_evaluation_node.py de
faire "comme si" le filtre de cohérence avait initialement renvoyé COHERENT
ou INCOHERENT une fois le professeur consulté (ReasoningClarificationRequest.
resolved_as_coherent) : bypass du SEUL appel LLM de classification dans
_eval_multiple_distinct_answers, la suite de la méthode (recherche RAG,
branches COHERENT/INCOHERENT déjà existantes) tourne SANS AUCUNE
modification — jamais une deuxième logique de notation créée en parallèle.

Phase 3/4 — verdict par sous-question C2PCT (SubquestionJudgment) :
- Juge UNIQUEMENT les sous-questions que le professeur a réellement couvertes
  (request.covered_subquestions, produit par Extraction_Verification_Agent
  Phase 2/4) — jamais au-delà. Aucune note/ratio/point ici : rôle exclusif
  d'un futur Pedagogical_Evaluation_Agent (Phase 4, pas construit ici).
- Deux niveaux jamais fusionnés : addressed (présence) puis is_correct
  (qualité, uniquement si addressed=true — None sinon, NOT_ADDRESSED n'est
  jamais confondu avec une tentative incorrecte).
- Détection FACTORISÉE (pas un second mécanisme) : le premier passage
  déterministe rapidfuzz vit désormais dans
  app.domain.models.competency.c2pct_detection.fuzzy_candidate_subquestions,
  réutilisé À L'IDENTIQUE ici sur le texte de l'étudiant — Extraction_
  Verification_Agent._fuzzy_candidate_subquestions délègue au même module
  (cf. son propre docstring). Le jugement LLM sur l'intention reste propre à
  chaque agent (textes/appels différents), pas mutualisable à ce niveau.
- Deux voies de jugement : (a) sous-questions d'ALGORITHMIC_STRUCTURING
  (3.1/3.2) réutilisent le verdict SOLUTION_WORKED déjà produit
  (step_judgments) SI un tel critère existe pour cette question — jamais un
  second jugement contradictoire possible ; limite assumée : faute de
  granularité plus fine dans SOLUTION_WORKED, 3.1 et 3.2 partagent le même
  verdict dérivé (addressed=True si step_judgments non vide, is_correct=
  all(is_locally_correct)). (b) toutes les autres (narratives) : UN SEUL
  nouvel appel LLM par question, batché sur toutes à la fois (jamais un
  appel par sous-question, jamais greffé sur un des 7 appels par-critère
  existants — granularité différente, transversal à la question entière).
- Traçabilité : copy_report/DecisionEntry restent INEXISTANTS dans ce
  codebase (revérifié à cette phase) — un AgentDecisionLog (mécanisme déjà
  en place, §0) sert de substitut, avec les mêmes clés sémantiques
  (decision/reason/evidence_reference) dans output_summary.
  [Note historique — DecisionEntry/copy_report ont depuis été construits,
  cf. plus bas dans ce fichier et docstring evaluation_node.py.]

Chantier notation graduée par éléments vérifiables (extension du principe
CRITERIA_BASED à toutes les sous-questions) — is_correct (binaire) ne
disparaît PAS : Pedagogical_Evaluation_Agent.py et Competency_Assessment_
Agent.py le lisent directement et sont hors périmètre de ce chantier.
completion_ratio/verifiable_elements sont AJOUTÉS sur SubquestionJudgment ;
is_correct devient DÉRIVÉ de completion_ratio (True ssi ratio == 1.0),
jamais un second jugement LLM indépendant — comportement binaire strictement
inchangé pour tout consommateur qui ignore ces nouveaux champs. Aucun
nouvel appel LLM : verifiable_elements est extrait dans le MÊME appel que
la détection de couverture narrative (_judge_narrative_subquestions) ; côté
reused_step_judgment (3.1/3.2), le ratio est dérivé de step_judgments
(plusieurs étapes déjà jugées individuellement — pas le repli binaire
1-pour-1, cf. docstring _judge_subquestions).
"""
import json
import logging
import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal

import networkx as nx
from pydantic import BaseModel, Field

from app.agents.context import AgentExecutionContext
from app.agents.comparative_evaluation_exceptions import UnknownCorrectionModeError
from app.agents.Extraction_Verification_Agent import (
    ClarificationRequest,
    ClarificationSeverity,
    CorrectionMode,
    ExtractionVerificationAgent,
)
from app.domain.models.assessment.reasoning_clarification_request import ClarificationStatus
from app.domain.models.competency.c2pct_detection import fuzzy_candidate_subquestions
from app.domain.models.competency.c2pct_scaffold import (
    find_subquestion_by_id,
    get_all_subquestions,
    get_competency_for_subquestion,
    get_subquestions_for,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.system_infrastructure.agent_decision_log import AgentDecisionLog
from app.infra_services.judge0_sandbox_service import Judge0SandboxService, TestCaseRunResult
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType
from app.observability.langfuse import AgentTraceSpan
from app.prompts.comparative_evaluation_prompt import (
    BINARY_CHECKLIST_SYSTEM_PROMPT,
    BINARY_CHECKLIST_USER_TEMPLATE,
    COHERENCE_CHECK_SYSTEM_PROMPT,
    COHERENCE_CHECK_USER_TEMPLATE,
    CRITERIA_BASED_SYSTEM_PROMPT,
    CRITERIA_BASED_USER_TEMPLATE,
    PROCEDURAL_SEQUENCE_SYSTEM_PROMPT,
    PROCEDURAL_SEQUENCE_USER_TEMPLATE,
    RUBRIC_LEVELS_SYSTEM_PROMPT,
    RUBRIC_LEVELS_USER_TEMPLATE,
    SOLUTION_WORKED_SYSTEM_PROMPT,
    SOLUTION_WORKED_USER_TEMPLATE,
    SUBQUESTION_JUDGMENT_SYSTEM_PROMPT,
    SUBQUESTION_JUDGMENT_USER_TEMPLATE,
)
from app.repositories.rag_repository import search_similar

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entrées / Sorties de Comparative_Evaluation_Agent
# ---------------------------------------------------------------------------

@dataclass
class CriterionEvaluationInput:
    criterion_id: str  # ID du critère dans le barème
    label: str  # ex: "exactitude", "respect du protocole"
    points: Decimal
    correction_mode: CorrectionMode | str
    verifiable_conditions: list[str] = field(default_factory=list)
    rubric_levels: list[dict] = field(default_factory=list)  # [{"level": "Excellent", "description": "..."}]
    expected_steps: list[str] = field(default_factory=list)  # Pour PROCEDURAL_SEQUENCE
    test_cases: list[dict] = field(default_factory=list)  # Pour TEST_CASE_BASED
    reference_code: str | None = None
    expected_complexity: str | None = None


@dataclass
class StudentResponseInput:
    question_id: uuid.UUID
    student_answer_text: str
    code_submission: str | None = None
    structured_content: dict | None = None


@dataclass
class EvaluationRequest:
    question_id: uuid.UUID
    question_statement: str
    student_response: StudentResponseInput
    criteria: list[CriterionEvaluationInput]
    reference_solution_text: str | None = None
    # Étapes de la solution de référence, telles que produites par
    # Reasoning_Graph_Agent (step_ref/order/step_type/description/formula/
    # depends_on_refs) et complétées si possible par les signaux Phase 3b
    # d'Extraction_Verification_Agent (canonical_form/numeric_tolerance) —
    # ces 2 derniers ne sont PAS garantis présents (cf. docstring module :
    # reasoning_graph_service.py ne les fait pas encore transiter), donc
    # consommés défensivement (.get()) partout où ils sont lus.
    reasoning_graph_steps: list[dict] = field(default_factory=list)
    # Méthode/outil explicitement imposé par la consigne (Phase 5A
    # d'Extraction_Verification_Agent, QuestionVerificationResult.
    # mandated_method) — None si aucune méthode n'est imposée, jamais deviné.
    mandated_method: str | None = None
    # Phase 3/4 — id des sous-questions officielles C2PCT réellement
    # couvertes par le PROFESSEUR pour cette question (Extraction_
    # Verification_Agent Phase 2/4, QuestionVerificationResult.
    # covered_subquestions) — jamais au-delà : la seule autorité sur ce qui
    # est mobilisé reste la correction du prof, pas cet agent.
    covered_subquestions: list[str] = field(default_factory=list)
    # Correctif AMBIGUOUS_COHERENCE — clé = criterion_id, résolution déjà
    # tranchée par le professeur (ReasoningClarificationRequest.
    # resolved_as_coherent, cf. comparative_evaluation_node.py) pour un
    # critère MULTIPLE_DISTINCT_ANSWERS dont le filtre de cohérence avait
    # produit AMBIGUOUS_COHERENCE. Bypass le SEUL appel LLM de classification
    # (cf. _eval_multiple_distinct_answers) — jamais un nouveau calcul de
    # score, la suite de la méthode (recherche RAG, branches existantes)
    # reste strictement inchangée.
    coherence_ambiguity_resolutions: dict[str, Literal["coherent", "incoherent"]] = field(
        default_factory=dict
    )
    # 2026-08-18 — règles générales du barème du professeur, non rattachées
    # à un critère précis (Extraction_Verification_Agent.QuestionVerification
    # Result.general_rules — fusion des 2 mécanismes d'extraction, classique
    # Cas 1/2 et C2PCT natif Cas 0, qui restent séparés en amont). Injectées
    # dans CHAQUE appel LLM de cet agent (cf. _call_llm_json) pour influencer
    # un VERDICT — jamais un calcul de points direct (ajout/retrait), hors
    # périmètre tant que l'agent responsable du calcul final des points
    # n'existe pas (Pedagogical_Evaluation_Agent).
    general_rules: list[str] = field(default_factory=list)


@dataclass
class ConditionEvaluation:
    condition_text: str
    satisfied: bool
    justification: str
    confidence: float = 1.0


@dataclass
class StepPresenceEvaluation:
    step_name: str
    present: bool
    justification: str


@dataclass
class SequenceOrderingEvaluation:
    is_order_correct: bool
    misplaced_steps: list[str]
    justification: str


class CoherenceStatus(StrEnum):
    """
    Bug 3 — filtre de cohérence à 3 statuts (jamais un booléen à 2 états) :
    une zone d'incertitude réelle ne doit jamais être forcée vers l'un ou
    l'autre côté. Cf. _classify_coherence pour les 2 seuils.
    """
    COHERENT = "coherent"
    INCOHERENT = "incoherent"
    AMBIGUOUS_COHERENCE = "ambiguous_coherence"


@dataclass
class SolutionWorkedStepJudgment:
    """
    Bug 2 — verdict PAR ÉTAPE étudiante (jamais un verdict global). Chaque
    étape est jugée par rapport à sa PROPRE étape précédente (is_locally_
    correct), jamais directement contre la référence — c'est ce qui permet
    l'erreur reportée (carries_forward_error) : une étape peut être
    is_locally_correct=True tout en héritant d'une erreur commise plus tôt
    par l'étudiant lui-même, sans être une nouvelle erreur indépendante.
    """
    step_ref: str
    order: int
    description: str
    justification: str
    depends_on_refs: list[str] = field(default_factory=list)
    # Calculé localement (networkx.descendants) dans cet agent — cf.
    # docstring module : aucune bibliothèque partagée avec Reasoning_Graph_
    # Agent n'existe encore, et celui-ci ne traite jamais les réponses
    # d'étudiants de toute façon.
    downstream_step_refs: list[str] = field(default_factory=list)
    # step_ref de l'étape de référence à laquelle celle-ci correspond le
    # plus, ou None si aucune correspondance claire (étape superflue,
    # méthode différente) — jamais déduit par ordre/position, fourni par le
    # LLM qui voit le texte complet des deux côtés.
    aligned_reference_step_ref: str | None = None
    is_locally_correct: bool = True
    # True si is_locally_correct=True MAIS cette étape dépend (directement
    # ou transitivement) d'une étape antérieure où is_locally_correct=False
    # — erreur reportée : ne doit jamais être pénalisée une deuxième fois,
    # l'origine de l'erreur est l'étape en amont, pas celle-ci.
    carries_forward_error: bool = False


@dataclass
class CriterionEvaluationResult:
    criterion_id: str
    correction_mode: CorrectionMode
    is_satisfied: bool | None = None
    score_ratio: float = 0.0  # 0.0 à 1.0
    assigned_level: str | None = None
    condition_evaluations: list[ConditionEvaluation] = field(default_factory=list)
    step_presence: list[StepPresenceEvaluation] = field(default_factory=list)
    sequence_ordering: SequenceOrderingEvaluation | None = None
    test_case_results: list[TestCaseRunResult] = field(default_factory=list)
    execution_mode: Literal["mock", "judge0_remote", "sandbox_local"] | None = None
    observed_complexity: str | None = None
    clarification_request: ClarificationRequest | None = None
    justification: str = ""
    confidence_score: float = 1.0
    decision_log: AgentDecisionLog | None = None
    # SOLUTION_WORKED uniquement — verdict par étape, cf. SolutionWorkedStepJudgment.
    step_judgments: list[SolutionWorkedStepJudgment] = field(default_factory=list)
    # SOLUTION_WORKED uniquement — séparé du verdict d'exactitude. None si
    # mandated_method n'était pas renseigné pour la question (rien à
    # vérifier), jamais déduit/forcé à une valeur par défaut.
    consigne_respected: bool | None = None
    # MULTIPLE_DISTINCT_ANSWERS uniquement — cf. CoherenceStatus.
    coherence_status: CoherenceStatus | None = None


@dataclass
class VerifiableElement:
    """
    Chantier notation graduée — un élément concret et vérifiable individuellement,
    extrait de la correction de référence du professeur (ou de la description
    méthodologique de la sous-question à défaut) au sein du MÊME appel LLM que
    la détection de couverture (aucun appel réseau supplémentaire). Même
    principe que ConditionEvaluation (mode CRITERIA_BASED) : jamais un score
    continu demandé directement au LLM, un jugement binaire simple par élément,
    le taux global dérivé en code du ratio d'éléments présents.
    """
    description: str
    present_in_student_answer: bool
    evidence_reference: str | None  # extrait exact de la réponse étudiante, None si absent


@dataclass
class SubquestionJudgment:
    """
    Phase 3/4 — verdict par sous-question C2PCT réellement couverte par le
    professeur (jamais au-delà). Deux niveaux jamais fusionnés : addressed
    (présence, indépendante de la qualité) puis la qualité, UNIQUEMENT si
    addressed=True.

    Chantier notation graduée — la qualité n'est plus un binaire jugé
    directement par le LLM : completion_ratio (0.0 à 1.0, None si
    addressed=False — jamais 0.0, une absence n'est pas un taux nul) est
    calculé en code depuis verifiable_elements (ratio d'éléments présents),
    jamais vide si completion_ratio est renseigné.

    is_correct CONSERVÉ (jamais supprimé) pour compatibilité descendante
    stricte — Pedagogical_Evaluation_Agent.py et Competency_Assessment_Agent.py
    (via evaluation_node.py/StudentCompetencyObservation.subquestion_outcomes)
    lisent ce champ directement et sont explicitement HORS PÉRIMÈTRE de ce
    chantier. is_correct n'est plus un second jugement LLM indépendant : il
    est désormais DÉRIVÉ de completion_ratio à la construction (True ssi
    completion_ratio == 1.0, None ssi completion_ratio est None) — jamais de
    désaccord possible entre les deux, comportement binaire strictement
    identique à l'ancien pour tout consommateur qui ignore completion_ratio.
    """
    subquestion_id: str  # référence au module c2pct_scaffold, ex. "1.1"
    addressed: bool
    is_correct: bool | None  # dérivé de completion_ratio, cf. docstring ci-dessus — None si addressed=False
    evidence_reference: str | None  # extrait de la réponse étudiante, None si addressed=False
    # Traçabilité de la voie utilisée : verdict SOLUTION_WORKED réutilisé
    # tel quel (ALGORITHMIC_STRUCTURING, 3.1/3.2, si step_judgments existe
    # pour cette question) ou nouveau jugement LLM narratif batché.
    source: Literal["reused_step_judgment", "new_llm_judgment"]
    completion_ratio: Decimal | None = None
    verifiable_elements: list[VerifiableElement] = field(default_factory=list)


@dataclass
class DecisionEntry:
    """
    Câblage copy_report (§0 : "chaque décision vérifiable, traçable et
    contestable sur la base de preuves explicites") — une entrée UNIQUEMENT
    pour les cas NON TRIVIAUX (cf. _build_decision_entries), jamais une par
    SubquestionJudgment systématiquement : un rapport qui liste aussi
    chaque réussite sans ambiguïté se noie dans le bruit et perd son
    utilité pour le professeur/l'étudiant qui le consulte.

    reason est une phrase déterministe (template + valeurs déjà calculées
    par c2pct_scaffold/SubquestionJudgment), jamais un nouvel appel LLM.
    """
    subquestion_id: str
    competency: C2PCTSkillCode
    decision: Literal["NOT_ADDRESSED", "INCORRECT", "REUSED_FROM_STEP_JUDGMENT"]
    reason: str
    evidence_reference: str | None

    def to_dict(self) -> dict:
        return {
            "subquestion_id": self.subquestion_id,
            "competency": self.competency.value,
            "decision": self.decision,
            "reason": self.reason,
            "evidence_reference": self.evidence_reference,
        }

    @staticmethod
    def from_dict(d: dict) -> "DecisionEntry":
        return DecisionEntry(
            subquestion_id=d["subquestion_id"],
            competency=C2PCTSkillCode(d["competency"]),
            decision=d["decision"],
            reason=d["reason"],
            evidence_reference=d.get("evidence_reference"),
        )


@dataclass
class ComparativeEvaluationReport:
    question_id: uuid.UUID
    criterion_results: list[CriterionEvaluationResult]
    overall_confidence: float
    clarifications: list[ClarificationRequest] = field(default_factory=list)
    decision_logs: list[AgentDecisionLog] = field(default_factory=list)
    # Phase 3/4 — une entrée par id de request.covered_subquestions, jamais
    # plus, jamais moins. Liste vide si covered_subquestions est vide.
    subquestion_judgments: list[SubquestionJudgment] = field(default_factory=list)
    # Câblage copy_report — cf. DecisionEntry, produit par _build_decision_
    # entries() APRÈS subquestion_judgments (mêmes entrées, filtrées aux
    # cas non triviaux + texte explicatif).
    decision_entries: list[DecisionEntry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Schémas de sortie structurée pour les 6 formes JSON attendues par
# _call_llm_json (2026-08-18) — remplacent l'ancien point d'appel unique en
# response_schema=None + regex JSON (_JSON_PATTERN = re.compile(r"\{.*\}"))
# + json.loads, même bug déjà trouvé et corrigé cette session sur 5 autres
# agents (Document_Structuring_Agent, Extraction_Verification_Agent,
# Reasoning_Graph_Agent, Solution_Variant_Generation_Agent, Contestation_
# Verification_Agent). Ici la centralisation existante (_call_llm_json,
# point d'appel unique voulu par le module dès sa conception — cf. docstring
# module) joue en faveur du fix : une seule fonction à corriger, response_
# schema devient un paramètre OBLIGATOIRE (jamais de défaut None) pour
# empêcher qu'un futur site d'appel oublie de le fournir et retombe
# silencieusement sur l'ancien comportement fragile.
# ---------------------------------------------------------------------------

class _VerifiableElementLLM(BaseModel):
    description: str = ""
    present_in_student_answer: bool = False
    evidence_reference: str | None = None


class _SubquestionJudgmentLLM(BaseModel):
    subquestion_id: str
    addressed: bool = False
    verifiable_elements: list[_VerifiableElementLLM] = Field(default_factory=list)


class _SubquestionJudgmentsSchema(BaseModel):
    """_judge_narrative_subquestions."""
    judgments: list[_SubquestionJudgmentLLM] = Field(default_factory=list)


class _StudentStepLLM(BaseModel):
    step_ref: str | None = None
    order: int = 0
    description: str = ""
    justification: str = ""
    depends_on_refs: list[str] = Field(default_factory=list)
    aligned_reference_step_ref: str | None = None
    is_locally_correct: bool = True


class _SolutionWorkedSchema(BaseModel):
    """_eval_solution_worked (mode 1)."""
    student_steps: list[_StudentStepLLM] = Field(default_factory=list)
    final_conclusion_value: str | None = None
    consigne_respected: bool | None = None


class _ConditionEvaluationLLM(BaseModel):
    condition_text: str = ""
    satisfied: bool = False
    justification: str = ""
    confidence: float = 0.9


class _CriteriaBasedSchema(BaseModel):
    """_eval_criteria_based (mode 2)."""
    condition_evaluations: list[_ConditionEvaluationLLM] = Field(default_factory=list)
    overall_justification: str | None = None


class _BinaryChecklistSchema(BaseModel):
    """
    _eval_binary_checklist (mode 3, 2026-08-18) — jugement propre, ne
    réutilise plus _CriteriaBasedSchema : verifiable_conditions est
    TOUJOURS vide pour ce mode (garde-fou anti-biais côté Extraction_
    Verification_Agent, réservé à CRITERIA_BASED), donc l'ancienne
    délégation à _eval_criteria_based tombait systématiquement dans son
    repli "aucune condition -> satisfait par défaut", validant n'importe
    quelle copie sans jamais la lire (trouvé sur test réel, cf. mémoire de
    session).
    """
    satisfied: bool = False
    justification: str = ""


class _CoherenceCheckSchema(BaseModel):
    """_eval_multiple_distinct_answers (mode 4) — filtre de cohérence."""
    coherence_score: float = Field(ge=0.0, le=1.0, default=0.5)


class _RubricLevelsSchema(BaseModel):
    """_eval_rubric_levels (mode 5)."""
    assigned_level: str = "Insuffisant"
    justification: str | None = None


class _StepPresenceLLM(BaseModel):
    step_name: str = ""
    present: bool = False
    justification: str = ""


class _SequenceOrderingLLM(BaseModel):
    is_order_correct: bool = True
    misplaced_steps: list[str] = Field(default_factory=list)
    justification: str = ""


class _ProceduralSequenceSchema(BaseModel):
    """_eval_procedural_sequence (mode 6)."""
    step_presence: list[_StepPresenceLLM] = Field(default_factory=list)
    sequence_ordering: _SequenceOrderingLLM = Field(default_factory=_SequenceOrderingLLM)


# ---------------------------------------------------------------------------
# Classe Agent Principal
# ---------------------------------------------------------------------------

class ComparativeEvaluationAgent:
    """
    Agent d'évaluation comparative par question/critère.
    """
    AGENT_NAME = "Comparative_Evaluation_Agent"

    # Bug 3 — 2 seuils déterministes pour CoherenceStatus (cf. _classify_coherence).
    # Valeurs empiriques par défaut, à calibrer après observation en usage réel.
    _COHERENCE_HIGH_THRESHOLD = 0.7
    _COHERENCE_LOW_THRESHOLD = 0.3

    # Chantier notation graduée — précision de completion_ratio (0.667 pour
    # 2/3, cf. scénario de référence). Distincte de _CENTS-like arrondis
    # ailleurs dans ce projet (ex. score_ratio CRITERIA_BASED à 2 décimales) :
    # ce ratio n'est jamais directement multiplié par un montant en euros,
    # une précision plus fine est donc sans risque et plus fidèle au décompte
    # réel d'éléments.
    _RATIO_PRECISION = Decimal("0.001")

    def __init__(self, sandbox_service: Judge0SandboxService | None = None):
        self._sandbox_service = sandbox_service or Judge0SandboxService()

    async def _call_llm_json(
        self,
        system_prompt: str,
        user_prompt: str,
        ctx: AgentExecutionContext,
        response_schema: type[BaseModel],
        general_rules: list[str] | None = None,
    ) -> tuple[BaseModel, str]:
        """
        Point d'appel LLM UNIQUE pour ce fichier — vraie signature de
        invoke_llm_with_fallback (messages/response_schema/context, retour
        4-tuple), cf. Reasoning_Graph_Agent.py:142 comme référence exacte.
        Centralisé pour qu'un bug de signature ne puisse plus se reproduire
        sur un site isolé sans affecter tous les modes qui en dépendent.

        response_schema OBLIGATOIRE (2026-08-18, jamais de défaut None) :
        sortie structurée, plus un JSON extrait par regex d'une réponse en
        prose — même bug déjà trouvé et corrigé sur 5 autres agents cette
        session, ici corrigé une seule fois pour les 6 modes qui appellent
        cette méthode grâce à la centralisation déjà en place.

        general_rules (2026-08-18) — règles générales du barème du prof,
        cf. EvaluationRequest.general_rules. Injectées ici, centralement,
        plutôt que dans chaque *_SYSTEM_PROMPT séparément : garantit que
        les 7 appels LLM de cet agent (les 6 modes + le jugement des
        sous-questions C2PCT) les reçoivent tous de façon identique, sans
        dépendre de ce que chaque call site pense à faire. Aucun effet si
        vide/None (système inchangé pour un barème sans règle générale).
        """
        if general_rules:
            rules_block = "\n".join(f"- {r}" for r in general_rules)
            system_prompt = (
                f"{system_prompt}\n\n"
                "Règles générales du barème du professeur, applicables à toute "
                "la question (pas seulement au critère jugé ici) — à respecter "
                "impérativement dans ton jugement, même si elles ne sont "
                "rattachées à aucun critère individuel :\n"
                f"{rules_block}"
            )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        result, spec, fallback, _tokens = await invoke_llm_with_fallback(
            task_type=TaskType.COMPARATIVE_EVALUATION,
            messages=messages,
            response_schema=response_schema,
            context=ctx,
        )
        parsed = (
            result if isinstance(result, response_schema)
            else response_schema.model_validate(result)
        )
        model_version = f"{spec.provider}:{spec.model_name}" + ("+fallback" if fallback else "")
        return parsed, model_version

    async def execute(
        self,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> ComparativeEvaluationReport:
        """
        Point d'entrée principal : évalue la copie d'un étudiant par rapport aux
        critères du barème de la question.
        """
        logger.info(
            "[%s] Évaluation comparative de la question %s (%d critères)",
            self.AGENT_NAME, request.question_id, len(request.criteria),
        )

        with AgentTraceSpan(self.AGENT_NAME, ctx.trace_id, ctx.metadata) as span:
            criterion_results: list[CriterionEvaluationResult] = []
            clarifications: list[ClarificationRequest] = []
            decision_logs: list[AgentDecisionLog] = []

            for crit in request.criteria:
                # Normalisation & vérification stricte du correction_mode
                mode_str = str(crit.correction_mode).lower()
                try:
                    mode_enum = CorrectionMode(mode_str)
                except ValueError:
                    raise UnknownCorrectionModeError(mode_str) from None

                crit_result = await self._dispatch_criterion(
                    mode=mode_enum,
                    crit=crit,
                    request=request,
                    ctx=ctx,
                )
                criterion_results.append(crit_result)

                if crit_result.clarification_request:
                    clarifications.append(crit_result.clarification_request)
                if crit_result.decision_log:
                    decision_logs.append(crit_result.decision_log)

            overall_conf = (
                sum(c.confidence_score for c in criterion_results) / len(criterion_results)
                if criterion_results else 1.0
            )

            # Phase 3/4 — verdict par sous-question C2PCT, APRÈS la boucle
            # de critères (a besoin des step_judgments déjà produits par un
            # éventuel critère SOLUTION_WORKED pour décider quelle voie
            # utiliser). Uniquement les sous-questions du prof
            # (request.covered_subquestions), jamais au-delà.
            subquestion_judgments = await self._judge_subquestions(request, criterion_results, ctx)
            if subquestion_judgments:
                decision_logs.append(
                    self._build_subquestion_decision_log(request, subquestion_judgments)
                )

            # Câblage copy_report — step_judgments recalculé ici (même
            # liste que celle interne à _judge_subquestions, jamais
            # modifiée) uniquement pour enrichir le texte des DecisionEntry
            # REUSED_FROM_STEP_JUDGMENT avec l'étape source précise
            # (numéro/description) — _judge_subquestions lui-même reste
            # intouché, aucune logique déjà validée retouchée.
            step_judgments = [j for cr in criterion_results for j in cr.step_judgments]
            decision_entries = self._build_decision_entries(subquestion_judgments, step_judgments)

            report = ComparativeEvaluationReport(
                question_id=request.question_id,
                criterion_results=criterion_results,
                overall_confidence=overall_conf,
                clarifications=clarifications,
                decision_logs=decision_logs,
                subquestion_judgments=subquestion_judgments,
                decision_entries=decision_entries,
            )

            span.record_metrics(
                criterion_count=len(criterion_results),
                clarification_count=len(clarifications),
                overall_confidence=round(overall_conf, 3),
                subquestion_judgment_count=len(subquestion_judgments),
            )
            return report

    async def _dispatch_criterion(
        self,
        mode: CorrectionMode,
        crit: CriterionEvaluationInput,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> CriterionEvaluationResult:
        """Dispatcher vers la bonne méthode d'évaluation selon le correction_mode."""
        if mode == CorrectionMode.SOLUTION_WORKED:
            return await self._eval_solution_worked(crit, request, ctx)
        elif mode == CorrectionMode.CRITERIA_BASED:
            return await self._eval_criteria_based(crit, request, ctx)
        elif mode == CorrectionMode.BINARY_CHECKLIST:
            return await self._eval_binary_checklist(crit, request, ctx)
        elif mode == CorrectionMode.MULTIPLE_DISTINCT_ANSWERS:
            return await self._eval_multiple_distinct_answers(crit, request, ctx)
        elif mode == CorrectionMode.RUBRIC_LEVELS:
            return await self._eval_rubric_levels(crit, request, ctx)
        elif mode == CorrectionMode.PROCEDURAL_SEQUENCE:
            return await self._eval_procedural_sequence(crit, request, ctx)
        elif mode == CorrectionMode.TEST_CASE_BASED:
            return await self._eval_test_case_based(crit, request, ctx)
        else:
            raise UnknownCorrectionModeError(str(mode))

    # -----------------------------------------------------------------------
    # Phase 3/4 — Jugement par sous-question C2PCT (transversal à la
    # question, indépendant des 7 modes ci-dessous — jamais une note/un ratio)
    # -----------------------------------------------------------------------
    async def _judge_subquestions(
        self,
        request: EvaluationRequest,
        criterion_results: list[CriterionEvaluationResult],
        ctx: AgentExecutionContext,
    ) -> list[SubquestionJudgment]:
        """
        Une entrée par id de request.covered_subquestions (le prof), jamais
        au-delà — si l'étudiant répond à une sous-question hors de cette
        liste, aucun verdict n'est produit pour elle, absente du résultat.

        Deux voies, jamais un double jugement contradictoire possible :
          (a) ALGORITHMIC_STRUCTURING (3.1/3.2) réutilise le verdict
              SOLUTION_WORKED déjà produit SI au moins un critère de cette
              question a produit des step_judgments — sinon, retombe
              naturellement en voie narrative (b), aucun câblage spécial requis.
          (b) toutes les autres : un seul appel LLM narratif, batché.
        """
        covered = request.covered_subquestions
        if not covered:
            return []

        step_judgments = [j for cr in criterion_results for j in cr.step_judgments]
        reused_ids: set[str] = set()
        if step_judgments:
            algo_ids = {sq.id for sq in get_subquestions_for(C2PCTSkillCode.ALGORITHMIC_STRUCTURING)}
            reused_ids = set(covered) & algo_ids

        judgments: list[SubquestionJudgment] = []

        if reused_ids:
            # Limite assumée (documentée dans le docstring module) : faute
            # de granularité plus fine dans SOLUTION_WORKED, 3.1 et 3.2
            # partagent le même verdict dérivé de l'ensemble des step_judgments.
            #
            # Chantier notation graduée — step_judgments porte DÉJÀ plusieurs
            # étapes jugées individuellement (is_locally_correct par étape) :
            # exactement le cas "plusieurs éléments mappés" du chantier, pas
            # le repli binaire 1-pour-1 (cf. plan). Chaque étape devient un
            # VerifiableElement (réutilise _compute_completion_ratio, jamais
            # un second calcul de ratio dupliqué) — completion_ratio == 1.0
            # ssi all(is_locally_correct), donc is_correct dérivé reste
            # STRICTEMENT identique à l'ancien all_correct (aucune régression
            # de comportement pour Pedagogical_Evaluation_Agent).
            step_elements = [
                VerifiableElement(
                    description=j.description, present_in_student_answer=j.is_locally_correct,
                    evidence_reference=None,
                )
                for j in sorted(step_judgments, key=lambda j: j.order)
            ]
            ratio = self._compute_completion_ratio(step_elements)
            evidence = "; ".join(j.description for j in step_judgments if j.description)[:300] or None
            for sq_id in sorted(reused_ids):
                judgments.append(
                    SubquestionJudgment(
                        subquestion_id=sq_id,
                        addressed=True,
                        is_correct=self._derive_is_correct(ratio),
                        evidence_reference=evidence,
                        source="reused_step_judgment",
                        completion_ratio=ratio,
                        verifiable_elements=step_elements,
                    )
                )

        narrative_ids = [sq_id for sq_id in covered if sq_id not in reused_ids]
        if narrative_ids:
            judgments.extend(
                await self._judge_narrative_subquestions(request, narrative_ids, ctx)
            )

        return judgments

    async def _judge_narrative_subquestions(
        self,
        request: EvaluationRequest,
        subquestion_ids: list[str],
        ctx: AgentExecutionContext,
    ) -> list[SubquestionJudgment]:
        """
        UN SEUL appel LLM, batché sur toutes les sous-questions narratives
        de la question à la fois (jamais un appel par sous-question).
        Même esprit que CRITERIA_BASED : jamais une comparaison de
        similarité textuelle, un vrai jugement de fond sur l'intention.

        Chantier notation graduée — le même appel LLM extrait désormais
        AUSSI les verifiable_elements par sous-question (aucun appel réseau
        supplémentaire, extension du schéma déjà en place) ; completion_ratio/
        is_correct sont calculés en code (jamais un score demandé
        directement au LLM, cf. décision actée du chantier).
        """
        student_text = request.student_response.student_answer_text

        subquestions = [sq for sq in get_all_subquestions() if sq.id in subquestion_ids]
        subquestions_block = "\n".join(f'- "{sq.id}" : {sq.reference_prompt}' for sq in subquestions)

        # Détection FACTORISÉE (Phase 2 -> module partagé), jamais un second
        # mécanisme réimplémenté ici — indice seulement, jamais un filtre.
        fuzzy_candidates = fuzzy_candidate_subquestions(student_text) & set(subquestion_ids)
        fuzzy_hints_block = ", ".join(sorted(fuzzy_candidates)) or "aucun"

        # reference_solution_text : SolutionVariant.content (is_reference=True),
        # None si aucune référence n'existe pour cette question (cf. docstring
        # EvaluationRequest) — repli explicite documenté dans le prompt système
        # (base-toi sur la description méthodologique), jamais un blocage.
        reference_solution_block = (
            request.reference_solution_text.strip()
            if request.reference_solution_text else
            "Aucune correction de référence textuelle disponible pour cette question."
        )

        user_prompt = SUBQUESTION_JUDGMENT_USER_TEMPLATE.format(
            question_statement=request.question_statement,
            student_answer=student_text,
            reference_solution_block=reference_solution_block,
            subquestions_block=subquestions_block,
            fuzzy_hints_block=fuzzy_hints_block,
        )

        parsed, _model_version = await self._call_llm_json(
            system_prompt=SUBQUESTION_JUDGMENT_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            ctx=ctx,
            response_schema=_SubquestionJudgmentsSchema,
            general_rules=request.general_rules,
        )

        valid_ids = set(subquestion_ids)
        judgments: list[SubquestionJudgment] = []
        for raw in parsed.judgments:
            sq_id = raw.subquestion_id
            # Garde-fou anti-hallucination : jamais un id hors de ce qui a
            # été explicitement demandé dans cet appel.
            if sq_id not in valid_ids:
                continue
            addressed = raw.addressed

            elements: list[VerifiableElement] = []
            if addressed:
                for el in raw.verifiable_elements:
                    present = el.present_in_student_answer
                    elements.append(
                        VerifiableElement(
                            description=el.description,
                            present_in_student_answer=present,
                            evidence_reference=el.evidence_reference if present else None,
                        )
                    )

            ratio = self._compute_completion_ratio(elements) if addressed else None
            # evidence_reference au niveau sous-question : le premier extrait
            # présent parmi les éléments (traçabilité globale conservée pour
            # les consommateurs qui ne regardent pas verifiable_elements,
            # ex. AgentDecisionLog) — None si aucun élément présent ou non adressée.
            top_level_evidence = next(
                (e.evidence_reference for e in elements if e.present_in_student_answer and e.evidence_reference),
                None,
            )
            judgments.append(
                SubquestionJudgment(
                    subquestion_id=sq_id,
                    addressed=addressed,
                    is_correct=self._derive_is_correct(ratio),
                    evidence_reference=top_level_evidence,
                    source="new_llm_judgment",
                    completion_ratio=ratio,
                    verifiable_elements=elements,
                )
            )
        return judgments

    @classmethod
    def _compute_completion_ratio(cls, elements: list[VerifiableElement]) -> Decimal:
        """
        Chantier notation graduée — ratio d'éléments présents, jamais un
        score continu demandé directement au LLM. Liste vide (le LLM n'a
        identifié aucun élément vérifiable malgré addressed=True — cas
        dégénéré, jamais censé se produire en pratique) traitée comme 0.0,
        jamais une exception ni un ratio de 1.0 injustifié.
        """
        if not elements:
            return Decimal("0.000")
        present_count = sum(1 for e in elements if e.present_in_student_answer)
        ratio = Decimal(present_count) / Decimal(len(elements))
        return ratio.quantize(cls._RATIO_PRECISION, rounding=ROUND_HALF_UP)

    @staticmethod
    def _derive_is_correct(completion_ratio: Decimal | None) -> bool | None:
        """
        Compatibilité descendante stricte (cf. docstring SubquestionJudgment)
        — is_correct=True ssi TOUS les éléments/étapes sont présents, jamais
        un second jugement LLM indépendant. Comportement binaire identique à
        l'ancien mécanisme pour tout consommateur qui ignore completion_ratio.
        """
        if completion_ratio is None:
            return None
        return completion_ratio == Decimal("1.000")

    @staticmethod
    def _build_subquestion_decision_log(
        request: EvaluationRequest, judgments: list[SubquestionJudgment],
    ) -> AgentDecisionLog:
        """
        Traçabilité TECHNIQUE (§0) — log brut destiné à l'audit interne,
        pas au professeur/étudiant (cf. DecisionEntry/_build_decision_entries
        ci-dessous pour le document lisible, câblage copy_report). Conservé
        tel quel, intouché par ce câblage — même clés sémantiques
        (decision/reason/evidence_reference) mais texte technique, pas une
        phrase pédagogique.
        """
        entries = []
        for j in judgments:
            if not j.addressed:
                entries.append({
                    "subquestion_id": j.subquestion_id,
                    "decision": "NOT_ADDRESSED",
                    "reason": "Sous-question couverte par le professeur mais non adressée par l'étudiant.",
                    "evidence_reference": None,
                })
            elif j.is_correct is False:
                entries.append({
                    "subquestion_id": j.subquestion_id,
                    "decision": "INCORRECT",
                    "reason": "Sous-question adressée mais jugée non satisfaisante par rapport à l'intention.",
                    "evidence_reference": j.evidence_reference,
                })

        correct_count = sum(1 for j in judgments if j.addressed and j.is_correct)
        not_addressed_count = sum(1 for j in judgments if not j.addressed)
        incorrect_count = sum(1 for j in judgments if j.addressed and j.is_correct is False)
        justification = (
            f"{len(judgments)} sous-question(s) C2PCT jugée(s) : {correct_count} correcte(s), "
            f"{incorrect_count} incorrecte(s), {not_addressed_count} non adressée(s)."
        )

        return AgentDecisionLog(
            agent_name=ComparativeEvaluationAgent.AGENT_NAME,
            related_entity_type="Question",
            related_entity_id=request.question_id,
            justification=justification,
            confidence_score=Decimal("0.9"),
            model_version="comparative_eval:subquestions",
            input_summary=json.dumps({"covered_subquestions": request.covered_subquestions}),
            output_summary=json.dumps({"entries": entries}),
            tools_consulted=[],
        )

    @staticmethod
    def _build_decision_entries(
        subquestion_judgments: list[SubquestionJudgment],
        step_judgments: list[SolutionWorkedStepJudgment],
    ) -> list[DecisionEntry]:
        """
        Câblage copy_report — document LISIBLE (§0), pas un log technique
        (cf. AgentDecisionLog ci-dessus). Une entrée UNIQUEMENT pour les cas
        non triviaux : addressed=False (NOT_ADDRESSED), is_correct=False
        (INCORRECT, prioritaire sur REUSED_FROM_STEP_JUDGMENT même si
        source="reused_step_judgment" — l'erreur prime sur l'explication du
        mécanisme), ou source="reused_step_judgment" avec un verdict correct
        (REUSED_FROM_STEP_JUDGMENT, utile à expliquer même sans problème).
        Une réussite via un jugement narratif neuf (source="new_llm_judgment",
        is_correct=True) ne produit JAMAIS d'entrée — sinon le rapport se
        noie dans le bruit d'une réussite sans ambiguïté et perd son utilité.

        reason est un template rempli avec des valeurs déjà calculées
        (c2pct_scaffold, SubquestionJudgment, step_judgments) — jamais un
        nouvel appel LLM.

        subquestion_id inconnu de c2pct_scaffold (get_competency_for_
        subquestion renvoie None) : entrée sautée, jamais une compétence
        devinée (même garde que Pedagogical_Evaluation_Agent).
        """
        entries: list[DecisionEntry] = []

        # Toutes les étapes SOLUTION_WORKED de la question, triées par ordre
        # — 3.1/3.2 partagent le même verdict dérivé de l'ENSEMBLE de ces
        # étapes (limite assumée, cf. _judge_subquestions), donc listées
        # toutes ensemble plutôt qu'une seule "étape source" par sous-question.
        steps_str = "; ".join(
            f"étape {j.order} ({j.description})"
            for j in sorted(step_judgments, key=lambda j: j.order)
        )[:400] or "aucune étape disponible"

        for j in subquestion_judgments:
            skill = get_competency_for_subquestion(j.subquestion_id)
            if skill is None:
                continue

            sq = find_subquestion_by_id(j.subquestion_id)
            label = sq.label if sq is not None else j.subquestion_id

            if not j.addressed:
                reason = (
                    f"La sous-question {j.subquestion_id} ({label}) fait partie des "
                    f"sous-questions couvertes par le professeur pour cette question, "
                    f"mais n'a pas été traitée dans la copie de l'étudiant : aucun "
                    f"passage de la réponse n'y correspond."
                )
                entries.append(DecisionEntry(j.subquestion_id, skill, "NOT_ADDRESSED", reason, None))
            elif not j.is_correct:
                # Chantier notation graduée — décompte par éléments quand
                # disponible (les deux sources en produisent désormais,
                # cf. _judge_narrative_subquestions/_judge_subquestions),
                # jamais juste "incorrect" sans détail exploitable.
                if j.verifiable_elements:
                    breakdown = ComparativeEvaluationAgent._format_elements_breakdown(j.verifiable_elements)
                    reason = (
                        f"La sous-question {j.subquestion_id} ({label}) a été traitée par "
                        f"l'étudiant, mais seulement partiellement : {breakdown}"
                    )
                else:
                    reason = (
                        f"La sous-question {j.subquestion_id} ({label}) a été traitée par "
                        f"l'étudiant, mais le contenu proposé ne répond pas correctement à "
                        f"cette exigence."
                    )
                if j.evidence_reference:
                    reason += f' Extrait évalué : "{j.evidence_reference}".'
                entries.append(DecisionEntry(j.subquestion_id, skill, "INCORRECT", reason, j.evidence_reference))
            elif j.source == "reused_step_judgment":
                reason = (
                    f"La sous-question {j.subquestion_id} ({label}) n'a pas été jugée "
                    f"séparément : son verdict reprend celui déjà établi lors de "
                    f"l'évaluation de la méthode travaillée (SOLUTION_WORKED) pour "
                    f"cette question, faute de granularité plus fine entre les étapes "
                    f"3.1 et 3.2. Étape(s) source : {steps_str}."
                )
                entries.append(
                    DecisionEntry(j.subquestion_id, skill, "REUSED_FROM_STEP_JUDGMENT", reason, j.evidence_reference)
                )
            # else : addressed=True, is_correct=True, source="new_llm_judgment"
            # -> cas trivial, aucune entrée (cf. docstring ci-dessus).

        return entries

    @staticmethod
    def _format_elements_breakdown(elements: list[VerifiableElement]) -> str:
        """
        Chantier notation graduée — phrase déterministe (template + valeurs
        déjà calculées, jamais un nouvel appel LLM, même discipline que
        _build_decision_entries) résumant le décompte d'éléments vérifiables,
        ex. "2 élément(s) sur 3 identifié(s) : la longueur, le périmètre
        présent(s), mais la largeur absent(s) de la réponse."
        """
        present = [e.description for e in elements if e.present_in_student_answer]
        absent = [e.description for e in elements if not e.present_in_student_answer]
        sentence = f"{len(present)} élément(s) sur {len(elements)} identifié(s)"
        if present:
            sentence += " : " + ", ".join(present) + " présent(s)"
        if absent:
            sentence += (", mais " if present else " : ") + ", ".join(absent) + " absent(s) de la réponse"
        return sentence + "."

    # -----------------------------------------------------------------------
    # 1. Mode SOLUTION_WORKED
    # -----------------------------------------------------------------------
    async def _eval_solution_worked(
        self,
        crit: CriterionEvaluationInput,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> CriterionEvaluationResult:
        """
        Bug 2 — comparaison réelle étape par étape. Verdict PAR ÉTAPE
        étudiante (jamais un verdict global) : chaque étape est jugée par
        rapport à sa PROPRE étape précédente, jamais directement contre la
        référence — c'est ce qui permet l'erreur reportée (une étape qui
        prolonge correctement un calcul déjà faux chez l'étudiant n'est pas
        une nouvelle erreur, cf. _propagate_carries_forward_error).
        """
        reference_steps = request.reasoning_graph_steps
        reference_steps_json = (
            json.dumps(
                [
                    {
                        "step_ref": s.get("step_ref"),
                        "order": s.get("order"),
                        "step_type": s.get("step_type"),
                        "description": s.get("description"),
                        "formula": s.get("formula"),
                    }
                    for s in reference_steps
                ],
                ensure_ascii=False,
            )
            if reference_steps else "(aucune décomposition de référence disponible)"
        )

        mandated_method_instruction = (
            f"La méthode/l'outil suivant est explicitement imposé par la consigne : "
            f"« {request.mandated_method} ». Détermine si l'étudiant l'a effectivement "
            f"utilisé (consigne_respected)."
            if request.mandated_method
            else "Aucune méthode n'est imposée pour cette question — laisse consigne_respected à null."
        )

        user_prompt = SOLUTION_WORKED_USER_TEMPLATE.format(
            question_statement=request.question_statement,
            reference_steps_json=reference_steps_json,
            reference_solution_text=request.reference_solution_text or "(aucun texte de référence disponible)",
            student_answer=request.student_response.student_answer_text,
        )
        system_prompt = SOLUTION_WORKED_SYSTEM_PROMPT.format(
            mandated_method_instruction=mandated_method_instruction,
        )

        parsed, model_version = await self._call_llm_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            ctx=ctx,
            response_schema=_SolutionWorkedSchema,
            general_rules=request.general_rules,
        )

        judgments = self._parse_student_step_judgments(parsed, reference_steps)
        self._compute_downstream_refs(judgments)
        self._propagate_carries_forward_error(judgments)

        # Équivalence de la conclusion : canonical_form déjà produit côté
        # référence est réutilisé tel quel (jamais recalculé) ; seule la
        # valeur étudiante est parsée, via la même fonction pure que
        # Extraction_Verification_Agent. None si aucune comparaison
        # déterministe n'est possible -> le jugement LLM déjà porté par
        # is_locally_correct de l'étape finale reste seul applicable.
        equivalence_override = self._check_final_equivalence(
            parsed.final_conclusion_value, reference_steps,
        )
        final_judgment = judgments[-1] if judgments else None
        if equivalence_override is not None and final_judgment is not None:
            final_judgment.is_locally_correct = equivalence_override
            final_judgment.justification = (
                f"{final_judgment.justification} "
                f"[Équivalence symbolique déterministe (canonical_form) appliquée en priorité.]"
            ).strip()

        known_reference_refs = {s.get("step_ref") for s in reference_steps if s.get("step_ref")}
        aligned_correct_refs = {
            j.aligned_reference_step_ref for j in judgments
            if j.aligned_reference_step_ref and j.is_locally_correct
        }
        if reference_steps:
            score_ratio = round(len(aligned_correct_refs) / len(known_reference_refs), 2) if known_reference_refs else 0.0
        else:
            # Aucune référence structurée disponible : seul le jugement de
            # l'étape finale (déjà informé par le texte de référence libre,
            # cf. reference_solution_text dans le prompt) reste exploitable.
            score_ratio = 1.0 if (final_judgment and final_judgment.is_locally_correct) else 0.0
        is_satisfied = final_judgment.is_locally_correct if final_judgment else False

        consigne_respected: bool | None = None
        if request.mandated_method is not None:
            consigne_respected = parsed.consigne_respected

        justification = (
            f"SOLUTION_WORKED : {len(judgments)} étape(s) étudiante(s) jugée(s), "
            f"{sum(1 for j in judgments if j.is_locally_correct)} localement correcte(s), "
            f"{sum(1 for j in judgments if j.carries_forward_error)} héritant d'une erreur reportée."
        )

        log = self._create_decision_log(
            request=request,
            mode=CorrectionMode.SOLUTION_WORKED,
            justification=justification,
            confidence=0.9,
            model_version=model_version,
            output_summary={
                "score_ratio": score_ratio,
                "is_satisfied": is_satisfied,
                "step_count": len(judgments),
                "carried_forward_error_count": sum(1 for j in judgments if j.carries_forward_error),
                "consigne_respected": consigne_respected,
            },
        )

        return CriterionEvaluationResult(
            criterion_id=crit.criterion_id,
            correction_mode=CorrectionMode.SOLUTION_WORKED,
            is_satisfied=is_satisfied,
            score_ratio=score_ratio,
            step_judgments=judgments,
            consigne_respected=consigne_respected,
            justification=justification,
            confidence_score=0.9,
            decision_log=log,
        )

    @staticmethod
    def _parse_student_step_judgments(
        parsed: _SolutionWorkedSchema, reference_steps: list[dict],
    ) -> list[SolutionWorkedStepJudgment]:
        """
        Garde-fou anti-hallucination : depends_on_refs et
        aligned_reference_step_ref ne sont retenus que s'ils pointent vers
        un step_ref réellement présent (étudiant ou référence respectivement)
        — jamais une référence inventée par le LLM propagée telle quelle.
        """
        raw_steps = parsed.student_steps
        known_student_refs = {s.step_ref for s in raw_steps if s.step_ref}
        known_reference_refs = {s.get("step_ref") for s in reference_steps if s.get("step_ref")}

        judgments: list[SolutionWorkedStepJudgment] = []
        for s in raw_steps:
            step_ref = s.step_ref
            if not step_ref:
                continue
            aligned = s.aligned_reference_step_ref
            if aligned not in known_reference_refs:
                aligned = None
            judgments.append(
                SolutionWorkedStepJudgment(
                    step_ref=step_ref,
                    order=s.order,
                    description=s.description,
                    justification=s.justification,
                    depends_on_refs=[r for r in s.depends_on_refs if r in known_student_refs],
                    aligned_reference_step_ref=aligned,
                    is_locally_correct=s.is_locally_correct,
                )
            )
        judgments.sort(key=lambda j: j.order)
        return judgments

    @staticmethod
    def _compute_downstream_refs(judgments: list[SolutionWorkedStepJudgment]) -> None:
        """
        downstream_step_refs calculé LOCALEMENT : Reasoning_Graph_Agent ne
        traite jamais les réponses d'étudiants (scopé exclusivement aux
        SolutionVariant), donc pas question de lui déléguer ce calcul.
        Même algorithme que lui (networkx.descendants sur un DiGraph
        construit depuis depends_on_refs) — dupliqué ici faute de
        bibliothèque partagée existante à ce jour (cf. docstring module).
        """
        graph = nx.DiGraph()
        for j in judgments:
            graph.add_node(j.step_ref)
        for j in judgments:
            for dep in j.depends_on_refs:
                graph.add_edge(dep, j.step_ref)

        for j in judgments:
            j.downstream_step_refs = sorted(nx.descendants(graph, j.step_ref))

    @staticmethod
    def _propagate_carries_forward_error(judgments: list[SolutionWorkedStepJudgment]) -> None:
        """
        Erreur reportée : toute étape is_locally_correct=True qui figure
        dans downstream_step_refs d'une étape is_locally_correct=False est
        marquée carries_forward_error=True. Elle n'est pas une nouvelle
        erreur indépendante — l'origine reste l'étape en amont, jamais
        pénalisée deux fois.
        """
        by_ref = {j.step_ref: j for j in judgments}
        for origin in judgments:
            if origin.is_locally_correct:
                continue
            for downstream_ref in origin.downstream_step_refs:
                downstream = by_ref.get(downstream_ref)
                if downstream is not None and downstream.is_locally_correct:
                    downstream.carries_forward_error = True

    @staticmethod
    def _check_final_equivalence(
        student_final_value: str | None,
        reference_steps: list[dict],
    ) -> bool | None:
        """
        Équivalence déterministe via canonical_form : réutilisé TEL QUEL
        côté référence (jamais recalculé — déjà produit par
        Extraction_Verification_Agent en amont), calculé côté étudiant via
        la MÊME fonction pure (ExtractionVerificationAgent.
        _compute_canonical_form — réutilisation directe d'une fonction
        existante, pas une duplication de logique sympy).

        numeric_tolerance n'est volontairement PAS parsé ici : texte libre
        non normalisé (ex. "± 5%", "3 chiffres significatifs"), dont
        l'interprétation algorithmique est déjà documentée ailleurs dans ce
        codebase comme une décision produit différée — jamais inventée ici.
        Le jugement LLM sur l'étape finale (qui reçoit ce texte en contexte,
        cf. prompt) reste seul applicable dans ce cas.

        None si aucune comparaison déterministe n'est possible (canonical_
        form de référence absent, ou valeur étudiante non fournie/non
        parsable par sympy) — jamais une supposition à la place.
        """
        if not student_final_value:
            return None

        reference_conclusion = next(
            (
                s for s in reference_steps
                if str(s.get("step_type")) == "conclusion" and s.get("canonical_form")
            ),
            None,
        )
        if reference_conclusion is None:
            return None

        student_canonical = ExtractionVerificationAgent._compute_canonical_form(student_final_value)
        if student_canonical is None:
            return None

        return student_canonical == reference_conclusion["canonical_form"]

    # -----------------------------------------------------------------------
    # 2. Mode CRITERIA_BASED
    # -----------------------------------------------------------------------
    async def _eval_criteria_based(
        self,
        crit: CriterionEvaluationInput,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> CriterionEvaluationResult:
        """
        Évaluation atomique des verifiable_conditions.
        Garde-fou anti-biais : Aucune réponse modèle narrative n'est générée.
        """
        conditions = crit.verifiable_conditions
        if not conditions:
            justification = "Aucune condition vérifiable fournie pour le critère CRITERIA_BASED."
            log = self._create_decision_log(
                request=request, mode=CorrectionMode.CRITERIA_BASED,
                justification=justification, confidence=1.0,
                output_summary={"score_ratio": 1.0, "condition_count": 0},
            )
            return CriterionEvaluationResult(
                criterion_id=crit.criterion_id,
                correction_mode=CorrectionMode.CRITERIA_BASED,
                is_satisfied=True,
                score_ratio=1.0,
                justification=justification,
                confidence_score=1.0,
                decision_log=log,
            )

        user_prompt = CRITERIA_BASED_USER_TEMPLATE.format(
            question_statement=request.question_statement,
            student_answer=request.student_response.student_answer_text,
            verifiable_conditions_json=json.dumps(conditions, ensure_ascii=False),
        )

        parsed, model_version = await self._call_llm_json(
            system_prompt=CRITERIA_BASED_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            ctx=ctx,
            response_schema=_CriteriaBasedSchema,
            general_rules=request.general_rules,
        )

        cond_evals: list[ConditionEvaluation] = []
        satisfied_count = 0

        for cond in parsed.condition_evaluations:
            sat = cond.satisfied
            if sat:
                satisfied_count += 1
            cond_evals.append(
                ConditionEvaluation(
                    condition_text=cond.condition_text,
                    satisfied=sat,
                    justification=cond.justification,
                    confidence=cond.confidence,
                )
            )

        score_ratio = round(satisfied_count / len(conditions), 2) if conditions else 1.0
        overall_justification = parsed.overall_justification or f"{satisfied_count}/{len(conditions)} conditions satisfaites."

        log = self._create_decision_log(
            request=request,
            mode=CorrectionMode.CRITERIA_BASED,
            justification=overall_justification,
            confidence=0.92,
            model_version=model_version,
            output_summary={
                "satisfied_conditions": satisfied_count,
                "total_conditions": len(conditions),
                "score_ratio": score_ratio,
            },
        )

        return CriterionEvaluationResult(
            criterion_id=crit.criterion_id,
            correction_mode=CorrectionMode.CRITERIA_BASED,
            is_satisfied=(score_ratio == 1.0),
            score_ratio=score_ratio,
            condition_evaluations=cond_evals,
            justification=overall_justification,
            confidence_score=0.92,
            decision_log=log,
        )

    # -----------------------------------------------------------------------
    # 3. Mode BINARY_CHECKLIST
    # -----------------------------------------------------------------------
    async def _eval_binary_checklist(
        self,
        crit: CriterionEvaluationInput,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> CriterionEvaluationResult:
        """
        Verdict strictement booléen par critère (présence/absence stricte).

        Bug trouvé sur test réel le 2026-08-18 : cette méthode déléguait
        auparavant à _eval_criteria_based, qui a un repli légitime ("aucune
        condition vérifiable -> satisfait par défaut") — MAIS verifiable_
        conditions est TOUJOURS vide pour BINARY_CHECKLIST par garde-fou
        anti-biais déterministe côté Extraction_Verification_Agent (réservé
        à CRITERIA_BASED, cf. son docstring module) — donc ce mode tombait
        SYSTÉMATIQUEMENT dans ce repli et validait n'importe quelle copie
        sans jamais la lire (confirmé : 2 critères binary_checklist réels,
        tous deux "SATISFAIT" avec la même justification générique, alors
        que l'un contredisait directement un autre critère ET une sous-
        question du MÊME rapport qui, eux, avaient correctement détecté
        l'absence du schéma demandé). Décalage de contrat entre les deux
        agents, pas un hasard du LLM.

        Jugement LLM propre à ce mode désormais (BINARY_CHECKLIST_*), ancré
        sur le label du critère ET le texte réel de la réponse — jamais une
        présomption de présence pour un élément non mentionné.
        """
        user_prompt = BINARY_CHECKLIST_USER_TEMPLATE.format(
            question_statement=request.question_statement,
            criterion_label=crit.label,
            student_answer=request.student_response.student_answer_text,
        )
        parsed, model_version = await self._call_llm_json(
            system_prompt=BINARY_CHECKLIST_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            ctx=ctx,
            response_schema=_BinaryChecklistSchema,
            general_rules=request.general_rules,
        )

        satisfied = parsed.satisfied
        final_score = 1.0 if satisfied else 0.0
        justification = parsed.justification or (
            f"BINARY_CHECKLIST : Verdict strict = {'SATISFAIT' if satisfied else 'NON SATISFAIT'}."
        )

        log = self._create_decision_log(
            request=request,
            mode=CorrectionMode.BINARY_CHECKLIST,
            justification=justification,
            confidence=0.95,
            model_version=model_version,
            output_summary={"is_satisfied": satisfied, "score_ratio": final_score},
        )

        return CriterionEvaluationResult(
            criterion_id=crit.criterion_id,
            correction_mode=CorrectionMode.BINARY_CHECKLIST,
            is_satisfied=satisfied,
            score_ratio=final_score,
            justification=justification,
            confidence_score=0.95,
            decision_log=log,
        )

    # -----------------------------------------------------------------------
    # 4. Mode MULTIPLE_DISTINCT_ANSWERS
    # -----------------------------------------------------------------------
    async def _eval_multiple_distinct_answers(
        self,
        crit: CriterionEvaluationInput,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> CriterionEvaluationResult:
        """
        Recherche RAG sémantique + filtre de cohérence à 3 statuts (Bug 3) :
        COHERENT + match RAG -> validé. COHERENT + aucun match -> clarification
        HITL (réponse alternative possible). INCOHERENT -> incorrect, sans
        clarification. AMBIGUOUS_COHERENCE -> ne déclenche JAMAIS ni la
        génération ni un rejet automatique (cf. _classify_coherence) : la
        recherche RAG est même sautée (pas de raison de chercher une réponse
        validée pour un texte dont on n'est pas sûr qu'il soit un effort de
        réponse sensé), et un ClarificationRequest BLOCKING est créé.
        """
        student_text = request.student_response.student_answer_text.strip()
        clarification_req: ClarificationRequest | None = None
        is_matched = False
        score_ratio = 0.0

        # 1. Filtre de cohérence à 3 statuts (Bug 3) — score continu produit
        #    par le LLM, seuillage déterministe fait ici en code. Correctif
        #    AMBIGUOUS_COHERENCE : si le professeur a déjà tranché ce critère
        #    (resolution forcée), l'appel LLM est SAUTÉ — sa décision est
        #    désormais autoritaire pour ce (question, critère), jamais
        #    redemandée au LLM qui pourrait reproduire la même ambiguïté.
        forced_resolution = request.coherence_ambiguity_resolutions.get(crit.criterion_id)
        if forced_resolution is not None:
            coherence_status = (
                CoherenceStatus.COHERENT if forced_resolution == "coherent"
                else CoherenceStatus.INCOHERENT
            )
            coherence_score = 1.0 if forced_resolution == "coherent" else 0.0
            coherence_model_version = "resolved_by_professor"
        else:
            coherence_prompt = COHERENCE_CHECK_USER_TEMPLATE.format(
                question_statement=request.question_statement,
                student_answer=student_text,
            )
            parsed_coh, coherence_model_version = await self._call_llm_json(
                system_prompt=COHERENCE_CHECK_SYSTEM_PROMPT,
                user_prompt=coherence_prompt,
                ctx=ctx,
                response_schema=_CoherenceCheckSchema,
                general_rules=request.general_rules,
            )
            coherence_score = parsed_coh.coherence_score
            coherence_status = self._classify_coherence(coherence_score)

        # 2. Recherche RAG uniquement si franchement cohérent — jamais en
        #    zone d'ambiguïté (cf. docstring ci-dessus).
        #
        # Câblage Priorité 3 — cible validated_alternative_answers (réponses
        # d'étudiants validées par un professeur), PAS reasoning_clarification_
        # requests (mécanisme few-shot §10ter de Reasoning_Graph_Agent,
        # embedding calculé sur la QUESTION posée par l'agent, jamais une
        # réponse d'étudiant — cf. docstring ValidatedAlternativeAnswer pour
        # la justification complète du choix d'une table dédiée plutôt que
        # ComparativeEvaluationPattern, structurellement inadaptée). Filtrée
        # par question_id ET criterion_id via filter_params (jamais
        # interpolés dans filter_clauses, cf. rag_repository.search_similar)
        # — une réponse alternative validée sur une AUTRE question ou un
        # AUTRE critère ne doit jamais matcher ici.
        rag_matches = []
        if coherence_status == CoherenceStatus.COHERENT and ctx.db_session is not None:
            from app.core.embeddings import embed_text
            query_vec = embed_text(student_text)
            if query_vec:
                try:
                    rag_matches = await search_similar(
                        session=ctx.db_session,
                        embedding_query=query_vec,
                        table_name="validated_alternative_answers",
                        embedding_column="embedding",
                        id_column="id",
                        payload_columns=["answer_text", "validated_by_professor_id"],
                        filter_clauses="question_id = :question_id AND criterion_id = :criterion_id",
                        filter_params={
                            "question_id": str(request.question_id),
                            "criterion_id": crit.criterion_id,
                        },
                        top_k=1,
                        similarity_threshold=0.85,
                    )
                except Exception as exc:
                    logger.warning("[Comparative_Evaluation_Agent] Erreur RAG search: %s", exc)

        if coherence_status == CoherenceStatus.AMBIGUOUS_COHERENCE:
            # Bug 3 — jamais un verdict tranché en zone d'incertitude (§0) :
            # ni validé, ni rejeté, une clarification BLOCKING route la
            # décision vers le professeur (aucune consommation en aval tant
            # qu'elle n'est pas résolue, même sémantique que les autres
            # BLOCKING de ce codebase — cf. docstring module).
            clarification_req = ClarificationRequest(
                related_field=f"criterion[{crit.criterion_id}].multiple_distinct_answers",
                agent_question=(
                    f"La cohérence de la réponse de l'étudiant à la question "
                    f"'{request.question_statement[:60]}...' est ambiguë (score={coherence_score:.2f}) : "
                    f"'{student_text[:150]}'. S'agit-il d'un effort de réponse valide à examiner, "
                    f"ou d'une réponse hors-sujet à rejeter ?"
                ),
                proposed_answer=None,
                severity=ClarificationSeverity.BLOCKING,
            )
            justification = (
                f"MULTIPLE_DISTINCT_ANSWERS : Cohérence ambiguë (score={coherence_score:.2f}) -> "
                f"aucun verdict automatique, demande de clarification créée."
            )
        elif rag_matches:
            is_matched = True
            score_ratio = 1.0
            justification = f"MULTIPLE_DISTINCT_ANSWERS : Réponse validée via RAG (similarité={rag_matches[0].similarity:.3f})."
        elif coherence_status == CoherenceStatus.COHERENT:
            # Réponse cohérente mais aucune correspondance RAG validée -> HITL Clarification
            clarification_req = ClarificationRequest(
                related_field=f"criterion[{crit.criterion_id}].multiple_distinct_answers",
                agent_question=(
                    f"Une réponse alternative inédite a été proposée pour la question '{request.question_statement[:60]}...' : "
                    f"'{student_text[:150]}'. Est-elle valide ?"
                ),
                proposed_answer="Valider cette réponse alternative comme correcte.",
                severity=ClarificationSeverity.BLOCKING,
            )
            justification = "MULTIPLE_DISTINCT_ANSWERS : Réponse alternative inédite et cohérente -> Demande de clarification créée."
        else:
            justification = "MULTIPLE_DISTINCT_ANSWERS : Réponse incohérente ou hors-sujet -> Traitée comme incorrecte."

        log = self._create_decision_log(
            request=request,
            mode=CorrectionMode.MULTIPLE_DISTINCT_ANSWERS,
            justification=justification,
            confidence=0.90,
            model_version=coherence_model_version,
            tools_consulted=[{"type": "rag_search", "matches_found": len(rag_matches)}],
            output_summary={
                "coherence_status": coherence_status.value,
                "coherence_score": coherence_score,
                "rag_matched": bool(rag_matches),
                "clarification_created": bool(clarification_req),
            },
        )

        return CriterionEvaluationResult(
            criterion_id=crit.criterion_id,
            correction_mode=CorrectionMode.MULTIPLE_DISTINCT_ANSWERS,
            is_satisfied=is_matched,
            score_ratio=score_ratio,
            clarification_request=clarification_req,
            coherence_status=coherence_status,
            justification=justification,
            confidence_score=0.90,
            decision_log=log,
        )

    @classmethod
    def _classify_coherence(cls, coherence_score: float) -> CoherenceStatus:
        """
        Bug 3 — seuillage déterministe à 2 seuils (jamais un booléen) :
        >= _COHERENCE_HIGH_THRESHOLD -> COHERENT, < _COHERENCE_LOW_THRESHOLD
        -> INCOHERENT, entre les deux -> AMBIGUOUS_COHERENCE. Seuils
        empiriques par défaut (même statut de calibration que
        rag_repository.similarity_threshold) — à ajuster après observation
        de résultats réels, hors périmètre de ce ticket.
        """
        if coherence_score >= cls._COHERENCE_HIGH_THRESHOLD:
            return CoherenceStatus.COHERENT
        if coherence_score < cls._COHERENCE_LOW_THRESHOLD:
            return CoherenceStatus.INCOHERENT
        return CoherenceStatus.AMBIGUOUS_COHERENCE

    # -----------------------------------------------------------------------
    # 5. Mode RUBRIC_LEVELS
    # -----------------------------------------------------------------------
    async def _eval_rubric_levels(
        self,
        crit: CriterionEvaluationInput,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> CriterionEvaluationResult:
        """
        Classification ancrée exclusivement sur les descriptions textuelles du professeur.

        Calcul de note classique (2026-08-18) — score_ratio est désormais
        DÉTERMINISTE, jamais redemandé au LLM : seule l'information d'échelle
        disponible est l'ORDRE de crit.rubric_levels tel que fourni par le
        professeur (pas de poids numérique explicite), donc la position du
        niveau assigné dans cette liste est répartie linéairement sur
        [0.0, 1.0] (index 0 = meilleur niveau -> 1.0). La conversion
        score_ratio -> points reste hors de cet agent (rôle de Pedagogical_
        Evaluation_Agent).
        """
        levels = crit.rubric_levels
        user_prompt = RUBRIC_LEVELS_USER_TEMPLATE.format(
            question_statement=request.question_statement,
            student_answer=request.student_response.student_answer_text,
            rubric_levels_json=json.dumps(levels, ensure_ascii=False),
        )

        parsed, model_version = await self._call_llm_json(
            system_prompt=RUBRIC_LEVELS_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            ctx=ctx,
            response_schema=_RubricLevelsSchema,
            general_rules=request.general_rules,
        )

        assigned_level = parsed.assigned_level or "Insuffisant"
        justification = parsed.justification or f"Réponse classée dans le niveau {assigned_level}."

        level_index = self._find_rubric_level_index(levels, assigned_level)
        if level_index is None:
            # Ne devrait jamais arriver vu le schéma structuré (assigned_level
            # est censé provenir de rubric_levels), mais defensive : jamais un
            # niveau deviné, score_ratio neutre à 0.0, signalé pour audit.
            logger.warning(
                "[%s] RUBRIC_LEVELS : niveau assigné '%s' introuvable dans "
                "rubric_levels du critère %s -- score_ratio=0.0.",
                self.AGENT_NAME, assigned_level, crit.criterion_id,
            )
            score_ratio = 0.0
        elif len(levels) <= 1:
            # Cas dégénéré (0 ou 1 niveau fourni) : le seul niveau possible,
            # une fois assigné, vaut le maximum -- pas de formule linéaire
            # applicable sur une échelle à un seul point.
            score_ratio = 1.0
        else:
            score_ratio = 1.0 - (level_index / (len(levels) - 1))

        log = self._create_decision_log(
            request=request,
            mode=CorrectionMode.RUBRIC_LEVELS,
            justification=justification,
            confidence=0.91,
            model_version=model_version,
            output_summary={"assigned_level": assigned_level, "score_ratio": score_ratio},
        )

        return CriterionEvaluationResult(
            criterion_id=crit.criterion_id,
            correction_mode=CorrectionMode.RUBRIC_LEVELS,
            is_satisfied=(score_ratio == 1.0),
            score_ratio=score_ratio,
            assigned_level=assigned_level,
            justification=justification,
            confidence_score=0.91,
            decision_log=log,
        )

    @staticmethod
    def _find_rubric_level_index(levels: list[dict], assigned_level: str) -> int | None:
        """
        Localise assigned_level dans rubric_levels par correspondance de
        "level" — comparaison stricte d'abord, puis insensible à la
        casse/espaces en repli. Jamais un matching flou (fuzzy) : c'est une
        liste fermée et courte fournie par le professeur.
        """
        for i, lvl in enumerate(levels):
            if lvl.get("level") == assigned_level:
                return i
        normalized = assigned_level.strip().casefold()
        for i, lvl in enumerate(levels):
            if str(lvl.get("level", "")).strip().casefold() == normalized:
                return i
        return None

    # -----------------------------------------------------------------------
    # 6. Mode PROCEDURAL_SEQUENCE
    # -----------------------------------------------------------------------
    async def _eval_procedural_sequence(
        self,
        crit: CriterionEvaluationInput,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> CriterionEvaluationResult:
        """
        Deux signaux distincts :
        1. step_presence : Présence/absence des étapes.
        2. sequence_ordering : Respect de l'ordre entre les étapes présentes.
        """
        expected_steps = crit.expected_steps
        user_prompt = PROCEDURAL_SEQUENCE_USER_TEMPLATE.format(
            question_statement=request.question_statement,
            student_answer=request.student_response.student_answer_text,
            expected_steps_json=json.dumps(expected_steps, ensure_ascii=False),
        )

        parsed, model_version = await self._call_llm_json(
            system_prompt=PROCEDURAL_SEQUENCE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            ctx=ctx,
            response_schema=_ProceduralSequenceSchema,
            general_rules=request.general_rules,
        )

        step_presences: list[StepPresenceEvaluation] = []
        for sp in parsed.step_presence:
            step_presences.append(
                StepPresenceEvaluation(
                    step_name=sp.step_name,
                    present=sp.present,
                    justification=sp.justification,
                )
            )

        seq = parsed.sequence_ordering
        seq_ordering = SequenceOrderingEvaluation(
            is_order_correct=seq.is_order_correct,
            misplaced_steps=seq.misplaced_steps,
            justification=seq.justification,
        )

        present_count = sum(1 for p in step_presences if p.present)
        justification = (
            f"PROCEDURAL_SEQUENCE : {present_count}/{len(expected_steps)} étapes présentes. "
            f"Ordre : {'CORRECT' if seq_ordering.is_order_correct else 'INCORRECT'}"
        )

        # Calcul de note classique (2026-08-18) — score_ratio DÉTERMINISTE,
        # jamais redemandé au LLM. presence_ratio seul si l'ordre est
        # respecté ; sinon pénalité MULTIPLICATIVE (pas un score écrasé à
        # 0.0) : ce mode ("l'ordre compte en lui-même, protocole/algorithme")
        # ne peut pas ignorer un ordre incorrect, mais une réponse complète
        # mal ordonnée reste supérieure à une réponse incomplète.
        presence_ratio = round(present_count / len(expected_steps), 2) if expected_steps else 0.0
        score_ratio = presence_ratio if seq_ordering.is_order_correct else round(presence_ratio * 0.5, 2)

        log = self._create_decision_log(
            request=request,
            mode=CorrectionMode.PROCEDURAL_SEQUENCE,
            justification=justification,
            confidence=0.92,
            model_version=model_version,
            output_summary={
                "present_steps": present_count,
                "total_steps": len(expected_steps),
                "is_order_correct": seq_ordering.is_order_correct,
                "misplaced_steps": seq_ordering.misplaced_steps,
                "score_ratio": score_ratio,
            },
        )

        return CriterionEvaluationResult(
            criterion_id=crit.criterion_id,
            correction_mode=CorrectionMode.PROCEDURAL_SEQUENCE,
            is_satisfied=(score_ratio == 1.0),
            score_ratio=score_ratio,
            step_presence=step_presences,
            sequence_ordering=seq_ordering,
            justification=justification,
            confidence_score=0.92,
            decision_log=log,
        )

    # -----------------------------------------------------------------------
    # 7. Mode TEST_CASE_BASED
    # -----------------------------------------------------------------------
    async def _eval_test_case_based(
        self,
        crit: CriterionEvaluationInput,
        request: EvaluationRequest,
        ctx: AgentExecutionContext,
    ) -> CriterionEvaluationResult:
        """
        Délégation à Judge0SandboxService (isolé).
        Separe visible vs hidden test cases.
        Consigne l'indication explicite mock vs judge0_remote vs sandbox_local dans tools_consulted.
        """
        student_code = request.student_response.code_submission or request.student_response.student_answer_text
        test_cases = crit.test_cases or []

        exec_mode, test_results = await self._sandbox_service.execute_test_cases(
            source_code=student_code,
            language="python",
            test_cases=test_cases,
        )

        visible_results = [r for r in test_results if r.visibility == "visible"]
        hidden_results = [r for r in test_results if r.visibility == "hidden"]

        total_passed = sum(1 for r in test_results if r.passed)
        total_cases = len(test_results)
        score_ratio = round(total_passed / total_cases, 2) if total_cases > 0 else 0.0

        # Signal informatif de complexité
        observed_comp = crit.expected_complexity or "O(1)"

        justification = (
            f"TEST_CASE_BASED ({exec_mode}) : {total_passed}/{total_cases} cas de test réussis "
            f"(Visibles: {sum(1 for r in visible_results if r.passed)}/{len(visible_results)}, "
            f"Cachés: {sum(1 for r in hidden_results if r.passed)}/{len(hidden_results)})."
        )

        # Log de décision incluant L'INDICATION EXPLICITE du mode d'exécution
        # (mock vs judge0_remote vs sandbox_local) — confiance haute pour
        # toute exécution RÉELLE (judge0_remote ET sandbox_local, le code
        # étudiant a vraiment tourné dans les deux cas), basse uniquement
        # pour le mock (simulation par pattern-matching, cf. Judge0SandboxService).
        log = self._create_decision_log(
            request=request,
            mode=CorrectionMode.TEST_CASE_BASED,
            justification=justification,
            confidence=0.99 if exec_mode != "mock" else 0.90,
            tools_consulted=[
                {
                    "type": "sandbox_execution",
                    "execution_mode": exec_mode,  # "mock" ou "judge0_remote" ou "sandbox_local"
                    "visible_passed": sum(1 for r in visible_results if r.passed),
                    "visible_total": len(visible_results),
                    "hidden_passed": sum(1 for r in hidden_results if r.passed),
                    "hidden_total": len(hidden_results),
                }
            ],
            output_summary={
                "execution_mode": exec_mode,
                "score_ratio": score_ratio,
                "observed_complexity": observed_comp,
            },
        )

        return CriterionEvaluationResult(
            criterion_id=crit.criterion_id,
            correction_mode=CorrectionMode.TEST_CASE_BASED,
            is_satisfied=(score_ratio == 1.0),
            score_ratio=score_ratio,
            test_case_results=test_results,
            execution_mode=exec_mode,
            observed_complexity=observed_comp,
            justification=justification,
            confidence_score=0.99 if exec_mode != "mock" else 0.90,
            decision_log=log,
        )

    # -----------------------------------------------------------------------
    # Helper AgentDecisionLog
    # -----------------------------------------------------------------------
    def _create_decision_log(
        self,
        request: EvaluationRequest,
        mode: CorrectionMode,
        justification: str,
        confidence: float,
        model_version: str = "comparative_eval:v1",
        tools_consulted: list | None = None,
        output_summary: dict | None = None,
    ) -> AgentDecisionLog:
        return AgentDecisionLog(
            agent_name=self.AGENT_NAME,
            related_entity_type="Question",
            related_entity_id=request.question_id,
            justification=f"[{mode.value}] {justification}",
            confidence_score=Decimal(str(round(confidence, 3))),
            model_version=model_version,
            input_summary=json.dumps({"mode": mode.value, "student_answer_len": len(request.student_response.student_answer_text)}),
            output_summary=json.dumps(output_summary or {}),
            tools_consulted=tools_consulted or [],
        )
