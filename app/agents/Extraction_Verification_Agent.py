"""
Agent — Extraction_Verification_Agent, noyau + taxonomie des modes + patterns
structurels scientifiques + outils déterministes + clarifications + méthode
imposée + mode informatique (Phases 1-5/6).

S'exécute après Document_Structuring_Agent, sur des Question déjà créées
avec leur correction déjà rattachée (TeacherCorrectionBlock.question_id
résolu). Ne juge jamais la qualité pédagogique de la réponse.

Produit, par question :
  1. Une décomposition ordonnée en étapes (donnée/formule/calcul/résultat
     intermédiaire/conclusion), la dernière étape étant toujours la
     conclusion — jamais une étape inventée pour combler un manque perçu.
  2. Un Bareme sur les 4 critères classiques (exactitude/cohérence/
     complétude/justification), selon 3 cas (§2) :
       Cas 1 DETAILED       — barème détaillé, rattachement par critère.
       Cas 2 GLOBAL_PROPOSED — un seul total, répartition proposée
                                (jamais appliquée automatiquement).
       Cas 3                — aucun chiffre nulle part : MissingBaremeError,
                                blocage strict, jamais de formulaire.
  3. (Phase 2, §2bis) Pour chaque critère du barème, un correction_mode
     parmi 7 valeurs (CorrectionMode) — comment CE critère précis doit être
     vérifié, indépendamment des autres critères de la même question.
  4. (Phase 3a, §2ter) Patterns structurels scientifiques détectés pendant
     la décomposition/le barème — signal seulement, jamais d'exécution :
       - CASE_SPLIT (step_type) + case_group_id : raisonnement par cas
         disjoints, branches à couvrir ensemble.
       - recurrence_role (initialization/induction/conclusion) : structure
         de récurrence à 3 parties, garde déterministe si incomplète.
       - disqualifying (critère) : invalide tous les points, peu importe
         le reste (ex. protocole de sécurité).
       - involves_graph_plot (question) : signale un graphique impliqué,
         aucune structure de représentation ici.
     QCM + justification restent toujours deux critères distincts, jamais
     fusionnés (règle de prompt uniquement, aucun champ dédié).
  5. (Phase 3b, §2ter) Outils déterministes, post-traitement pur, jamais un
     jugement LLM :
       - INVERSE_SOLVE (step_type) : contrainte posée puis inconnue isolée.
       - canonical_form (étape CONCLUSION) : forme canonique via sympy —
         tente sympify/simplify (notation standard, gère aussi une égalité
         simple "A = L*l" via sympy.Eq), puis en repli latex2sympy2_extended
         (notation LaTeX, ex. "P = 28 \\text{ kN}") — PAS sympy.parsing.
         latex.parse_latex : ce dernier exige exactement antlr4-python3-
         runtime 4.11.x (contrôle de version en dur dans sympy 1.14),
         incompatible avec la 4.13.2 déjà résolue dans ce venv par d'autres
         paquets (latex2sympy2/latex2sympy2_extended, déjà présents, qui
         eux embarquent leur propre grammaire ANTLR 4.13.2 — cf. requirements.
         txt). Une formule qui échoue aux deux tentatives retourne None,
         silencieusement, comme tout échec de parsing.
       - dimensional_check_result (étape COMPUTATION) : vérification
         dimensionnelle via pint sur une égalité extraite de formula/
         description, après normalisation bornée du bruit LaTeX courant
         (\\text{}, \\frac{}{}, \\cdot/\\times, virgule décimale française —
         cf. _normalize_latex_for_units). "not_checkable" si aucune unité
         n'est extractible — ce résultat couvre déjà "non pertinent ici"
         (formule purement symbolique, sans unité littérale des deux côtés),
         donc aucun champ requires_dimensional_check séparé. Limite connue :
         pint peut interpréter un symbole algébrique isolé comme une unité
         (ex. "A" = ampère, "P" = poise) — signal non bloquant, jamais une
         vérité absolue.
       - numeric_tolerance (étape CONCLUSION, LLM) : marge explicite du
         professeur ("± 5%", "3 chiffres significatifs"), None sinon —
         AUCUNE valeur par défaut arbitraire codée en dur (décision produit
         à trancher séparément, hors périmètre ici).
       - criticality (étape COMPUTATION, LLM) : "conceptual"/"routine",
         optionnel, jamais forcé.
       - depends_on_question_order (question) : détection hybride
         regex+rapidfuzz de références croisées explicites entre questions
         ("d'après (2)", "voir question précédente") — marqueur textuel
         SEULEMENT dans cette phase, aucun appel LLM de secours (extension
         future si nécessaire). Passe préliminaire sur l'ensemble de
         `questions`, avant la boucle par question (propriété structurelle,
         ne dépend d'aucun résultat de décomposition/barème).
  6. (Phase 4, §2quater) Formalisation, PAS une nouvelle détection : chaque
     signal d'incertitude déjà produit par les phases 1/2/3a/3b devient une
     ClarificationRequest (related_field, agent_question déterministe —
     jamais un appel LLM de plus —, proposed_answer optionnel, severity) :
       - Barème Cas 2 (GLOBAL_PROPOSED)         -> BLOCKING.
       - Récurrence incomplète (Phase 3a)       -> BLOCKING.
       - Anomalie de calcul isolée, hors récurrence (Phase 1) -> WARNING.
       - Échec sympy (canonical_form=None) / échec pint (not_checkable) sur
         une formule/égalité réellement présente (Phase 3b)   -> INFORMATIONAL.
     Principe non négociable, en CODE (pas seulement documenté) : rien de
     severity=BLOCKING n'est jamais traité comme acquis ici — l'agent
     propose/signale, il ne décide jamais à la place du professeur. Le
     verrou de validation effectif est hors périmètre (persistance).
     Candidats identifiés en relecture mais volontairement NON formalisés
     ici (pas dans le périmètre demandé, à confirmer séparément) :
     decomposition_error/bareme_error (déjà des échecs bloquants, pas des
     propositions à valider) ; disqualifying=True ; involves_graph_plot ;
     depends_on_question_order ; numeric_tolerance manquant.
  7. (Phase 5, §2quinquies) Deux ajouts indépendants, formalisation/extraction
     pure, jamais une nouvelle décision pédagogique :
       A. mandated_method (question, LLM, même appel que la décomposition) :
          méthode/algorithme/outil EXPLICITEMENT imposé par l'énoncé et/ou
          la correction ("utilisez...", "à l'aide de...", "par la méthode
          de..."). None si aucun marqueur d'obligation — jamais déduit du
          simple fait que la correction utilise une méthode (ça ne veut pas
          dire qu'elle est imposée, juste que c'est celle choisie par le
          prof). Consommé plus tard par Solution_Variant_Generation_Agent
          (jamais de variante hors méthode imposée) et un futur
          Comparative_Evaluation_Agent (consigne_respected, séparé du score
          d'exactitude) — aucun des deux n'est implémenté ici.
       B. Mode TEST_CASE_BASED (critère, même appel barème) : TestCase
          (input/expected_output/visibility, défaut "visible" jamais "hidden"
          deviné), reference_code, expected_complexity (uniquement si
          explicitement mentionnée, jamais déduite du code) sur
          BaremeCriterionProposal — vides/None pour tout autre mode
          (garde-fou anti-biais en code, cf. _parse_criterion, même principe
          que verifiable_conditions/CRITERIA_BASED). Règle de séparation
          correctness/qualité ajoutée au prompt (même principe que QCM +
          justification, Phase 3a) : fonctionnement du code (test_case_based)
          et qualité du code (rubric_levels/criteria_based) restent toujours
          deux critères distincts. Aucune décomposition en étapes forcée sur
          du code pur (règle de prompt, la garde "liste vide plutôt
          qu'inventée" existante suffit). TEST_CASE_BASED détecté sans
          reference_code ni TestCase extractible (spécification purement
          textuelle) : formalisé en ClarificationRequest BLOCKING (cf.
          _build_test_case_based_incomplete_clarification) — contrairement à
          l'anomalie de calcul isolée, le mécanisme de notation automatique
          de ce critère n'a littéralement rien à exécuter tant que le
          professeur n'a pas fourni au moins un cas de test ou un code de
          référence ; ce n'est pas un détail secondaire mais l'incertitude
          porte sur la faisabilité même de la notation de ce critère.
       C. covered_subquestions (question, LLM, même appel que la
          décomposition — RÉVISÉ Phase 2/4, granularité sous-question) :
          liste des `id` des sous-questions officielles C2PCT (module
          app.domain.models.competency.c2pct_scaffold, 15 sous-questions
          au total, réparties de façon INÉGALE sur les 7 compétences)
          réellement couvertes — cherchées dans L'ÉNONCÉ ET LA CORRECTION,
          jamais un seul des deux textes. Extraction directe, jamais une
          proposition IA à valider par le prof, même logique stricte que le
          barème (Cas 1/2/3) : une sous-question est identifiable dans au
          moins un des deux textes, ou absente des deux. Aucune limite
          artificielle sur le nombre retenu (0 à 15 selon ce que les textes
          démontrent réellement) ; liste vide un résultat valide. Détection
          hybride, en parallèle (jamais l'un filtrant l'autre) :
            - Premier passage déterministe (_fuzzy_candidate_subquestions,
              rapidfuzz.fuzz.token_set_ratio, seuil 70) : utile UNIQUEMENT
              au cas où le prof fait écho explicitement au texte de la
              sous-question officielle. Un score faible/absent ne signifie
              RIEN sur l'absence réelle (couverture implicite possible,
              cf. ci-dessous) — jamais utilisé pour exclure, seulement
              transmis en indice au LLM dans le user prompt.
            - LLM (rôle principal) : reçoit les 15 reference_prompt comme
              des INTENTIONS à vérifier sur le fond, pas des textes à
              retrouver littéralement — détecte aussi bien une couverture
              EXPLICITE (écho au texte de la question) qu'IMPLICITE
              (réponse directe au contenu attendu, sans jamais reformuler
              la question), les deux réelles, aucune privilégiée par
              construction du prompt.
          Garde-fou anti-hallucination en code (comme pour l'ancien
          competencies_mobilized) : tout id hors des 15 valides du module
          de référence est rejeté individuellement, jamais un échec de
          schéma pour toute la décomposition.
          competencies_mobilized (C2PCTSkillCode, 7 codes) devient une
          propriété DÉRIVÉE de covered_subquestions (_derive_competencies_
          mobilized) — plus une extraction séparée par le LLM : une
          compétence est mobilisée si AU MOINS UNE de ses sous-questions
          officielles est couverte. Consommé plus tard par un futur
          Pedagogical_Evaluation_Agent (répartition du barème de la
          question entre les compétences dérivées ici, pas construit dans
          ce ticket).

Deux appels LLM séquentiels, jamais l'inverse : la décomposition est
TOUJOURS produite en premier (pour toute question), le barème Cas 2 s'appuie
explicitement dessus pour proposer une répartition plausible — jamais un
total/4 mécanique. Le rattachement montant→critère (Cas 1) passe aussi par
le LLM : un regex détecte fiablement qu'un montant existe, jamais à quel
critère il appartient (ça demande de comprendre le sens de la phrase). Seule
la détection Cas 3 (absence totale de chiffre) reste un regex pur.

La classification de correction_mode (Phase 2) est FUSIONNÉE dans le même
appel barème plutôt qu'un 3e appel séparé — même texte, même décomposition,
mêmes critères déjà en cours de production ; un appel de moins par question,
sans perte d'information. Auto-cohérence (§1bis) : reportée à une phase
ultérieure, un seul appel suffit pour cette phase (décision catégorielle à
7 valeurs, plus stable qu'une répartition numérique ; ajouter l'auto-
cohérence maintenant réintroduirait le coût que la fusion vient d'éliminer).

Garde-fou anti-biais CRITERIA_BASED : en plus de l'instruction de prompt,
un garde-fou déterministe en code (_parse_criterion) force
verifiable_conditions à [] pour tout mode différent de CRITERIA_BASED,
quoi que le LLM ait renvoyé.

Hors périmètre (tickets séparés à venir) : appel LLM de secours pour les
dépendances inter-questions sans marqueur textuel ; persistance dans ReasoningClarificationRequest (la table
réelle n'a ni severity ni proposed_answer — réconciliation pour un futur
service, ClarificationRequest ici reste une structure agent transitoire) ;
toute structure de représentation du graphique pour involves_graph_plot
(dépend d'un futur structure_type côté OCR_Extraction_Agent) ; valeur par
défaut pour numeric_tolerance (décision produit) ; écran de présentation
groupée des clarifications au professeur (interface) ; ClarificationRequest
pour disqualifying/involves_graph_plot/depends_on_question_order/
numeric_tolerance manquant (candidats identifiés, non tranchés, cf. §2quater
ci-dessus) ; consommation de mandated_method par Solution_Variant_Generation_
Agent/Comparative_Evaluation_Agent (agents futurs, cf. §7A) ; exécution
réelle du mode TEST_CASE_BASED — sandbox/Judge0 (agent futur), détection de
code qui ne compile pas côté élève (relève de Comparative_Evaluation_Agent,
cet agent-ci ne voit que la correction du prof, jamais une copie), crédit
partiel sur code non-fonctionnel.

Point de cohérence à vérifier plus tard (pas ici, ne bloque pas ce ticket) :
competencies_mobilized (§7C, désormais dérivé de covered_subquestions) et
les compétences à poids non-nul dans competency_weights (déjà produit par
Reasoning_Graph_Agent sur les étapes du graphe de la même correction)
devraient normalement converger — les deux mécanismes restent indépendants
pour l'instant (texte vs. graphe déjà construit), à recouper une fois
Pedagogical_Evaluation_Agent construit.

Aucune persistance ici (ni Bareme, ni ReasoningStep, ni AgentDecisionLog, ni
ReasoningClarificationRequest) — même principe que Document_Structuring_Agent/
Contestation_Verification_Agent : l'agent calcule, un futur service persiste.

2026-08-18 — trou de pipeline comblé (calcul de note classique, ticket dédié) :
BaremeCriterionProposal.rubric_levels/expected_steps. Jusqu'ici, RUBRIC_LEVELS
et PROCEDURAL_SEQUENCE étaient correctement CLASSÉS comme mode de correction,
mais la donnée réelle qu'ils nécessitent (grille de niveaux du professeur /
liste d'étapes attendues) n'était jamais extraite nulle part dans ce fichier
— Comparative_Evaluation_Agent recevait donc systématiquement une liste
vide, quel que soit le texte du barème. Même garde-fou anti-biais en code que
verifiable_conditions/test_cases (cf. _criterion_from_schema) : chaque champ
n'existe que pour son propre mode.
"""
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

import pint
import sympy
from latex2sympy2_extended.latex2sympy2 import ConversionConfig, latex2sympy
from latex2sympy2_extended.math_normalization import NormalizationConfig
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.agents.context import AgentExecutionContext
from app.agents.extraction_verification_exceptions import (
    BaremeExtractionSchemaError,
    DecompositionSchemaError,
    ExerciseAlreadyPublishedError,
    MissingBaremeError,
    ModeClassificationSchemaError,
)
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.assessment.reasoning_step import ReasoningStepType
from app.domain.models.assessment.teacher_correction_block import BlockEvidenceLevel
from app.domain.models.competency.c2pct_detection import fuzzy_candidate_subquestions
from app.domain.models.competency.c2pct_scaffold import (
    find_subquestion_by_id,
    get_all_subquestions,
    get_subquestions_for,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType
from app.observability.langfuse import AgentTraceSpan
from app.prompts.extraction_verification_prompt import (
    BAREME_SYSTEM_PROMPT,
    BAREME_USER_TEMPLATE,
    DECOMPOSITION_SYSTEM_PROMPT,
    DECOMPOSITION_USER_TEMPLATE,
    SUBQUESTION_POINTS_SYSTEM_PROMPT,
    SUBQUESTION_POINTS_USER_TEMPLATE,
    SUBQUESTION_SEGMENTATION_SYSTEM_PROMPT,
    SUBQUESTION_SEGMENTATION_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entrée / sortie (dataclasses internes — pas de Pydantic partagé service/
# agent à ce stade, aucun service n'existe encore ; même choix que
# Document_Structuring_Agent).
# ---------------------------------------------------------------------------

@dataclass
class QuestionInput:
    question_id: uuid.UUID
    order: int
    statement: str
    section_order: int | None = None


@dataclass
class CorrectionBlockInput:
    block_id: uuid.UUID
    content_type: ExtractionContentType
    raw_text: str | None = None
    structured_content: dict | None = None
    # Signal de confiance de rattachement posé par Document_Structuring_Agent
    # (cf. teacher_correction_block.py) — None si l'appelant ne le fournit
    # pas (ex. scripts de test agent-only). Jamais utilisé pour bloquer,
    # seulement pour signaler qu'une partie du texte source d'une question
    # a été rattachée par inférence de contenu plutôt qu'un label explicite,
    # cf. _build_low_confidence_attachment_clarification.
    evidence_level: BlockEvidenceLevel | None = None


@dataclass
class ReasoningStepOutput:
    # Forme volontairement compatible avec ReasoningStepCreate
    # (solution_schemas.py) / create_with_reasoning_graph
    # (solution_variant_repository.py) pour une future phase de
    # persistance — jamais appelé depuis cet agent.
    step_ref: str
    order: int
    step_type: ReasoningStepType
    description: str
    source_span: str  # extrait exact du texte source — jamais une étape inventée
    formula: str | None = None
    depends_on_refs: list[str] = field(default_factory=list)  # linéaire en phase 1
    anomaly_detected: bool = False
    anomaly_justification: str | None = None
    # §2ter — partagé par toutes les branches d'un même CASE_SPLIT, distinct
    # des variantes interchangeables (Solution_Variant_Generation_Agent, hors périmètre).
    case_group_id: str | None = None
    # §2ter — démonstration par récurrence, structure à 3 parties. Garde
    # déterministe : cf. _decompose_steps.
    recurrence_role: Literal["initialization", "induction", "conclusion"] | None = None
    # §2ter (Phase 3b) — étape CONCLUSION uniquement, calculé en Python via
    # sympy, jamais un jugement LLM. None si formula est absent/non standard
    # (pas de parsing LaTeX) — échec silencieux, jamais bloquant.
    canonical_form: str | None = None
    # §2ter (Phase 3b) — étape COMPUTATION uniquement, calculé en Python via
    # pint. None si non tenté (pas de formula/description exploitable),
    # "not_checkable" si tenté mais pas d'unité extractible.
    dimensional_check_result: Literal["consistent", "inconsistent", "not_checkable"] | None = None
    # §2ter (Phase 3b) — étape CONCLUSION, LLM. Aucune valeur par défaut
    # arbitraire : None si le professeur ne précise rien d'explicite.
    numeric_tolerance: str | None = None
    # §2ter (Phase 3b) — étape COMPUTATION, LLM, jamais forcé.
    criticality: Literal["conceptual", "routine"] | None = None


class ClarificationSeverity(StrEnum):
    """
    Phase 4 — formalise (n'invente jamais) un signal d'incertitude déjà
    produit par une phase précédente. BLOCKING : aucune consommation en aval
    sans validation explicite du professeur (verrou lui-même hors périmètre
    ici, c'est une persistance). WARNING : utilisable provisoirement, mais
    le professeur doit être alerté. INFORMATIONAL : simple trace, aucun
    impact sur la validité de la donnée.
    """
    BLOCKING = "blocking"
    WARNING = "warning"
    INFORMATIONAL = "informational"


@dataclass
class ClarificationRequest:
    """
    Forme volontairement compatible avec une future persistance dans
    ReasoningClarificationRequest (mécanisme polymorphe déjà existant pour
    Reasoning_Graph_Agent) — mais severity et proposed_answer n'existent pas
    encore sur ce modèle ORM ; réconciliation laissée à un futur service,
    hors périmètre ici (cf. module docstring).
    """
    related_field: str  # ex. "bareme.criteria", "steps[2].recurrence_role"
    agent_question: str  # formulée pour être lue directement par le professeur
    # Ce que l'agent propose, si applicable ; None si l'agent n'a aucune
    # proposition et se contente de signaler (ex. récurrence incomplète : on
    # ne peut pas inventer le rôle manquant).
    proposed_answer: str | None
    severity: ClarificationSeverity


@dataclass
class DecompositionResult:
    steps: list[ReasoningStepOutput]
    # §2ter — signal seulement, aucune structure de représentation du
    # graphique ici (dépend d'un futur structure_type côté OCR_Extraction_Agent).
    involves_graph_plot: bool = False
    # Phase 4 — clarifications formalisées pendant la décomposition (anomalie
    # de calcul isolée, récurrence incomplète, échecs sympy/pint) : cf.
    # _decompose_steps. Toujours produites ici, jamais dans execute().
    clarifications: list[ClarificationRequest] = field(default_factory=list)
    # Phase 5A (§2quinquies) — méthode/algorithme/outil EXPLICITEMENT imposé
    # par l'énoncé et/ou la correction ("utilisez...", "à l'aide de...") ;
    # None si aucun marqueur d'obligation, jamais déduit du simple usage
    # d'une méthode par le professeur dans sa correction.
    mandated_method: str | None = None
    # Domaine de raisonnement identifié pour la question
    question_domain_type: "ExerciseType" = field(default_factory=lambda: ExerciseType.OPEN_ENDED)
    # Phase 2/4 — id des sous-questions officielles C2PCT (module
    # c2pct_scaffold, 15 au total) réellement couvertes, cherchées dans
    # l'énoncé ET la correction. Aucune limite artificielle (0 à 15, selon
    # ce que les textes démontrent réellement) ; liste vide un résultat
    # valide. Détection hybride rapidfuzz (indice seulement)/LLM (rôle
    # principal), cf. docstring module et _fuzzy_candidate_subquestions.
    covered_subquestions: list[str] = field(default_factory=list)
    # Phase 5C — DÉRIVÉ de covered_subquestions (Phase 2/4, plus une
    # extraction séparée par le LLM) : une compétence est mobilisée si AU
    # MOINS UNE de ses sous-questions officielles est couverte. Aucune
    # limite artificielle sur le nombre retenu (0 à 7). Consommé plus tard
    # par Pedagogical_Evaluation_Agent pour répartir le barème entre
    # compétences (hors périmètre ici).
    competencies_mobilized: list[C2PCTSkillCode] = field(default_factory=list)
    # Phase 6 — fournisseur:modèle réel utilisé pour cet appel LLM
    # ("groq:llama-3.3-70b", "+fallback" si le repli d'infrastructure a été
    # déclenché), pour AgentDecisionLog.model_version. None si l'appel n'a
    # jamais abouti (DecompositionSchemaError levée avant tout retour).
    model_version: str | None = None


class ExerciseType(StrEnum):
    """Domaine de raisonnement identifié au niveau d'une question."""
    MATHEMATICAL = "mathematical"
    SCIENTIFIC = "scientific"
    PROGRAMMING = "programming"
    WRITING = "writing"
    PROOF = "proof"
    MULTIPLE_CHOICE = "multiple_choice"
    PROCEDURAL = "procedural"
    OPEN_ENDED = "open_ended"


class CorrectionMode(StrEnum):

    """§2bis — mode de vérification d'UN critère précis, pas de toute la question."""
    SOLUTION_WORKED = "solution_worked"
    CRITERIA_BASED = "criteria_based"
    MULTIPLE_DISTINCT_ANSWERS = "multiple_distinct_answers"
    RUBRIC_LEVELS = "rubric_levels"
    BINARY_CHECKLIST = "binary_checklist"
    PROCEDURAL_SEQUENCE = "procedural_sequence"
    TEST_CASE_BASED = "test_case_based"
    # Pas de OPEN_JUDGMENT — écarté définitivement (doc de référence) : un
    # jugement totalement libre sans aucun critère n'existe pas en pratique,
    # tout cas ambigu est classé CRITERIA_BASED.


@dataclass
class TestCase:
    """
    Phase 5B (§2quinquies) — un cas de test extrait de la correction pour un
    critère CorrectionMode.TEST_CASE_BASED. Aucune exécution ici (agent
    futur, sandbox/Judge0) — uniquement l'extraction déterministe du texte.
    """
    input: str
    expected_output: str
    # Si la correction ne précise pas explicitement, défaut "visible" —
    # jamais "hidden" deviné (un cas de test non marqué caché doit rester
    # traité comme visible, plus sûr : cf. _parse_criterion).
    visibility: Literal["visible", "hidden"] = "visible"


@dataclass
class BaremeCriterionProposal:
    id: str  # UUID string — même id que Bareme.criteria (JSONB) attend
    label: str  # "exactitude" | "cohérence" | "complétude" | "justification"
    points: Decimal
    correction_mode: CorrectionMode
    # Uniquement pour CorrectionMode.CRITERIA_BASED — conditions atomiques
    # vérifiables indépendamment, jamais une réponse-modèle narrative
    # (garde-fou anti-biais, cf. _parse_criterion).
    verifiable_conditions: list[str] = field(default_factory=list)
    # §2ter — un critère qui invalide la totalité des points en cas de
    # violation, peu importe le reste (ex. protocole de sécurité).
    disqualifying: bool = False
    # Phase 5B (§2quinquies) — uniquement pour CorrectionMode.TEST_CASE_BASED
    # (filières informatique) : vides/None pour tout autre mode, garde-fou
    # anti-biais en code dans _parse_criterion, même principe que
    # verifiable_conditions pour CRITERIA_BASED.
    test_cases: list[TestCase] = field(default_factory=list)
    reference_code: str | None = None  # code de référence du prof, si fourni
    # Complexité algorithmique attendue, UNIQUEMENT si explicitement
    # mentionnée dans le texte (ex. "O(n log n)") — jamais déduite du code.
    expected_complexity: str | None = None
    # Uniquement pour CorrectionMode.RUBRIC_LEVELS — grille RÉELLE du
    # professeur (jamais une échelle standard inventée), ORDONNÉE du
    # meilleur au pire niveau, cf. _find_rubric_level_index (Comparative_
    # Evaluation_Agent) qui dérive score_ratio de cette position. Chaque
    # entrée : {"level": str, "description": str}. Vide pour tout autre mode.
    rubric_levels: list[dict] = field(default_factory=list)
    # Uniquement pour CorrectionMode.PROCEDURAL_SEQUENCE — étapes RÉELLES
    # attendues par le professeur, ORDONNÉES. Vide pour tout autre mode.
    expected_steps: list[str] = field(default_factory=list)


@dataclass
class BaremeResult:
    case: Literal["DETAILED", "GLOBAL_PROPOSED"]  # jamais "MISSING" : Cas 3 lève une exception
    total_points: Decimal
    criteria: list[BaremeCriterionProposal]
    status: Literal["READY", "PENDING_REVIEW"]  # READY = Cas 1, PENDING_REVIEW = Cas 2
    # Phase 6 — cf. DecompositionResult.model_version, même format.
    model_version: str | None = None
    # 2026-08-18 — règles générales du barème classique (Cas 1/2), non
    # rattachées à un critère précis (règles communes, conditions
    # d'application, consignes méthodologiques, pénalités non chiffrées,
    # éléments obligatoires...) : jusqu'ici perdues après extraction (seul
    # `criteria` était conservé). Transmises telles quelles à Comparative_
    # Evaluation_Agent pour influencer un VERDICT — jamais un calcul de
    # points direct (ajout/retrait), hors périmètre tant que l'agent
    # responsable du calcul final des points n'existe pas.
    general_rules: list[str] = field(default_factory=list)


@dataclass
class SubquestionSegment:
    """
    Extrait VERBATIM du texte source (énoncé ou correction) correspondant à
    une sous-question C2PCT officielle déjà confirmée dans covered_
    subquestions — jamais une paraphrase, jamais un id hors de cette liste
    (cf. _extract_subquestion_segments / _find_verbatim_span). `official_
    title` n'est PAS porté ici : résolu à la lecture depuis c2pct_scaffold
    (seule source de vérité, jamais dupliquée en base — même principe que
    related_competency_name côté ReasoningStep).
    """
    id: str
    content: str


@dataclass
class QuestionVerificationResult:
    question_id: uuid.UUID
    steps: list[ReasoningStepOutput]
    decomposition_error: str | None
    bareme: BaremeResult | None
    bareme_error: str | None
    # §2ter — signal seulement, cf. DecompositionResult.
    involves_graph_plot: bool = False
    # §2ter (Phase 3b) — détection hybride regex+rapidfuzz de références
    # croisées explicites entre questions, cf. _detect_cross_question_references.
    depends_on_question_order: list[int] = field(default_factory=list)
    # Phase 4 — formalisation des signaux d'incertitude des phases 1/2/3a/3b
    # en ClarificationRequest, cf. module docstring pour la table de sévérité.
    clarifications: list[ClarificationRequest] = field(default_factory=list)
    # Phase 5A — niveau question (pas critère) : une consigne de méthode
    # imposée porte généralement sur toute la question. Consommé plus tard
    # par Solution_Variant_Generation_Agent (jamais de variante hors méthode
    # imposée) et un futur Comparative_Evaluation_Agent (consigne_respected,
    # séparé du score d'exactitude) — hors périmètre ici, cf. docstring module.
    mandated_method: str | None = None
    # Domaine de raisonnement identifié pour la question
    question_domain_type: ExerciseType = ExerciseType.OPEN_ENDED
    # Phase 2/4 — cf. DecompositionResult.covered_subquestions.
    covered_subquestions: list[str] = field(default_factory=list)
    # Phase 5C — DÉRIVÉ de covered_subquestions, cf. DecompositionResult.
    # competencies_mobilized. Plus une extraction séparée par le LLM depuis
    # ce ticket (Phase 2/4) — même logique stricte que le barème (Cas 1/2/3)
    # à la granularité sous-question désormais : identifiable dans l'un des
    # deux textes (énoncé/correction), ou absente des deux.
    competencies_mobilized: list[C2PCTSkillCode] = field(default_factory=list)
    # Phase 6 — combine model_version de la décomposition et, si le barème a
    # abouti, celui du barème ("+" entre les deux) : pour AgentDecisionLog.
    model_version: str | None = None
    # Chantier barème C2PCT natif — Cas 0, PRIORITAIRE sur le calcul de
    # répartition proportionnelle de Pedagogical_Evaluation_Agent. None si
    # aucun barème détaillé par sous-question C2PCT n'a été trouvé pour
    # cette question (repli sur le calcul proportionnel existant, jamais un
    # dict vide ambigu) — cf. _extract_subquestion_points, appelée UNE FOIS
    # pour tout l'exercice (pas par question, contrairement aux autres
    # champs de ce dataclass).
    subquestion_points: dict[str, Decimal] | None = None
    # 2026-08-29 (backlog_bugs_c2pct.md, structuration Question.subquestions)
    # — extraits verbatim vérifiés déterministiquement, cf. SubquestionSegment
    # et _extract_subquestion_segments. None si covered_subquestions est vide
    # pour cette question (appel LLM évité, jamais un dict vide ambigu) ou si
    # l'appel a échoué (best-effort, jamais bloquant, même discipline que
    # subquestion_points).
    subquestion_segments: list[SubquestionSegment] | None = None
    # 2026-08-18 — règles générales applicables à cette question, fusion de
    # deux sources qui restent des mécanismes d'EXTRACTION séparés (jamais
    # confondus en amont, cf. BaremeResult.general_rules pour le classique
    # et _extract_subquestion_points pour le C2PCT natif) : le barème
    # classique (Cas 1/2, si `bareme` a abouti) et le barème C2PCT natif
    # (Cas 0, portée document entier, donc identique pour toutes les
    # questions de l'exercice). En pratique une question donnée n'utilise
    # généralement qu'un des deux mécanismes (cf. docstring module) — cette
    # fusion ne fait donc quasi jamais doublon. Consommé par Comparative_
    # Evaluation_Agent pour influencer un VERDICT, jamais un calcul de
    # points direct (cf. BaremeResult.general_rules).
    general_rules: list[str] = field(default_factory=list)



@dataclass
class ExtractionVerificationReport:
    exercise_id: uuid.UUID
    questions: list[QuestionVerificationResult]


# ---------------------------------------------------------------------------
# Schémas Pydantic pour sortie structurée LLM — remplacent l'ancienne
# extraction par regex (recherche de la première/dernière accolade sur texte
# libre) + json.loads sur les 3 appels LLM de cet agent (_decompose_steps,
# _extract_or_propose_bareme, _extract_subquestion_points). Cette regex
# captait une paire d'accolades invalide dès que le texte source contenait du
# LaTeX (`formula`, très courant ici — questions scientifiques/mathématiques)
# ou une réponse LLM entourée de prose/bloc de code markdown — constaté en
# test réel (agents_tests/step4_test_extraction_verification_probe.py),
# même bug que Document_Structuring_Agent avant son fix du 2026-08-16.
# ---------------------------------------------------------------------------

class _StepSchema(BaseModel):
    step_ref: str
    order: int
    step_type: ReasoningStepType
    description: str
    source_span: str
    formula: str | None = None
    anomaly_detected: bool = False
    anomaly_justification: str | None = None
    case_group_id: str | None = None
    recurrence_role: Literal["initialization", "induction", "conclusion"] | None = None


class _DecompositionSchema(BaseModel):
    steps: list[_StepSchema]
    involves_graph_plot: bool = False
    mandated_method: str | None = None
    question_domain_type: "ExerciseType" = ExerciseType.OPEN_ENDED
    covered_subquestions: list[str] = Field(default_factory=list)


class _TestCaseSchema(BaseModel):
    input: str
    expected_output: str
    visibility: Literal["visible", "hidden"] = "visible"


class _RubricLevelSchema(BaseModel):
    level: str
    description: str = ""


class _BaremeCriterionSchema(BaseModel):
    label: str
    points: float
    correction_mode: "CorrectionMode"
    verifiable_conditions: list[str] = Field(default_factory=list)
    disqualifying: bool = False
    test_cases: list[_TestCaseSchema] = Field(default_factory=list)
    reference_code: str | None = None
    expected_complexity: str | None = None
    rubric_levels: list[_RubricLevelSchema] = Field(default_factory=list)
    expected_steps: list[str] = Field(default_factory=list)


class _BaremeSchema(BaseModel):
    case: Literal["DETAILED", "GLOBAL_PROPOSED"]
    total_points: float
    criteria: list[_BaremeCriterionSchema]
    justification: str | None = None  # demandé au LLM (prompt), jamais consommé — conservé pour fidélité au schéma
    # 2026-08-18 — règles générales du barème non rattachées à un critère
    # précis (règles communes, conditions d'application, consignes
    # méthodologiques, pénalités non chiffrées, éléments obligatoires...),
    # cf. docstring BaremeResult.general_rules pour la portée exacte.
    general_rules: list[str] = Field(default_factory=list)


class _SubquestionPointsGroupSchema(BaseModel):
    question_order: int
    subquestion_points: dict[str, float] = Field(default_factory=dict)


class _SubquestionPointsSchema(BaseModel):
    questions: list[_SubquestionPointsGroupSchema] = Field(default_factory=list)
    # 2026-08-18 — même principe que _BaremeSchema.general_rules, mais pour
    # le barème C2PCT natif (Cas 0) : portée DOCUMENT ENTIER (pas par
    # question), cf. docstring QuestionVerificationResult.general_rules.
    general_rules: list[str] = Field(default_factory=list)


class _SubquestionSegmentSchema(BaseModel):
    id: str
    content: str


class _SubquestionSegmentationSchema(BaseModel):
    segments: list[_SubquestionSegmentSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ExtractionVerificationAgent:
    """Décomposition en étapes + barème (3 cas), question par question."""

    AGENT_NAME = "Extraction_Verification_Agent"

    _POINT_PATTERN = re.compile(r"\d+(?:[.,]\d+)?\s*(?:pts?|points?)\b", re.IGNORECASE)

    # §2ter (Phase 3b), filet de sécurité déterministe (2026-08-17) —
    # capture "P = 28 kN" / "P=28,5kN" / "P = 28" : un identifiant (lettre
    # + indice optionnel), un nombre (virgule française ou point), une
    # unité optionnelle. Volontairement étroit (jamais une expression
    # complète type \frac{...}) : sert uniquement à récupérer une valeur
    # finale numérique explicite que le LLM a laissée hors du champ
    # formula, jamais à reconstruire un raisonnement.
    _CONCLUSION_VALUE_PATTERN = re.compile(
        r"([A-Za-zΑ-Ωα-ω][\wΑ-Ωα-ω]*(?:_\{?[\wΑ-Ωα-ω]+\}?)?)\s*=\s*"
        r"([-+]?\d+(?:[.,]\d+)?)\s*([a-zA-Zµ°%/²³]*)"
    )

    # §2ter (Phase 3b) — détection de dépendances inter-questions, marqueur
    # textuel explicite seulement (pas de repli LLM dans cette phase).
    _QUESTION_NUMBER_PATTERN = re.compile(r"(?:question\s*n?°?\s*|q\.?\s*)(\d+)", re.IGNORECASE)
    _PRECEDING_QUESTION_PATTERN = re.compile(
        r"question\s+pr[ée]c[ée]dente|pr[ée]c[ée]dente\s+question", re.IGNORECASE,
    )
    _CROSS_REF_TRIGGERS = (
        "d'après la question", "d'apres la question",
        "voir la question", "voir question",
        "cf question", "cf. question",
        "en utilisant le résultat de la question", "en utilisant le resultat de la question",
        "à partir du résultat de la question", "a partir du resultat de la question",
        "comme à la question", "comme a la question",
        "résultat de la question", "resultat de la question",
    )
    _CROSS_REF_FUZZY_THRESHOLD = 80
    _CROSS_REF_WINDOW_CHARS = 40

    # Phase 2/4 (§7C révisé) — granularité sous-question C2PCT (module
    # c2pct_scaffold.py, seule source de vérité, jamais copiée en dur ici).
    # Seuil empirique de calibration (même statut que
    # _CROSS_REF_FUZZY_THRESHOLD ci-dessus) : n'exclut jamais rien, alimente
    # seulement un indice transmis au LLM, cf. _fuzzy_candidate_subquestions.
    _SUBQUESTION_FUZZY_THRESHOLD = 70
    # Chantier barème C2PCT natif (Cas 0) — pré-filtre déterministe avant
    # l'appel LLM (même esprit que _has_any_point_amount pour Cas 3) :
    # exige un motif "chiffre.chiffre" (ex. "1.1", "3.2") quelque part dans
    # le document entier. Volontairement plus strict que _has_any_point_
    # amount seul (qui matcherait sur "5 points" ou "2pts" n'importe où,
    # y compris le barème classique Cas 1/2/3 déjà omniprésent) — sans ce
    # filtre resserré, l'appel Cas 0 se déclencherait sur quasiment tous
    # les documents. Limite assumée, documentée : les 2 sous-questions
    # officielles à id SANS point ("4", "5", cf. c2pct_scaffold.py) ne sont
    # jamais détectées par ce pré-filtre seul (un chiffre isolé est bien
    # trop ambigu pour servir de déclencheur, contrairement à un motif
    # pointé) — jamais bloquant, retombe simplement sur le calcul
    # proportionnel existant pour ces 2 sous-questions comme aujourd'hui.
    _SUBQUESTION_POINTS_CANDIDATE_PATTERN = re.compile(r"\b\d\.\d\b")
    # 2026-08-18 — second déclencheur, indépendant du premier (OU logique,
    # jamais un ET) : une mention textuelle explicite de la méthodologie
    # C2PCT elle-même (ex. "méthodologie C2PCT", "méthode Chaabi") suffit à
    # elle seule à justifier l'appel Cas 0, même en l'absence de toute
    # numérotation "chiffre.chiffre" détectable par le pattern ci-dessus
    # (ex. barème qui renvoie aux sous-questions par leur intitulé plutôt
    # que par id). Les deux motifs peuvent aussi cooccurrer — le prompt
    # Cas 0 reste seul juge de ce qu'il trouve réellement dans le texte,
    # ce pré-filtre ne fait qu'autoriser ou non l'appel LLM.
    _C2PCT_METHODOLOGY_MENTION_PATTERN = re.compile(r"c2pct|chaabi", re.IGNORECASE)
    _ALL_SUBQUESTION_IDS = frozenset(sq.id for sq in get_all_subquestions())
    _SUBQUESTIONS_REFERENCE_BLOCK = "\n".join(
        [
            "Sous-questions officielles C2PCT (id — compétence — intention à "
            "vérifier sur le fond, jamais un texte à retrouver littéralement) :",
            *(
                f'- "{sq.id}" ({skill.value}) : {sq.label} — intention : « {sq.reference_prompt} »'
                for skill in C2PCTSkillCode
                for sq in get_subquestions_for(skill)
            ),
        ]
    )

    async def execute(
        self,
        questions: list[QuestionInput],
        blocks_by_question: dict[uuid.UUID, list[CorrectionBlockInput]],
        exercise_status: ExerciseStatus,
        context: AgentExecutionContext,
    ) -> ExtractionVerificationReport:
        exercise_id = context.exercise_id or uuid.UUID(int=0)

        span_metadata = {
            "flow_type": context.flow_type,
            "exercise_id": str(exercise_id),
        }

        with AgentTraceSpan(self.AGENT_NAME, trace_id=context.trace_id, metadata=span_metadata) as span:
            t_start = time.perf_counter()

            # Étape 1 — Précondition, une fois pour tout l'exercice : refuse
            # tout redéclenchement automatique une fois l'exercice publié.
            if exercise_status != ExerciseStatus.DRAFT:
                raise ExerciseAlreadyPublishedError(exercise_id, str(exercise_status))

            # Passe préliminaire (Phase 3b) — sur l'ensemble de `questions`,
            # jamais dans la boucle par question : propriété structurelle,
            # ne dépend d'aucun résultat de décomposition/barème. Calcule
            # aussi correction_texts une seule fois (au lieu de _combine_text
            # répété à chaque itération de la boucle ci-dessous).
            correction_texts = {
                q.question_id: self._combine_text(blocks_by_question.get(q.question_id, []))
                for q in questions
            }
            deps_by_question = self._detect_cross_question_references(questions, correction_texts)

            # Chantier barème C2PCT natif — Cas 0, UN SEUL appel pour
            # l'exercice ENTIER (jamais par question, cf. docstring méthode) :
            # le barème détaillé par sous-question C2PCT peut être regroupé
            # n'importe où dans le document, jamais forcément dans le texte
            # rattaché à une question précise (correction_texts ci-dessus
            # reste scopé par question — insuffisant pour ce cas).
            full_document_text = "\n\n".join(t for t in correction_texts.values() if t)
            subquestion_points_by_question, c2pct_general_rules = await self._extract_subquestion_points(
                questions, full_document_text, context,
            )

            results: list[QuestionVerificationResult] = []
            for question in questions:
                correction_text = correction_texts[question.question_id]
                # Bug réel évité (2026-09-06) : calculé ICI, indépendamment
                # du succès de la décomposition ci-dessous — utilisé aussi
                # dans le bloc bareme (plus bas), qui s'exécute QUE la
                # décomposition ait réussi ou non (DecompositionSchemaError).
                # Auparavant recalculé seulement dans le bloc `else:` de la
                # décomposition, NameError garanti sinon.
                bareme_points_for_question = subquestion_points_by_question.get(question.question_id)

                # a. Décomposition — toujours en premier, indépendamment du barème.
                steps: list[ReasoningStepOutput] = []
                involves_graph_plot = False
                decomposition_error: str | None = None
                mandated_method: str | None = None
                question_domain_type: ExerciseType = ExerciseType.OPEN_ENDED
                covered_subquestions: list[str] = []
                competencies_mobilized: list[C2PCTSkillCode] = []
                decomposition_model_version: str | None = None
                # Phase 4 — clarifications déjà formalisées pendant la
                # décomposition (anomalie isolée, récurrence, sympy/pint) ;
                # complétées ci-dessous par celle du barème Cas 2 si besoin.
                clarifications: list[ClarificationRequest] = []
                try:
                    decomposition = await self._decompose_steps(question, correction_text, context)
                    steps = decomposition.steps
                    involves_graph_plot = decomposition.involves_graph_plot
                    clarifications = list(decomposition.clarifications)
                    mandated_method = decomposition.mandated_method
                    question_domain_type = decomposition.question_domain_type
                    covered_subquestions = decomposition.covered_subquestions
                    competencies_mobilized = decomposition.competencies_mobilized
                    decomposition_model_version = decomposition.model_version
                except DecompositionSchemaError as e:
                    decomposition_error = str(e)
                else:
                    # a2. Réconciliation barème C2PCT natif (Cas 0) vs
                    # décomposition — deux appels LLM indépendants, sur des
                    # périmètres de texte différents (Cas 0 lit TOUT le
                    # document combiné, cf. full_document_text ci-dessus ;
                    # la décomposition ne lit que le texte rattaché à CETTE
                    # question précise) jamais réconciliés jusqu'ici.
                    # Constaté en test réel (2026-08-30) : un barème
                    # combinant plusieurs questions en un seul bloc de
                    # correction (rattaché à une seule question) fait
                    # halluciner/omettre des sous-questions côté
                    # décomposition, dans les deux sens (une sous-question
                    # listée comme couverte sans exister dans le vrai
                    # barème, ET l'inverse). Le barème du professeur (des
                    # points explicites "X → Y") est une source bien plus
                    # fiable qu'un jugement sémantique de "couverture" —
                    # quand le Cas 0 a trouvé un barème pour cette question,
                    # ses clés REMPLACENT covered_subquestions (jamais une
                    # simple intersection : corrige les deux sens de
                    # l'erreur à la fois). competencies_mobilized redérivé
                    # en conséquence (sinon désynchronisé du nouveau
                    # covered_subquestions). Repli sur le résultat de la
                    # décomposition si Cas 0 n'a rien trouvé pour cette
                    # question (best-effort, comme partout ailleurs dans ce
                    # chantier barème C2PCT natif).
                    bareme_points_for_question = subquestion_points_by_question.get(question.question_id)
                    if bareme_points_for_question:
                        covered_subquestions = sorted(bareme_points_for_question.keys())
                        competencies_mobilized = self._derive_competencies_mobilized(covered_subquestions)

                    # b. Confiance de rattachement — déterministe, jamais un
                    # jugement LLM (cf. _build_low_confidence_attachment_
                    # clarification). N'a de sens que si la décomposition a
                    # réussi (sinon rien n'a été construit sur ce texte).
                    content_matched_count = sum(
                        1 for b in blocks_by_question.get(question.question_id, [])
                        if b.evidence_level == BlockEvidenceLevel.CONTENT_MATCHED
                    )
                    if content_matched_count:
                        clarifications.append(
                            self._build_low_confidence_attachment_clarification(
                                question, content_matched_count,
                            )
                        )

                # b2. Segmentation par sous-question (2026-08-29,
                # backlog_bugs_c2pct.md) — n'a de sens que si la
                # décomposition a réussi (covered_subquestions vient d'elle).
                subquestion_segments: list[SubquestionSegment] | None = None
                if not decomposition_error:
                    subquestion_segments = await self._extract_subquestion_segments(
                        question, correction_text, covered_subquestions, context,
                    )
                    # Couche 2 (backlog_bugs_c2pct.md, B1) — écart détecté
                    # MÉCANIQUEMENT (comparaison d'ensembles, jamais un
                    # jugement LLM) : une sous-question déjà confirmée
                    # couverte (covered_subquestions, LLM) mais dont aucun
                    # extrait verbatim n'a pu être vérifié dans le texte
                    # source (cf. _find_verbatim_span) est un signal concret
                    # de perte probable à l'OCR (B1) — jamais silencieux.
                    # WARNING, pas BLOCKING : ne bloque jamais la publication
                    # (la notation s'appuie sur SolutionVariant.content, pas
                    # sur cette structuration d'affichage), seulement une
                    # alerte pour que le professeur vérifie manuellement.
                    found_ids = {s.id for s in (subquestion_segments or [])}
                    missing_ids = [sq_id for sq_id in covered_subquestions if sq_id not in found_ids]
                    if missing_ids:
                        clarifications.append(
                            self._build_missing_subquestion_content_clarification(question, missing_ids)
                        )

                # c/d. Barème — Cas 3 (regex, seule partie déterministe) puis
                # Cas 1/2 (LLM, avec la décomposition déjà produite en contexte).
                bareme: BaremeResult | None = None
                bareme_error: str | None = None
                try:
                    self._check_bareme_presence(question.question_id, correction_text)
                except MissingBaremeError as e:
                    bareme_error = str(e)
                    # Bug réel corrigé (2026-09-06, test réel) : jusqu'ici,
                    # un barème introuvable ne posait QUE bareme_error (un
                    # log de décision passif) — rien ne demandait jamais
                    # explicitement au professeur de le fournir, contrairement
                    # au Cas 2 (répartition ambiguë, cf. _build_bareme_
                    # clarification juste en dessous) qui a déjà cette
                    # clarification. Deux exercices de test ont ainsi été
                    # publiés sans qu'aucune note ne soit jamais calculable
                    # pour leurs questions, sans que personne ne le
                    # remarque avant la correction d'une vraie copie.
                    # bareme_points_for_question (Cas 0 C2PCT natif, calculé
                    # plus haut) reste le seul repli légitime — jamais une
                    # clarification pour une question déjà correctement
                    # notée par l'autre mécanisme (barème par sous-questions).
                    if not bareme_points_for_question:
                        clarifications.append(
                            self._build_missing_bareme_clarification(question, bareme_error)
                        )
                else:
                    try:
                        bareme = await self._extract_or_propose_bareme(question, correction_text, steps, context)
                    except (BaremeExtractionSchemaError, ModeClassificationSchemaError) as e:
                        bareme_error = str(e)
                    else:
                        # Phase 4 — une répartition Cas 2 non détaillée par le
                        # professeur n'est jamais une vérité acquise : BLOCKING.
                        if bareme.status == "PENDING_REVIEW":
                            clarifications.append(self._build_bareme_clarification(question, bareme))
                        # Phase 5B — TEST_CASE_BASED détecté mais rien
                        # d'exécutable extrait (spécification purement
                        # textuelle) : BLOCKING — le mécanisme de notation
                        # automatique de ce critère n'a littéralement rien à
                        # exécuter tant que le professeur n'a pas fourni au
                        # moins un cas de test ou un code de référence.
                        for criterion in bareme.criteria:
                            if (
                                criterion.correction_mode == CorrectionMode.TEST_CASE_BASED
                                and not criterion.test_cases
                                and not criterion.reference_code
                            ):
                                clarifications.append(
                                    self._build_test_case_based_incomplete_clarification(
                                        question, criterion,
                                    )
                                )

                # Phase 6 — fournisseur(s) réel(s) utilisé(s) pour cette
                # question, décomposition puis barème s'il a abouti.
                model_versions = [v for v in (decomposition_model_version, bareme.model_version if bareme else None) if v]
                model_version = "+".join(model_versions) or None

                results.append(
                    QuestionVerificationResult(
                        question_id=question.question_id,
                        steps=steps,
                        decomposition_error=decomposition_error,
                        bareme=bareme,
                        bareme_error=bareme_error,
                        involves_graph_plot=involves_graph_plot,
                        depends_on_question_order=deps_by_question.get(question.question_id, []),
                        clarifications=clarifications,
                        mandated_method=mandated_method,
                        question_domain_type=question_domain_type,
                        covered_subquestions=covered_subquestions,
                        competencies_mobilized=competencies_mobilized,
                        model_version=model_version,
                        subquestion_points=subquestion_points_by_question.get(question.question_id),
                        subquestion_segments=subquestion_segments,
                        # Fusion des 2 mécanismes d'extraction (restent
                        # séparés en amont, cf. docstring du champ) : en
                        # pratique quasi jamais les deux à la fois pour une
                        # même question (cf. docstring module).
                        general_rules=[
                            *(bareme.general_rules if bareme else []),
                            *c2pct_general_rules,
                        ],
                    )
                )

            span.record_metrics(
                question_count=len(questions),
                decomposition_failures=sum(1 for r in results if r.decomposition_error),
                bareme_missing=sum(1 for r in results if r.bareme is None and r.bareme_error),
                bareme_detailed=sum(1 for r in results if r.bareme and r.bareme.case == "DETAILED"),
                bareme_proposed=sum(1 for r in results if r.bareme and r.bareme.case == "GLOBAL_PROPOSED"),
                total_duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
            )

            return ExtractionVerificationReport(exercise_id=exercise_id, questions=results)

    # ------------------------------------------------------------------
    # Décomposition (1er appel LLM, retry métier 1 essai)
    # ------------------------------------------------------------------

    _RECURRENCE_ROLES = ("initialization", "induction", "conclusion")

    async def _decompose_steps(
        self, question: QuestionInput, correction_text: str, context: AgentExecutionContext,
    ) -> DecompositionResult:
        # Phase 2/4 — passage déterministe, indice seulement (cf. docstring
        # module) : cherché séparément dans l'énoncé et la correction, pour
        # que le LLM sache d'où vient chaque candidat fort.
        fuzzy_hints_statement = self._fuzzy_candidate_subquestions(question.statement)
        fuzzy_hints_correction = self._fuzzy_candidate_subquestions(correction_text)

        user_msg = DECOMPOSITION_USER_TEMPLATE.format(
            statement=question.statement,
            correction_text=correction_text,
            fuzzy_hints_statement=", ".join(sorted(fuzzy_hints_statement)) or "aucun",
            fuzzy_hints_correction=", ".join(sorted(fuzzy_hints_correction)) or "aucun",
        )
        messages = [
            # Concaténation, jamais .format() sur DECOMPOSITION_SYSTEM_PROMPT
            # (qui contient déjà des accolades JSON littérales) : le bloc des
            # 15 sous-questions est injecté dynamiquement depuis
            # c2pct_scaffold.py, seule source de vérité — jamais une copie
            # figée en dur dans le fichier de prompt.
            {"role": "system", "content": DECOMPOSITION_SYSTEM_PROMPT + "\n\n" + self._SUBQUESTIONS_REFERENCE_BLOCK},
            {"role": "user", "content": user_msg},
        ]

        last_error = ""
        # 1 retry métier autorisé — jamais confondu avec le retry
        # d'infrastructure déjà géré à l'intérieur d'invoke_llm_with_fallback.
        for attempt in range(2):
            try:
                result, spec, fallback, _tokens = await invoke_llm_with_fallback(
                    task_type=TaskType.EXTRACTION_VERIFICATION,
                    messages=messages,
                    response_schema=_DecompositionSchema,
                    context=context,
                )
            except Exception as e:
                last_error = str(e)
                if attempt == 0:
                    continue
                raise DecompositionSchemaError(question.question_id, last_error) from e

            steps = [
                ReasoningStepOutput(
                    step_ref=s.step_ref, order=s.order, step_type=s.step_type,
                    description=s.description, source_span=s.source_span, formula=s.formula,
                    anomaly_detected=s.anomaly_detected, anomaly_justification=s.anomaly_justification,
                    case_group_id=s.case_group_id, recurrence_role=s.recurrence_role,
                )
                for s in result.steps
            ]
            involves_graph_plot = result.involves_graph_plot
            # Phase 5A — texte libre tel que nommé dans l'énoncé/la
            # correction, jamais une valeur fabriquée : None si absent.
            mandated_method = result.mandated_method or None
            question_domain_type = result.question_domain_type
            # Phase 2/4 — extraction directe, granularité sous-question :
            # tout id hors des 15 valides (module c2pct_scaffold) est
            # rejeté individuellement, jamais retenté au niveau du schéma
            # entier — un unique id imprévu ne doit jamais faire échouer
            # toute la décomposition (même garde-fou que l'ancien
            # competencies_mobilized, à la nouvelle granularité).
            covered_subquestions = [
                raw_id for raw_id in result.covered_subquestions if raw_id in self._ALL_SUBQUESTION_IDS
            ]
            # Phase 5C — DÉRIVÉ de covered_subquestions, plus une
            # extraction séparée par le LLM (cf. docstring module).
            competencies_mobilized = self._derive_competencies_mobilized(covered_subquestions)

            # Garde déterministe : jamais une conclusion inventée pour combler
            # une sortie LLM qui n'en a pas produit une. Une liste vide EST
            # un résultat valide (règle 2 du prompt : aucune conclusion
            # identifiable, ex. correction TEST_CASE_BASED en code pur sans
            # raisonnement classique, Phase 5B) — seule une liste NON vide
            # dont la dernière étape n'est pas CONCLUSION est un échec de
            # schéma à retenter.
            if steps and steps[-1].step_type != ReasoningStepType.CONCLUSION:
                if attempt == 0:
                    continue
                raise DecompositionSchemaError(
                    question.question_id, "Dernière étape non CONCLUSION après retry",
                )

            for i in range(1, len(steps)):
                steps[i].depends_on_refs = [steps[i - 1].step_ref]

            # Phase 4 — instantané des anomalies AVANT _check_recurrence_completeness :
            # c'est le seul point où anomaly_detected ne peut venir que du LLM
            # (Phase 1, "anomalie de calcul isolée"), jamais de la garde de
            # récurrence déterministe ci-dessous — distinction fiable même si
            # l'étape porte par ailleurs un recurrence_role non lié à l'anomalie.
            clarifications: list[ClarificationRequest] = [
                self._build_calculation_anomaly_clarification(question, idx, step)
                for idx, step in enumerate(steps)
                if step.anomaly_detected
            ]

            recurrence_clarification = self._check_recurrence_completeness(question, steps)
            if recurrence_clarification is not None:
                clarifications.append(recurrence_clarification)

            # Post-traitement déterministe (Phase 3b) — jamais un jugement
            # LLM, échec silencieux (None/not_checkable) sur parsing raté.
            # Phase 4 — un échec de parsing outillé est formalisé en trace
            # INFORMATIONAL, seulement quand une formule/unité semblait
            # réellement pertinente (jamais sur une étape qui n'en a pas).
            for idx, step in enumerate(steps):
                if step.step_type == ReasoningStepType.CONCLUSION:
                    # Filet de sécurité déterministe (2026-08-17, cf. mémoire
                    # de session) : le LLM laisse parfois formula vide pour
                    # la conclusion alors que description/source_span
                    # contiennent littéralement "P = 28 kN" — sans ce
                    # backfill, canonical_form/dimensional_check_result
                    # restent None faute d'input, ET reference_conclusion
                    # (Solution_Variant_Generation_Agent, en aval) hérite
                    # d'une simple description texte au lieu d'une formule
                    # comparable. Mutation de step.formula lui-même (pas
                    # seulement une variable locale) pour que le fix se
                    # propage naturellement à toute la persistance en aval —
                    # jamais une valeur inventée, uniquement extraite
                    # verbatim par regex du texte déjà produit.
                    if not step.formula:
                        step.formula = self._backfill_conclusion_formula(step)
                    step.canonical_form = self._compute_canonical_form(step.formula)
                    if step.formula and step.canonical_form is None:
                        clarifications.append(
                            self._build_sympy_failure_clarification(question, idx, step)
                        )
                if step.step_type == ReasoningStepType.COMPUTATION:
                    step.dimensional_check_result = self._compute_dimensional_check(
                        step.formula, step.description,
                    )
                    if step.dimensional_check_result == "not_checkable" and self._looks_like_equation(
                        step.formula, step.description,
                    ):
                        clarifications.append(
                            self._build_dimensional_check_failure_clarification(question, idx, step)
                        )

            return DecompositionResult(
                steps=steps,
                involves_graph_plot=involves_graph_plot,
                clarifications=clarifications,
                mandated_method=mandated_method,
                question_domain_type=question_domain_type,
                covered_subquestions=covered_subquestions,
                competencies_mobilized=competencies_mobilized,
                model_version=self._format_model_version(spec, fallback),
            )

        raise DecompositionSchemaError(question.question_id, last_error)

    @classmethod
    def _fuzzy_candidate_subquestions(cls, text: str) -> set[str]:
        """
        Phase 2/4 (§7C révisé) — DÉLÈGUE au mécanisme partagé (Phase 3/4,
        app.domain.models.competency.c2pct_detection.fuzzy_candidate_
        subquestions), factorisé pour être réutilisé À L'IDENTIQUE par
        Comparative_Evaluation_Agent (texte étudiant) sans dupliquer cette
        logique une deuxième fois. Wrapper conservé (plutôt que supprimé)
        pour ne pas casser les appels existants sur cette classe — même
        seuil qu'avant (_SUBQUESTION_FUZZY_THRESHOLD). Un score faible ou
        l'absence de candidat ne signifie RIEN sur l'absence réelle de la
        sous-question (couverture implicite possible) — jamais utilisé pour
        exclure, indice seulement, cf. docstring du module partagé.
        """
        return fuzzy_candidate_subquestions(text, threshold=cls._SUBQUESTION_FUZZY_THRESHOLD)

    @staticmethod
    def _derive_competencies_mobilized(covered_subquestions: list[str]) -> list[C2PCTSkillCode]:
        """
        Phase 5C (révisé Phase 2/4) — competencies_mobilized n'est plus
        extrait séparément par le LLM : DÉRIVÉ de covered_subquestions,
        jamais recalculé/deviné autrement. Une compétence est mobilisée si
        AU MOINS UNE de ses sous-questions officielles est couverte. Ordre
        déterministe (ordre de déclaration de C2PCTSkillCode).
        """
        covered_set = set(covered_subquestions)
        return [
            skill for skill in C2PCTSkillCode
            if covered_set & {sq.id for sq in get_subquestions_for(skill)}
        ]

    @classmethod
    def _check_recurrence_completeness(
        cls, question: QuestionInput, steps: list[ReasoningStepOutput],
    ) -> ClarificationRequest | None:
        """
        §2ter — pas une exception bloquante : si une correction utilise
        manifestement une récurrence (au moins un recurrence_role renseigné)
        mais que les 3 rôles ne sont pas tous couverts, c'est un signal
        d'anomalie posé sur la dernière étape concernée — même mécanisme que
        la garde anomaly_detected/anomaly_justification déjà existante,
        jamais un nouveau mécanisme.

        Phase 4 — formalise ce signal en ClarificationRequest BLOCKING : une
        démonstration structurellement incomplète compromet l'intégrité de
        toute la référence utilisée pour comparer les copies, pas seulement
        un détail local. None si la récurrence est absente ou complète.
        """
        roles_present = {s.recurrence_role for s in steps if s.recurrence_role is not None}
        if not roles_present or roles_present == set(cls._RECURRENCE_ROLES):
            return None

        target_index, target = next(
            (i, s) for i, s in reversed(list(enumerate(steps))) if s.recurrence_role is not None
        )
        missing = sorted(set(cls._RECURRENCE_ROLES) - roles_present)
        justification = f"Récurrence incomplète — rôle(s) manquant(s) : {', '.join(missing)}."

        if target.anomaly_detected and target.anomaly_justification:
            target.anomaly_justification = f"{target.anomaly_justification} | {justification}"
        else:
            target.anomaly_detected = True
            target.anomaly_justification = justification

        return ClarificationRequest(
            related_field=f"steps[{target_index}].recurrence_role",
            agent_question=(
                f"La question {question.order} présente une démonstration par récurrence "
                f"incomplète : le(s) rôle(s) {', '.join(missing)} ne sont identifiés dans "
                f"aucune étape. Confirmez-vous que la démonstration du professeur est bien "
                f"complète telle quelle, ou faut-il la compléter avant de servir de référence ?"
            ),
            # L'agent ne peut pas inventer le rôle manquant — signalement seul.
            proposed_answer=None,
            severity=ClarificationSeverity.BLOCKING,
        )

    # lowercase_symbols=False : LaTeX distingue "P" (ex. force) de "p" (ex.
    # pression) — un fork qui mélangerait la casse casserait cette
    # distinction physique, contrairement au comportement déjà validé de
    # sympy.sympify sur la branche notation standard juste en dessous.
    # units=True : une unité en \text{} (ex. "\text{ kN}") est écartée de
    # l'expression symbolique plutôt que transformée en pseudo-symbole
    # ("kn") — canonical_form compare une FORME algébrique, jamais une
    # grandeur physique (c'est le rôle, séparé, de dimensional_check_result
    # /_normalize_latex_for_units juste plus bas).
    _LATEX2SYMPY_CONVERSION_CONFIG = ConversionConfig(lowercase_symbols=False)
    _LATEX2SYMPY_NORMALIZATION_CONFIG = NormalizationConfig(units=True)

    @staticmethod
    def _parse_math_expr(text: str) -> sympy.Expr:
        r"""
        Aiguille sur la présence d'un backslash : notation LaTeX (ex.
        "28 \text{ kN}", "\frac{a}{a\sqrt{5}}") -> latex2sympy2_extended
        (gère nativement une égalité "A = B" -> sympy.Eq, pas seulement une
        expression seule) ; notation standard (ex. "L*l") ->
        sympy.sympify, inchangé. Jamais l'inverse en repli : sympify
        accepte la multiplication implicite et "réussirait" silencieusement
        sur du texte LaTeX brut (ex. "28 \text{ kN}" -> 28*N*k*text, un
        résultat inventé plutôt qu'un échec), ce qui empêcherait justement
        le repli vers le parseur LaTeX. La virgule décimale française
        (ex. "1,1") est normalisée en point AVANT l'appel : latex2sympy2_
        extended interprète sinon la virgule comme un séparateur
        d'ensemble ("1,1" -> l'ensemble {1}), un faux succès silencieux
        pire qu'un échec de parsing. Toute exception remonte telle quelle
        à l'appelant, qui centralise la capture.
        """
        if "\\" in text:
            normalized = ExtractionVerificationAgent._LATEX_DECIMAL_COMMA_RE.sub(".", text)
            return latex2sympy(
                normalized,
                conversion_config=ExtractionVerificationAgent._LATEX2SYMPY_CONVERSION_CONFIG,
                normalization_config=ExtractionVerificationAgent._LATEX2SYMPY_NORMALIZATION_CONFIG,
            )
        return sympy.sympify(text)

    @classmethod
    def _backfill_conclusion_formula(cls, step: ReasoningStepOutput) -> str | None:
        """
        §2ter (Phase 3b), filet de sécurité déterministe — le LLM laisse
        parfois formula vide pour l'étape CONCLUSION alors que
        description/source_span contiennent littéralement une valeur
        finale explicite ("... P = 28 kN ..."). Cherche source_span
        D'ABORD (extrait exact du texte source, donc plus fiable), puis
        description en repli. Jamais une valeur inventée : uniquement
        extraite verbatim via _CONCLUSION_VALUE_PATTERN. None si rien de
        ce type n'est trouvé — le comportement reste alors identique à
        avant ce filet (formula reste None), aucune régression.
        """
        for source_text in (step.source_span, step.description):
            if not source_text:
                continue
            match = cls._CONCLUSION_VALUE_PATTERN.search(source_text)
            if match is None:
                continue
            symbol, number, unit = match.groups()
            number = number.replace(",", ".")
            return f"{symbol} = {number} {unit}".strip() if unit else f"{symbol} = {number}"
        return None

    @staticmethod
    def _compute_canonical_form(formula: str | None) -> str | None:
        """
        §2ter (Phase 3b) — forme canonique déterministe, jamais un jugement
        LLM. Notation standard : sympify/simplify, gère aussi une égalité
        simple ("A = L*l" -> sympy.Eq). Notation LaTeX : repli sur
        _parse_math_expr, qui gère l'égalité NATIVEMENT (latex2sympy2_
        extended reconnaît directement "A = B", pas besoin de découper sur
        "=" comme pour sympify) — d'où la branche séparée ci-dessous. Une
        formule qui échoue à la tentative retenue (LaTeX invalide, contenu
        \text{} sans expression symbolique exploitable, etc.) retourne
        None comme tout échec de parsing — jamais une exception, aucun des
        deux chemins n'est fiable à 100% sur du texte libre.
        """
        if not formula:
            return None
        cleaned = formula.strip()
        try:
            if "\\" in cleaned:
                expr = ExtractionVerificationAgent._parse_math_expr(cleaned)
            elif cleaned.count("=") == 1:
                lhs_raw, rhs_raw = cleaned.split("=")
                expr = sympy.Eq(
                    ExtractionVerificationAgent._parse_math_expr(lhs_raw),
                    ExtractionVerificationAgent._parse_math_expr(rhs_raw),
                )
            else:
                expr = ExtractionVerificationAgent._parse_math_expr(cleaned)
            return str(sympy.simplify(expr))
        except Exception:
            return None

    _LATEX_TEXT_RE = re.compile(r"\\text\{([^{}]*)\}")
    _LATEX_FRAC_RE = re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}")
    _LATEX_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")

    @staticmethod
    def _normalize_latex_for_units(text: str) -> str:
        r"""
        Prétraitement borné, pas un parseur LaTeX complet — pint n'a besoin
        ici que de reconnaître un nombre + une unité littérale (ex.
        "28 \\text{ kN}"), jamais d'évaluer une expression symbolique. Gère
        les 4 formes de bruit LaTeX réellement observées dans les
        corrections testées : \\text{...} (unité en mode texte, on garde le
        contenu), \\frac{a}{b} (imbrication superficielle, suffisant pour
        un ratio d'unités — pas de récursion générale comme sympy, inutile
        ici), \\cdot/\\times (multiplication), et la virgule décimale
        française. Tout le reste (symboles grecs, indices, contenu
        purement algébrique sans unité littérale des deux côtés) n'est PAS
        transformé : ça reste un échec pint normal, "not_checkable" — pas
        une régression, juste une formule où aucune unité concrète n'était
        de toute façon extractible.
        """
        for _ in range(3):
            new_text = ExtractionVerificationAgent._LATEX_FRAC_RE.sub(r"((\1)/(\2))", text)
            if new_text == text:
                break
            text = new_text
        text = ExtractionVerificationAgent._LATEX_TEXT_RE.sub(r"\1", text)
        text = text.replace("\\cdot", "*").replace("\\times", "*")
        text = ExtractionVerificationAgent._LATEX_DECIMAL_COMMA_RE.sub(".", text)
        return text

    @staticmethod
    def _compute_dimensional_check(
        formula: str | None, description: str,
    ) -> Literal["consistent", "inconsistent", "not_checkable"] | None:
        """
        §2ter (Phase 3b) — vérification dimensionnelle déterministe via pint
        sur une égalité extraite de formula (repli sur description), après
        normalisation bornée du bruit LaTeX courant (_normalize_latex_for_
        units). None si non tenté (rien d'exploitable), "not_checkable" si
        tenté mais aucune unité extractible — jamais bloquant. Limite
        connue, assumée : pint peut interpréter un symbole algébrique isolé
        comme une unité (ex. "A" = ampère, "P" = poise) — signal indicatif,
        jamais une vérité absolue.
        """
        if not ExtractionVerificationAgent._looks_like_equation(formula, description):
            return "not_checkable"

        text = (formula or description or "").strip()
        lhs_raw, rhs_raw = text.split("=")
        lhs_raw = ExtractionVerificationAgent._normalize_latex_for_units(lhs_raw)
        rhs_raw = ExtractionVerificationAgent._normalize_latex_for_units(rhs_raw)
        registry = pint.UnitRegistry()
        try:
            lhs_qty = registry.Quantity(lhs_raw.strip())
            rhs_qty = registry.Quantity(rhs_raw.strip())
        except Exception:
            # pint délègue une partie de son parsing au tokenizer standard
            # de Python : du texte non-unité (LaTeX, prose, symboles isolés)
            # peut donc lever autre chose qu'un pint.errors.PintError —
            # AssertionError et tokenize.TokenError observés en pratique,
            # pas seulement les erreurs documentées de pint. Capture large
            # assumée ici : même contrat que sympy juste au-dessus, aucun
            # échec de parsing ne doit jamais remonter comme exception.
            return "not_checkable"

        return "consistent" if lhs_qty.dimensionality == rhs_qty.dimensionality else "inconsistent"

    @staticmethod
    def _looks_like_equation(formula: str | None, description: str | None) -> bool:
        """
        Partagé par _compute_dimensional_check et par la formalisation Phase 4
        (_build_dimensional_check_failure_clarification) : une égalité
        structurellement présente ("A = B", un seul "=") signifie qu'une unité
        semblait réellement pertinente ici, contrairement à une étape sans
        aucune structure d'égalité (ex. texte purement descriptif).
        """
        text = (formula or description or "").strip()
        return bool(text) and text.count("=") == 1


    # ------------------------------------------------------------------
    # Phase 4 (§2quater) — Formalisation des signaux d'incertitude déjà
    # produits par les phases 1/2/3a/3b en ClarificationRequest. Texte
    # formaté déterministe (f-string), jamais un appel LLM supplémentaire —
    # toute l'information nécessaire existe déjà dans les structures
    # produites par les phases précédentes.
    # ------------------------------------------------------------------

    @staticmethod
    def _build_calculation_anomaly_clarification(
        question: QuestionInput, index: int, step: ReasoningStepOutput,
    ) -> ClarificationRequest:
        """
        Phase 1 — anomalie de calcul isolée (hors récurrence, cf. l'instantané
        pris dans _decompose_steps avant _check_recurrence_completeness) :
        la démonstration reste globalement utilisable, mais le professeur
        doit être alerté explicitement — WARNING, jamais BLOCKING.
        """
        return ClarificationRequest(
            related_field=f"steps[{index}].anomaly_justification",
            agent_question=(
                f"L'étape {index + 1} de la question {question.order} "
                f"(« {step.description} ») présente une anomalie potentielle : "
                f"{step.anomaly_justification} Cette étape est-elle correcte telle quelle ?"
            ),
            proposed_answer=None,
            severity=ClarificationSeverity.WARNING,
        )

    @staticmethod
    def _build_sympy_failure_clarification(
        question: QuestionInput, index: int, step: ReasoningStepOutput,
    ) -> ClarificationRequest:
        """
        Phase 3b — canonical_form=None après tentative sympy sur une formule
        de conclusion réellement présente : rien n'indique un problème dans
        la correction, seul l'outil de double-vérification n'a pas pu
        confirmer — INFORMATIONAL, simple trace pour le suivi qualité.
        """
        return ClarificationRequest(
            related_field=f"steps[{index}].canonical_form",
            agent_question=(
                f"La conclusion de la question {question.order} contient une formule "
                f"(« {step.formula} ») que l'outil de vérification symbolique n'a pas pu "
                f"interpréter automatiquement. Aucune action requise — signalé pour le "
                f"suivi qualité."
            ),
            proposed_answer=None,
            severity=ClarificationSeverity.INFORMATIONAL,
        )

    @staticmethod
    def _build_dimensional_check_failure_clarification(
        question: QuestionInput, index: int, step: ReasoningStepOutput,
    ) -> ClarificationRequest:
        """
        Phase 3b — dimensional_check_result="not_checkable" alors qu'une
        égalité était structurellement présente (_looks_like_equation) : une
        unité semblait pertinente ici, contrairement aux étapes de calcul
        purement numériques/algébriques qui n'en génèrent jamais — INFORMATIONAL.
        """
        source = step.formula or step.description
        return ClarificationRequest(
            related_field=f"steps[{index}].dimensional_check_result",
            agent_question=(
                f"L'étape de calcul {index + 1} de la question {question.order} "
                f"(« {source} ») n'a pas pu être vérifiée dimensionnellement "
                f"automatiquement — unité non reconnue par l'outil. Aucune action "
                f"requise — signalé pour le suivi qualité."
            ),
            proposed_answer=None,
            severity=ClarificationSeverity.INFORMATIONAL,
        )

    @staticmethod
    def _build_low_confidence_attachment_clarification(
        question: QuestionInput, block_count: int,
    ) -> ClarificationRequest:
        """
        Signal déterministe, jamais un jugement LLM : au moins un des blocs
        de correction rattachés à cette question par Document_Structuring_
        Agent porte evidence_level=CONTENT_MATCHED (aucun label explicite,
        rattachement inféré par similarité de contenu parmi PLUSIEURS
        Questions candidates — cf. teacher_correction_block.py). La
        décomposition/le barème de cette question reposent donc en partie
        sur un rattachement moins sûr qu'un label explicite ou qu'un
        rattachement à candidat unique (INFERRED_SINGLE_QUESTION, jamais
        signalé ici : aucune ambiguïté réelle dans ce cas). INFORMATIONAL,
        jamais bloquant — le professeur reste libre de confirmer tel quel.
        """
        return ClarificationRequest(
            related_field="blocks.evidence_level",
            agent_question=(
                f"{block_count} bloc(s) de correction rattaché(s) à la question {question.order} "
                f"l'ont été par inférence de contenu (aucun label explicite, plusieurs questions "
                f"candidates) plutôt que par un label explicite. Vérifiez que ce rattachement est "
                f"correct avant de valider la décomposition/le barème de cette question."
            ),
            proposed_answer=None,
            severity=ClarificationSeverity.INFORMATIONAL,
        )

    @staticmethod
    def _build_missing_subquestion_content_clarification(
        question: QuestionInput, missing_ids: list[str],
    ) -> ClarificationRequest:
        """
        Couche 2 (backlog_bugs_c2pct.md, B1, 2026-08-29) — écart détecté
        MÉCANIQUEMENT (comparaison d'ensembles covered_subquestions vs
        segments vérifiés verbatim, cf. _extract_subquestion_segments),
        jamais un jugement LLM. Signal concret de perte probable à l'OCR
        (réponse courte isolée, tableau à colonnes parallèles...) — WARNING,
        jamais BLOCKING : la notation automatique s'appuie sur
        SolutionVariant.content (mécanisme indépendant, jamais affecté par
        cet écart), seul l'affichage structuré par sous-question
        (Question.subquestions) est incomplet pour le professeur.
        """
        labels = ", ".join(
            f'"{sq_id}" ({sq.label})' if (sq := find_subquestion_by_id(sq_id)) else f'"{sq_id}"'
            for sq_id in sorted(missing_ids)
        )
        return ClarificationRequest(
            related_field="subquestions",
            agent_question=(
                f"La question {question.order} couvre les sous-questions C2PCT {labels}, mais "
                f"leur contenu n'a pas pu être localisé de façon certaine dans le texte source "
                f"(possible perte à l'extraction OCR, ex. réponse courte isolée ou tableau à "
                f"colonnes parallèles). Vérifiez manuellement si ce contenu existe dans le "
                f"document original."
            ),
            proposed_answer=None,
            severity=ClarificationSeverity.WARNING,
        )

    @staticmethod
    def _build_bareme_clarification(
        question: QuestionInput, bareme: BaremeResult,
    ) -> ClarificationRequest:
        """
        Phase 1, Cas 2 (GLOBAL_PROPOSED) — une répartition proposée n'est
        jamais appliquée automatiquement : BLOCKING, une note réelle ne doit
        jamais reposer sur une répartition non confirmée par le professeur.
        """
        distribution = ", ".join(f"{c.label.capitalize()} {c.points}" for c in bareme.criteria)
        return ClarificationRequest(
            related_field="bareme.criteria",
            agent_question=(
                f"Le barème de la question {question.order} ({bareme.total_points} points) "
                f"n'est pas détaillé par critère dans votre correction. Voici la répartition "
                f"proposée : {distribution}. Confirmez-vous ?"
            ),
            proposed_answer=distribution,
            severity=ClarificationSeverity.BLOCKING,
        )

    @staticmethod
    def _build_missing_bareme_clarification(
        question: QuestionInput, bareme_error: str,
    ) -> ClarificationRequest:
        """
        Barème introuvable (ni chiffre de notation classique dans la
        correction, ni barème C2PCT natif par sous-questions pour cette
        question) — BLOCKING : sans l'un des deux mécanismes, aucune note
        n'est structurellement calculable pour cette question (cf. garde
        symétrique dans comparative_evaluation_node.py et Exercise Service.
        _check_completeness()). Contrairement à _build_bareme_clarification
        (Cas 2, une répartition EXISTE mais reste à confirmer), ici rien
        n'a pu être proposé du tout — proposed_answer reste None, jamais
        une répartition inventée.
        """
        return ClarificationRequest(
            related_field="bareme",
            agent_question=(
                f"Aucun barème n'a pu être établi pour la question {question.order} "
                f"({bareme_error}). Merci de fournir un barème (points par critère, ou "
                f"répartition par sous-question C2PCT) avant de pouvoir noter cette question."
            ),
            proposed_answer=None,
            severity=ClarificationSeverity.BLOCKING,
        )

    @staticmethod
    def _build_test_case_based_incomplete_clarification(
        question: QuestionInput, criterion: BaremeCriterionProposal,
    ) -> ClarificationRequest:
        """
        Phase 5B — critère classé test_case_based mais aucun code de
        référence ni cas de test extractible (spécification purement
        textuelle, ex. "la fonction doit trier un tableau") : BLOCKING, pas
        WARNING. Contrairement à l'anomalie de calcul isolée (où la
        démonstration reste utilisable malgré le défaut ponctuel), le mode
        test_case_based existe précisément pour qu'une future évaluation
        automatique exécute des cas de test contre la réponse de l'étudiant
        — sans aucun TestCase ni reference_code, il n'y a littéralement rien
        à exécuter. Le mécanisme de notation de ce critère n'a aucune donnée
        pour fonctionner tant que le professeur n'a pas fourni au moins un
        exemple entrée/sortie.
        """
        return ClarificationRequest(
            related_field=f"bareme.criteria[{criterion.label}].test_cases",
            agent_question=(
                f"Le critère « {criterion.label} » de la question {question.order} est en mode "
                f"test automatique (test_case_based), mais aucun cas de test ni code de "
                f"référence n'a pu être extrait de votre correction. Merci de fournir au moins "
                f"un exemple entrée / sortie attendue."
            ),
            proposed_answer=None,
            severity=ClarificationSeverity.BLOCKING,
        )

    # ------------------------------------------------------------------
    # Barème — Cas 3 (regex) puis Cas 1/2 (2e appel LLM, retry métier 1 essai)
    # ------------------------------------------------------------------

    @classmethod
    def _has_any_point_amount(cls, text: str) -> bool:
        return bool(cls._POINT_PATTERN.search(text or ""))

    @classmethod
    def _check_bareme_presence(cls, question_id: uuid.UUID, correction_text: str) -> None:
        """
        Cas 3 (§2) — seule partie de la logique de barème confiée à un regex :
        un pattern texte peut fiablement détecter qu'un chiffre de notation
        existe quelque part, jamais à quel critère il appartient (§ci-dessous).
        """
        if not cls._has_any_point_amount(correction_text):
            raise MissingBaremeError(question_id)

    async def _extract_or_propose_bareme(
        self,
        question: QuestionInput,
        bareme_text: str,
        decomposition: list[ReasoningStepOutput],
        context: AgentExecutionContext,
    ) -> BaremeResult:
        """
        Cas 1 (DETAILED) et Cas 2 (GLOBAL_PROPOSED) — le rattachement
        montant→critère (Cas 1) et la répartition proposée (Cas 2) passent
        tous les deux par le LLM, jamais par un pattern texte : un regex ne
        peut pas comprendre à quel critère un montant est rattaché, et une
        répartition Cas 2 doit s'appuyer sur la décomposition déjà produite
        (jamais un total/4 mécanique).
        """
        decomposition_summary = (
            "\n".join(
                f"- [{s.step_type.value}] {s.description}"
                + (f" (ANOMALIE : {s.anomaly_justification})" if s.anomaly_detected else "")
                for s in decomposition
            )
            or "(aucune étape produite)"
        )

        user_msg = BAREME_USER_TEMPLATE.format(
            statement=question.statement,
            bareme_text=bareme_text,
            decomposition_summary=decomposition_summary,
        )
        messages = [
            {"role": "system", "content": BAREME_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        last_error = ""
        for attempt in range(2):
            try:
                result, spec, fallback, _tokens = await invoke_llm_with_fallback(
                    task_type=TaskType.EXTRACTION_VERIFICATION,
                    messages=messages,
                    response_schema=_BaremeSchema,
                    context=context,
                )
            except Exception as e:
                last_error = str(e)
                if attempt == 0:
                    continue
                raise BaremeExtractionSchemaError(question.question_id, last_error) from e

            if not result.criteria:
                if attempt == 0:
                    continue
                raise BaremeExtractionSchemaError(question.question_id, "criteria manquant ou vide")

            # Chaque critère individuel, y compris son correction_mode (Phase 2) —
            # échec distinct de la forme barème (déjà validée par le schéma structuré).
            try:
                criteria = [self._criterion_from_schema(c) for c in result.criteria]
            except (KeyError, ValueError, TypeError, InvalidOperation) as e:
                if attempt == 0:
                    continue
                raise ModeClassificationSchemaError(question.question_id, str(e)) from e

            status: Literal["READY", "PENDING_REVIEW"] = (
                "READY" if result.case == "DETAILED" else "PENDING_REVIEW"
            )
            return BaremeResult(
                case=result.case, total_points=self._clean_decimal(result.total_points),
                criteria=criteria, status=status,
                model_version=self._format_model_version(spec, fallback),
                general_rules=[r.strip() for r in result.general_rules if r and r.strip()],
            )

        raise BaremeExtractionSchemaError(question.question_id, last_error)

    # ------------------------------------------------------------------
    # Barème C2PCT natif — Cas 0 (prioritaire), UN SEUL appel pour tout
    # l'exercice, jamais par question (cf. docstring module et prompts).
    # ------------------------------------------------------------------

    async def _extract_subquestion_points(
        self,
        questions: list[QuestionInput],
        full_document_text: str,
        context: AgentExecutionContext,
    ) -> tuple[dict[uuid.UUID, dict[str, Decimal]], list[str]]:
        """
        Cas 0 — best-effort, jamais bloquant : contrairement à Cas 1/2/3
        (BaremeExtractionSchemaError bloque la question), un échec ici ne
        fait JAMAIS échouer l'extraction — Pedagogical_Evaluation_Agent sait
        déjà retomber sur le calcul proportionnel quand rien n'est trouvé
        (comportement identique à avant ce chantier). Un WARNING est loggé,
        jamais une exception propagée.

        Pré-filtre déterministe avant l'appel LLM, OU logique entre deux
        motifs indépendants (cf. docstrings de _SUBQUESTION_POINTS_
        CANDIDATE_PATTERN et _C2PCT_METHODOLOGY_MENTION_PATTERN) : ni
        numérotation "chiffre.chiffre", ni mention explicite de la
        méthodologie C2PCT/Chaabi nulle part dans le document entier ->
        aucune section de barème C2PCT plausible, appel évité.

        Retourne (subquestion_points par question, règles générales du
        barème C2PCT — portée document entier, cf. QuestionVerificationResult.
        general_rules) — ([], []) équivalent si Cas 0 ne s'est pas déclenché
        ou n'a rien trouvé.
        """
        if not (
            self._SUBQUESTION_POINTS_CANDIDATE_PATTERN.search(full_document_text or "")
            or self._C2PCT_METHODOLOGY_MENTION_PATTERN.search(full_document_text or "")
        ):
            return {}, []

        order_to_id = {q.order: q.question_id for q in questions}
        question_orders = ", ".join(str(q.order) for q in sorted(questions, key=lambda q: q.order))

        user_msg = SUBQUESTION_POINTS_USER_TEMPLATE.format(
            question_orders=question_orders,
            full_document_text=full_document_text,
        )
        messages = [
            {"role": "system", "content": SUBQUESTION_POINTS_SYSTEM_PROMPT + "\n\n" + self._SUBQUESTIONS_REFERENCE_BLOCK},
            {"role": "user", "content": user_msg},
        ]

        for attempt in range(2):
            try:
                result, _spec, _fallback, _tokens = await invoke_llm_with_fallback(
                    task_type=TaskType.EXTRACTION_VERIFICATION,
                    messages=messages,
                    response_schema=_SubquestionPointsSchema,
                    context=context,
                )
            except Exception as e:
                if attempt == 0:
                    continue
                logger.warning(
                    f"Cas 0 (barème C2PCT natif) — échec LLM pour l'exercice, "
                    f"ignoré (best-effort, jamais bloquant) : {e}"
                )
                return {}, []

            by_question: dict[uuid.UUID, dict[str, Decimal]] = {}
            for group in result.questions:
                question_id = order_to_id.get(group.question_order)
                if question_id is None:
                    # Jamais un numéro de question hors de cet exercice —
                    # ignoré silencieusement, pas un échec de tout le résultat.
                    continue

                points: dict[str, Decimal] = {}
                for sq_id, amount in group.subquestion_points.items():
                    # Garde-fou anti-hallucination — même principe que
                    # covered_subquestions : tout id hors des 15 officiels
                    # est rejeté individuellement, jamais un échec global.
                    if sq_id not in self._ALL_SUBQUESTION_IDS:
                        continue
                    try:
                        points[sq_id] = self._clean_decimal(amount)
                    except (InvalidOperation, TypeError):
                        continue

                if points:
                    by_question[question_id] = points

            general_rules = [r.strip() for r in result.general_rules if r and r.strip()]
            return by_question, general_rules

        return {}, []

    async def _extract_subquestion_segments(
        self,
        question: QuestionInput,
        correction_text: str,
        covered_subquestions: list[str],
        context: AgentExecutionContext,
    ) -> list[SubquestionSegment] | None:
        """
        2026-08-29 (backlog_bugs_c2pct.md) — best-effort, jamais bloquant,
        même discipline que _extract_subquestion_points : un échec ici ne
        doit jamais faire échouer toute la vérification d'extraction.
        Appel évité entièrement si covered_subquestions est vide (rien à
        segmenter, pas la peine de payer un appel LLM).

        `covered_subquestions` est REÇU, jamais redemandé : cet appel ne
        fait qu'une chose, localiser le texte de chaque id déjà confirmé —
        jamais redécider quels ids sont couverts (cf. docstring prompt).
        """
        if not covered_subquestions:
            return None

        user_msg = SUBQUESTION_SEGMENTATION_USER_TEMPLATE.format(
            covered_ids=", ".join(sorted(covered_subquestions)),
            statement=question.statement,
            correction_text=correction_text,
        )
        messages = [
            {"role": "system", "content": SUBQUESTION_SEGMENTATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        for attempt in range(2):
            try:
                result, _spec, _fallback, _tokens = await invoke_llm_with_fallback(
                    task_type=TaskType.EXTRACTION_VERIFICATION,
                    messages=messages,
                    response_schema=_SubquestionSegmentationSchema,
                    context=context,
                )
            except Exception as e:
                if attempt == 0:
                    continue
                logger.warning(
                    f"Segmentation par sous-question — échec LLM pour la question "
                    f"{question.question_id}, ignorée (best-effort, jamais bloquant) : {e}"
                )
                return None

            covered_set = set(covered_subquestions)
            source_text = f"{question.statement}\n{correction_text}"
            segments: list[SubquestionSegment] = []
            for raw_segment in result.segments:
                # Garde-fou anti-hallucination — même principe que
                # covered_subquestions/subquestion_points : tout id hors de
                # la liste déjà confirmée est rejeté individuellement,
                # jamais un échec global de la segmentation.
                if raw_segment.id not in covered_set:
                    continue
                verified_content = self._find_verbatim_span(raw_segment.content, source_text)
                if verified_content is None:
                    logger.warning(
                        f"Segmentation par sous-question {raw_segment.id} (question "
                        f"{question.question_id}) — extrait non retrouvé verbatim dans "
                        f"la source (au-delà de la tolérance espaces/casse), rejeté."
                    )
                    continue
                segments.append(SubquestionSegment(id=raw_segment.id, content=verified_content))

            return segments or None

        return None

    @staticmethod
    def _find_verbatim_span(claimed: str, source_text: str) -> str | None:
        """
        Vérifie que `claimed` correspond réellement à un extrait de
        `source_text` — tolérance UNIQUEMENT sur les espaces/retours à la
        ligne (réduits à un seul espace, variabilité OCR déjà constatée
        cette session : espacement irrégulier, sauts de ligne parasites) et
        la casse, JAMAIS sur le contenu réel des mots (aucun fuzzy matching,
        aucune tolérance de paraphrase — chaque mot doit apparaître à
        l'identique). Retourne l'extrait EXACT tel qu'il apparaît dans
        source_text (jamais la version reformatée par le LLM, pour ne
        jamais introduire de dérive même minime) si trouvé, None sinon.
        """
        claimed = claimed.strip()
        if not claimed:
            return None

        tokens = re.split(r"\s+", claimed)
        pattern = r"\s+".join(re.escape(tok) for tok in tokens if tok)
        if not pattern:
            return None

        match = re.search(pattern, source_text, re.IGNORECASE)
        return match.group(0) if match else None

    @staticmethod
    def _clean_decimal(amount: float | int | str) -> Decimal:
        """
        Convertit un nombre (typiquement un champ structured-output typé
        float — cf. _BaremeSchema.total_points, _BaremeCriterionSchema.points,
        _SubquestionPointsGroupSchema.subquestion_points) en Decimal sans le
        ".0" parasite qu'un entier stocké en float produit systématiquement
        ("2 points" ne doit jamais s'afficher "2.0 points"). Comparaison par
        VALEUR (jamais par repr) : une vraie valeur fractionnaire (1.5)
        n'est jamais arrondie.
        """
        dec = Decimal(str(amount))
        if dec == dec.to_integral_value():
            return dec.to_integral_value()
        return dec

    @staticmethod
    def _criterion_from_schema(c: _BaremeCriterionSchema) -> BaremeCriterionProposal:
        mode = CorrectionMode(c.correction_mode)
        # Garde-fou anti-biais en code (pas seulement dans le prompt) :
        # verifiable_conditions n'existe que pour CRITERIA_BASED, quoi que
        # le LLM ait renvoyé pour les autres modes.
        verifiable_conditions = list(c.verifiable_conditions) if mode == CorrectionMode.CRITERIA_BASED else []

        # Phase 5B — même garde-fou, pour TEST_CASE_BASED : ces 3 champs
        # n'existent que pour ce mode, quoi que le LLM ait renvoyé sinon.
        test_cases: list[TestCase] = []
        reference_code: str | None = None
        expected_complexity: str | None = None
        if mode == CorrectionMode.TEST_CASE_BASED:
            test_cases = [
                TestCase(input=tc.input, expected_output=tc.expected_output, visibility=tc.visibility)
                for tc in c.test_cases
            ]
            reference_code = c.reference_code
            expected_complexity = c.expected_complexity

        # Même garde-fou anti-biais, pour RUBRIC_LEVELS/PROCEDURAL_SEQUENCE :
        # ces 2 champs n'existent que pour leur mode respectif, quoi que le
        # LLM ait renvoyé pour les autres modes.
        rubric_levels = (
            [{"level": lvl.level, "description": lvl.description} for lvl in c.rubric_levels]
            if mode == CorrectionMode.RUBRIC_LEVELS else []
        )
        expected_steps = list(c.expected_steps) if mode == CorrectionMode.PROCEDURAL_SEQUENCE else []

        return BaremeCriterionProposal(
            id=str(uuid.uuid4()),
            label=c.label,
            points=ExtractionVerificationAgent._clean_decimal(c.points),
            correction_mode=mode,
            verifiable_conditions=verifiable_conditions,
            disqualifying=c.disqualifying,
            test_cases=test_cases,
            reference_code=reference_code,
            expected_complexity=expected_complexity,
            rubric_levels=rubric_levels,
            expected_steps=expected_steps,
        )

    # ------------------------------------------------------------------
    # Dépendances inter-questions (Phase 3b, §2ter) — détection hybride,
    # marqueur textuel explicite seulement, aucun appel LLM dans cette phase.
    # ------------------------------------------------------------------

    @classmethod
    def _detect_cross_question_references(
        cls,
        questions: list[QuestionInput],
        texts_by_question: dict[uuid.UUID, str],
    ) -> dict[uuid.UUID, list[int]]:
        """
        Passe déterministe : regex pour l'extraction structurelle (numéro de
        question référencé, ou "question précédente"), rapidfuzz pour
        confirmer qu'un déclencheur de référence croisée entoure bien le
        numéro capturé (évite les faux positifs — ex. "Q2 = mc" sans
        déclencheur autour n'est jamais retenu). Cherche dans l'énoncé ET le
        texte de correction de la question (le marqueur peut apparaître dans
        l'un ou l'autre). Un ordre référencé doit exister réellement dans
        l'exercice et différer de l'ordre de la question elle-même, sinon
        ignoré silencieusement.
        """
        known_orders = {q.order for q in questions}
        result: dict[uuid.UUID, list[int]] = {}

        for question in questions:
            text = f"{question.statement}\n{texts_by_question.get(question.question_id, '')}"
            referenced: set[int] = set()

            if cls._PRECEDING_QUESTION_PATTERN.search(text) and (question.order - 1) in known_orders:
                referenced.add(question.order - 1)

            for match in cls._QUESTION_NUMBER_PATTERN.finditer(text):
                ref_order = int(match.group(1))
                if ref_order == question.order or ref_order not in known_orders:
                    continue
                window_start = max(0, match.start() - cls._CROSS_REF_WINDOW_CHARS)
                context = text[window_start:match.start()].lower()
                if any(
                    fuzz.partial_ratio(trigger, context) >= cls._CROSS_REF_FUZZY_THRESHOLD
                    for trigger in cls._CROSS_REF_TRIGGERS
                ):
                    referenced.add(ref_order)

            if referenced:
                result[question.question_id] = sorted(referenced)

        return result

    # ------------------------------------------------------------------
    # Utilitaires
    # ------------------------------------------------------------------

    @staticmethod
    def _combine_text(blocks: list[CorrectionBlockInput]) -> str:
        return "\n".join(b.raw_text for b in blocks if b.raw_text)

    @staticmethod
    def _format_model_version(spec, fallback: bool) -> str:
        """
        Phase 6 — même convention que Contestation_Verification_Agent
        (f"{spec.provider}:{spec.model_name}") : le fournisseur RÉEL utilisé,
        fallback d'infrastructure inclus, jamais une valeur statique/devinée.
        """
        base = f"{spec.provider}:{spec.model_name}"
        return f"{base}+fallback" if fallback else base
