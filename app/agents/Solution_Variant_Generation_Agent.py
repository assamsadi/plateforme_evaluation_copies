"""
Agent — Solution_Variant_Generation_Agent v1.12.

v1.12 (2026-08-28) — bug distinct de v1.10/v1.11 (dérivation manquante),
trouvé par relecture de code demandée par l'utilisateur AVANT tout nouveau
test réel : `content` (texte détaillé) et `steps_summary` (résumé structuré,
base du graphe affiché au professeur) sont produits par le MÊME appel LLM
(GeneratedVariantCandidateSchema), `content` étant généré AVANT `steps_
summary` dans l'ordre des champs — sur une variante déjà observée en test
réel (celle de v1.10/v1.11, méthode "énergétique de Castigliano"), `content`
décrivait fidèlement U = ΣN_i²L_i/(2EA_i) et un système de Cramer, mais
`steps_summary` résumait un équilibre nodal générique identique à la
référence, sans aucune trace d'énergie de déformation — pas systématique
(la variante "coupe de Ritter" générée dans les mêmes conditions est restée
cohérente), donc pas un défaut de câblage constant mais une perte de
cohérence interne du LLM sur les méthodes les plus élaborées.

Approche HYBRIDE retenue (arbitrage explicite avec l'utilisateur) plutôt
qu'un pur garde-fou de rejet (risque de boucler sur le même défaut
structurel à chaque retentative) ou qu'une génération systématique en deux
temps (double le coût même pour les candidates déjà cohérentes) :
  1. `_verify_steps_coherence` (1 appel LLM, quasi systématique) : détecte
     si `steps_summary` reflète réellement la méthode/les formules de
     `content` — jamais un rejet, seulement un signal.
  2. Si et SEULEMENT SI incohérent, `_regenerate_steps_from_content` (1
     appel LLM supplémentaire) : re-décompose `content` SEUL (déjà accepté,
     source de vérité) en un nouveau `steps_summary` — jamais une nouvelle
     génération complète, jamais un rejet de la candidate déjà validée par
     ailleurs (SymPy, distinction stratégique). Reprend la même exigence de
     `derivation` que v1.11 (règle 2 de STEPS_REDERIVATION_SYSTEM_PROMPT).
Coût borné et conditionnel : les candidates déjà cohérentes (ex. Ritter) ne
paient que le 1er appel de détection, jamais le second.

v1.11 (2026-08-28) — v1.10 (règle 6 du prompt, ci-dessous) n'a pas suffi :
constaté sur la variante générée JUSTE APRÈS le déploiement de v1.10 (coupe
de Ritter) que le LLM continue de donner `formula: "N_5 = 3P√5"` (le
résultat déjà connu, visible dans reference_content) SANS jamais poser
l'équation de moment ΣM=0 caractéristique de la méthode revendiquée — une
simple consigne textuelle, même appuyée d'un exemple concret bon/mauvais
dans le prompt, ne suffit pas à garantir la présence réelle d'une
dérivation (même limite déjà rencontrée sur ce fichier : cf. v1.7, "un
jugement sémantique n'est jamais fiablement obtenu par une simple
instruction"). Corrigé structurellement, pas par un nouveau paragraphe de
prompt :
  - `CandidateStepSummarySchema.derivation` (nouveau champ, schemas.py) :
    l'équation posée AVANT résolution, distincte de `formula` (le résultat).
  - Nouvelle vérification MÉCANIQUE (§1bis de execute(), jamais une simple
    consigne) : toute étape `formula_application`/`computation` sans
    `derivation` non vide est REJETÉE (nouveau statut REJECTED_NO_
    DERIVATION), avec retentative sur une autre stratégie — même discipline
    que REJECTED_SYMPY/REJECTED_INCONSISTENT juste au-dessus.
  - Persistance (solution_variant_generation_service.py) : `derivation` et
    `formula` combinés dans la colonne `ReasoningStep.formula` existante
    ("<dérivation> => <résultat>"), aucune migration nécessaire — le graphe
    affiché au professeur montre désormais la dérivation réelle.

v1.10 (2026-08-28) — 2 bugs trouvés en analysant un test réel (3 variantes
d'une même question de treillis, dont 2 IA convergeant vers les mêmes
valeurs numériques que la référence — attendu — mais l'une d'elles se
réclamant d'une "méthode énergétique de Castigliano/matricielle" alors que
sa seule étape de calcul réelle ("Résolution du système d'équilibre global
des nœuds") est l'équilibre nodal classique de la référence, juste reformulé
— et pourtant notée distinction_score=1.0, le score de distinction maximal) :
  1. `existing_variants` (service appelant) est filtré sur is_reference ==
     False AVANT d'atteindre l'agent — _verify_strategic_distinction ne
     voyait donc JAMAIS la solution du professeur, seulement les variantes
     IA déjà acceptées. Pire : pour la toute première variante IA d'une
     question, `current_existing` était vide, déclenchant le raccourci
     "aucun existant" -> distinction_score=1.0 automatique SANS AUCUNE
     comparaison, même pas avec la référence. Corrigé : `reference_steps`
     (déjà disponible dans execute(), déjà utilisé par la vérification de
     cohérence intermédiaire) est maintenant systématiquement injecté en
     tête de `current_existing` comme une entrée "Solution du professeur
     (référence)" — le raccourci "aucun existant" ne s'applique plus que si
     la référence elle-même n'a aucune étape décomposée.
  2. STRATEGIC_DISTINCTION_SYSTEM_PROMPT jugeait déjà sur les formules
     réelles des étapes (jamais le nom seul), mais rien n'empêchait le LLM
     de considérer un nom de méthode ("énergétique", "matricielle") comme
     une preuve suffisante de méthode distincte même quand aucune étape ne
     montre l'équation caractéristique de ce principe. Ajout d'une règle
     explicite : une méthode qui ne montre jamais l'équation propre au
     principe qu'elle revendique n'est pas distincte, jugée sur ce que les
     étapes font réellement, pas sur ce que le nom promet. Même règle
     symétrique côté génération (VARIANT_GENERATION_SYSTEM_PROMPT, règle 6,
     solution_variant_generation_prompt.py) : interdiction de "téléporter"
     un résultat déjà connu de la référence sans montrer, étape par étape,
     comment CETTE méthode précise y mène.

v1.9 (2026-08-17) — Face 2 du bug générique/spécialisé (N vs N_5) : v1.8
corrigeait le FAUX POSITIF (candidat correct rejeté à tort) mais laissait la
comparaison "NON VÉRIFIÉE" à chaque fois que les noms diffèrent — donc de
VRAIES solutions correctes ressortent marquées non vérifiées juste à cause
d'un nom de variable différent (utilisateur : "beaucoup de solutions
réellement correctes vont se retrouver marquées NON VÉRIFIÉE"). Diagnostic :
la donnée nécessaire pour établir une correspondance existait déjà
(ReasoningStep.description, chargée par le service mais jetée avant
d'atteindre l'agent qui ne recevait que reference_formulas: list[str] nu) ;
une correspondance purement déterministe (texte/dimension) ne suffit pas —
même limite structurelle que _compute_structural_distinction (v1.2-v1.6) :
"N et N_5 désignent-ils la même grandeur physique ici ?" est un jugement
sémantique, pas récupérable de façon fiable par nom/dimension seuls.

Ajouts :
  - `reference_formulas: list[str]` -> `reference_steps: list[
    ReferenceStepContext]` (formula + description) — plomberie réparée,
    aucune nouvelle extraction en amont nécessaire.
  - `_verify_intermediate_consistency` collecte désormais les grandeurs
    partagées (même LHS) dont le diff dépend de symboles exclusifs à un seul
    côté dans `ambiguous_pairs` (4ᵉ élément du tuple retourné) au lieu de les
    jeter silencieusement.
  - Nouvelle `_resolve_symbol_correspondences` (async, un seul appel LLM
    holistique par candidat, jamais paire par paire — même pattern que
    _verify_strategic_distinction) : voit TOUTES les paires ambiguës + le
    contexte complet (formule+description) des deux côtés. EXACTEMENT 3
    issues par paire, jamais confondues (exigence explicite utilisateur) :
      1. correspondance trouvée + cohérente -> verified_count += 1
      2. correspondance trouvée + désaccord réel -> verified_count += 1 ET
         conflit ajouté (rejet REJECTED_INCONSISTENT, motif citant la
         correspondance établie)
      3. correspondance non trouvée (LLM répond corresponds=false, ou
         couverture partielle des symboles exclusifs) -> NI l'un NI l'autre,
         reste NON VÉRIFIÉE exactement comme avant ce ticket.
    Garde-fous : le prompt impose `false` comme réponse sûre par défaut en
    cas de doute (une fausse correspondance positive validerait/
    invaliderait à tort le candidat, pire qu'une absence de réponse) ; une
    correspondance n'est retenue que si elle matche EXACTEMENT une paire
    proposée par le code (jamais une correspondance hors périmètre
    inventée) ; couverture exhaustive requise (tous les symboles exclusifs
    du candidat substitués, jamais une substitution partielle trompeuse) ;
    échec technique = toutes les paires traitées comme non résolues, jamais
    un blocage ni une invention.
  - Coût LLM : jusqu'à 1 appel supplémentaire par candidat (uniquement si
    des paires ambiguës existent), budgété par le MAX_LLM_CALLS existant
    (dégradation gracieuse déjà en place, jamais bloquant).

v1.8 (2026-08-17) — corrige un faux positif ET un gap de traçabilité dans
_verify_intermediate_consistency (v1.3), trouvés sur le test réel qui a suivi
v1.7 :
  1. Faux positif : référence "σ_max = N/A·ω" (N générique, jamais résolu
     ailleurs dans la référence) vs candidat "σ_max = N_5/A·ω" (N_5 nommé
     explicitement, cf. règle 5 du prompt v1.6) — sympy traite N et N_5 comme
     deux symboles indépendants, diff=ω(N-N_5)/A ≠ 0, rejeté à tort comme
     REJECTED_INCONSISTENT. C'est une différence de nommage générique/
     spécialisé de la RÉFÉRENCE elle-même, pas une erreur du candidat. A tué
     2 candidatures légitimes sur 3 dans ce test. Corrigé : un diff non nul
     n'est une vraie contradiction QUE s'il ne dépend que de symboles
     PARTAGÉS par les deux côtés (jamais de symboles exclusifs à un seul
     côté, jamais résolus l'un par rapport à l'autre).
  2. Gap de traçabilité (signalé par l'utilisateur en relisant ce fix) :
     is_consistent=True recouvrait deux cas radicalement différents sans les
     distinguer — "vérifié et confirmé cohérent" (≥1 grandeur partagée
     comparée avec succès) et "rien n'a pu être comparé" (0 grandeur
     partagée résolvable, ex. tout le candidat utilise des symboles absents
     de la référence). Un candidat jamais vérifié aurait pu porter
     silencieusement le même statut ACCEPTED, sans note, qu'un candidat
     réellement prouvé équivalent. _verify_intermediate_consistency retourne
     maintenant aussi verified_count ; VariantStrategyAttemptLog porte
     intermediate_verified_count + intermediate_check_note (jamais un simple
     bool interne muet), propagés jusqu'à structured_content, AgentDecisionLog
     et VariantReviewResponse (même surfaces que distinction_score, v1.3).

v1.7 (2026-08-17) — remplace ENTIÈREMENT _compute_structural_distinction
(score déterministe nom/séquence de step_type/concept_tags, v1.2/v1.4) par
_verify_strategic_distinction, un jugement LLM holistique. Trouvé peu fiable
sur 3 tests réels consécutifs, chacun avec un mode d'échec différent :
  1. Deux variantes nommées "travaux virtuels" jugées distinctes (0.64)
     tandis qu'une variante nommée "Castigliano" (même famille de méthode
     énergétique) était rejetée comme doublon (0.27) — le nom seul ne suffit
     jamais à juger une stratégie.
  2. Un nom identique à 100% (sous-ensemble exact de tokens) survivait quand
     même au seuil de rejet (0.36 > 0.35) grâce aux deux autres signaux —
     corrigé en v1.4 (nom comme plancher), mais symptomatique d'un problème
     de fond : sommer des scores de proxies textuels ne capture jamais
     fiablement "même stratégie ou non".
  3. Deux candidats aux formules concrètes QUASI-IDENTIQUES (même N_5, même
     σ_max, mêmes valeurs numériques) mais un nom différent jugés
     suffisamment distincts (0.41) — le score ignorait totalement le
     contenu des formules.
Le vrai critère ("est-ce que les deux stratégies de résolution sont
réellement différentes ?") est un jugement SÉMANTIQUE, jamais réductible à
une combinaison de scores texte/séquence — même pattern déjà rencontré et
résolu ainsi sur Document_Structuring_Agent cette session (une heuristique
par paire/bloc sans contexte partagé est systématiquement mise en défaut ;
un passage LLM holistique avec le contenu complet règle le problème). Un
seul appel LLM voit la candidate ET toutes les variantes existantes
ensemble (jamais paire par paire), juge le principe/la séquence/les
formules — jamais le nom seul.

v1.3 (2026-08-17) — la vérification mathématique ne portait que sur la
conclusion finale (_verify_mathematical_equivalence) : un LLM voit
reference_conclusion dans le prompt et peut la recopier telle quelle sans
que le raisonnement intermédiaire soit réellement dérivé — deux étapes
menant "par coïncidence" à la même conclusion via des grandeurs physiques
incompatibles n'étaient jamais détectées. Ajout de
_verify_intermediate_consistency : compare, pour CHAQUE grandeur (symbole
isolé à gauche d'une égalité, ex. "N_5", "σ_max") définie À LA FOIS dans la
référence (reference_formulas, nouveau paramètre d'execute()) et dans le
candidat, que les deux expressions sont symboliquement équivalentes — jamais
sur une grandeur propre au seul chemin du candidat (méthode alternative,
dérivation différente par construction). Bug trouvé en implémentant ceci :
_extract_sympy_expression (liste blanche stricte x/y/z, conçue pour extraire
un nombre final avec unités) détruisait un vrai nom de symbole en notation
standard ("N_5" -> "5") — nouveau _clean_symbol_or_expr, dédié, corrige ça
sans toucher au chemin déjà testé de _parse_conclusion_value.

Génère des méthodes alternatives de résolution réellement valides pour une Question.
Utilise SymPy pour la vérification d'équivalence mathématique de la conclusion
et un score de distinction structurelle (nom de stratégie + séquence de
step_type + concept_tags) par rapport aux variantes existantes.

v1.2 (2026-08-17) — trouvé sur le premier test réel (Gemini, document
complet) : deux variantes nommées "travaux virtuels" par le LLM étaient
jugées suffisamment distinctes (score 0.64) tandis qu'une variante nommée
"Castigliano" (une méthode énergétique différente) était rejetée comme
doublon (score 0.27) de l'une des deux "travaux virtuels" — le score ne
comparait que la séquence de step_type (position par position) et le
recouvrement de concept_tags (texte libre du LLM, sans vocabulaire
contrôlé), jamais le nom de la méthode elle-même — le signal le plus direct
pour juger si deux approches sont vraiment "la même". _compute_structural_
distinction construisait aussi un nx.DiGraph (G_cand) jamais utilisé —
retiré : CandidateStepSummarySchema n'a pas de depends_on_refs, la
"structure" candidate est toujours une simple chaîne linéaire, donc un vrai
algorithme de graphe (isomorphisme, distance d'édition) n'apporterait rien
de plus que la comparaison de séquence déjà faite tant que ce schéma reste
linéaire. Ajout d'un 3e signal, dominant : similarité du strategy_name
(rapidfuzz), rééquilibrage des poids.

v1.1 (2026-08-17) — 3 corrections trouvées par relecture de code AVANT tout
test réel (cf. mémoire de session), même pattern déjà rencontré/corrigé sur
Document_Structuring_Agent, Extraction_Verification_Agent et Reasoning_Graph_Agent :
  1. response_schema=None + re.search("\\{.*\\}",...) + json.loads : même bug
     JSON fragile déjà corrigé 3 fois cette session (LaTeX, ou result.content
     en liste chez certains providers) — passé en structured output.
  2. task_type=TaskType.REASONING_GRAPH au lieu de TaskType.
     SOLUTION_VARIANT_GENERATION (existe dans model_registry.models.TaskType,
     jamais utilisé) — routait cet agent sur la config LLM d'un autre agent.
  3. _extract_sympy_expression nettoyait le LaTeX par regex naïves (strip
     mots de 2+ lettres, remplace {}/^ à la main) — pour toute formule non
     triviale (ex. "\\frac{N}{A}") ça ne produit pas une expression invalide
     qui échoue proprement, ça produit une expression FAUSSE qui PARSE quand
     même ("\\frac{N}{A}" -> "NA", un symbole unique au lieu de N/A) : le
     candidat pouvait être rejeté à tort pour "invalidité mathématique" alors
     que le LaTeX était juste mal nettoyé — plus dangereux que Extraction_
     Verification_Agent (qui ne faisait que dégrader un signal, jamais
     bloquer). Remplacé par le même parseur LaTeX-aware (latex2sympy2_
     extended) déjà validé ce jour sur Extraction_Verification_Agent.
"""
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

import sympy as sp
from latex2sympy2_extended.latex2sympy2 import ConversionConfig, latex2sympy
from latex2sympy2_extended.math_normalization import NormalizationConfig
from pydantic import BaseModel, Field

from app.agents.context import AgentExecutionContext
from app.domain.schemas.solution_variant_generation_schemas import (
    CandidateStepSummarySchema,
    GeneratedVariantCandidateSchema,
    ReferenceStepContext,
    VariantGenerationAgentReport,
    VariantStrategyAttemptLog,
)
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType
from app.observability.langfuse import AgentTraceSpan
from app.prompts.solution_variant_generation_prompt import (
    HINTS_TEMPLATE,
    LATEX_CORRUPTION_RETRY_TEMPLATE,
    PROFESSOR_REJECTION_FEEDBACK_TEMPLATE,
    REJECTED_FEEDBACK_TEMPLATE,
    STEPS_COHERENCE_SYSTEM_PROMPT,
    STEPS_COHERENCE_USER_TEMPLATE,
    STEPS_REDERIVATION_SYSTEM_PROMPT,
    STEPS_REDERIVATION_USER_TEMPLATE,
    STRATEGIC_DISTINCTION_SYSTEM_PROMPT,
    STRATEGIC_DISTINCTION_USER_TEMPLATE,
    STUDENT_CANDIDATE_TEMPLATE,
    SYMBOL_CORRESPONDENCE_SYSTEM_PROMPT,
    SYMBOL_CORRESPONDENCE_USER_TEMPLATE,
    VARIANT_GENERATION_SYSTEM_PROMPT,
    VARIANT_GENERATION_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


class _StrategicDistinctionSchema(BaseModel):
    """
    Sortie structurée de _verify_strategic_distinction (v1.7) — jugement LLM
    holistique remplaçant le score déterministe nom/séquence/tags (cf.
    docstring module). is_distinct=False n'est jamais recalculé/pondéré
    davantage côté code : c'est le jugement final, contrairement à l'ancien
    score numérique comparé à un seuil arbitraire (0.35).
    """
    is_distinct: bool
    most_similar_existing_index: int | None = None
    distinction_score: float = Field(ge=0.0, le=1.0, default=1.0)
    justification: str


@dataclass
class _AmbiguousSymbolPair:
    """
    Grandeur partagée (même LHS des deux côtés, ex. "σ_max") dont le diff
    dépend de symboles exclusifs à un seul côté (ex. "N" côté référence,
    "N_5" côté candidat) — purement interne à ce module (jamais sérialisé),
    porte directement les objets sympy vivants plutôt que leur str() pour
    éviter tout risque de reparsing incohérent lors de la résolution par
    correspondance sémantique (v1.9, cf. docstring module).
    """
    shared_symbol: str
    reference_expr: sp.Expr
    candidate_expr: sp.Expr
    reference_exclusive_symbols: list[str] = field(default_factory=list)
    candidate_exclusive_symbols: list[str] = field(default_factory=list)


class _SymbolCorrespondenceEntrySchema(BaseModel):
    reference_symbol: str
    candidate_symbol: str
    corresponds: bool
    justification: str


class _SymbolCorrespondenceSchema(BaseModel):
    """
    Sortie structurée de _resolve_symbol_correspondences (v1.9). `corresponds`
    est un booléen strict, jamais un score — `false` est le choix sûr par
    défaut imposé par le prompt (cf. SYMBOL_CORRESPONDENCE_SYSTEM_PROMPT) :
    une fausse correspondance positive serait ensuite utilisée pour valider/
    invalider mathématiquement le candidat, donc pire qu'une absence de
    réponse.
    """
    correspondences: list[_SymbolCorrespondenceEntrySchema] = Field(default_factory=list)


class _StepsCoherenceSchema(BaseModel):
    """
    Sortie de _verify_steps_coherence (v1.12) — détecte une divergence entre
    `content` (texte détaillé, source de vérité) et `steps_summary` (résumé
    structuré), les deux produits par le MÊME appel LLM mais pas toujours
    mutuellement cohérents (cf. docstring module, section v1.12). Booléen
    strict, jamais un score — même discipline que _SymbolCorrespondenceEntrySchema.corresponds.
    """
    is_coherent: bool
    justification: str


class _StepsRederivationSchema(BaseModel):
    """
    Sortie de _regenerate_steps_from_content (v1.12) — re-décomposition
    CIBLÉE de `content` en `steps_summary`, déclenchée uniquement si
    _StepsCoherenceSchema.is_coherent=False. `content` sert de SEULE source
    de vérité (jamais la méthode reformulée à nouveau), pour ne plus jamais
    dépendre de la cohérence interne d'un unique appel générant les deux à
    la fois.
    """
    steps_summary: list[CandidateStepSummarySchema] = Field(default_factory=list)


class SolutionVariantGenerationAgent:
    """Agent de génération de variantes de solution alternatives."""

    AGENT_NAME = "Solution_Variant_Generation_Agent"
    MAX_LLM_CALLS = 8
    MAX_STRATEGIES = 3

    async def execute(
        self,
        question_id: uuid.UUID,
        question_statement: str,
        reference_content: str,
        reference_conclusion: str,
        reference_steps: list[ReferenceStepContext] | None = None,
        existing_variants: list[dict] | None = None,
        academic_envelope: list[str] | set[str] | None = None,
        mandated_method: str | None = None,
        trigger_type: str = "proactive",
        student_candidate_method: str | None = None,
        method_hint: str | None = None,
        concept_hint: list[str] | None = None,
        context: AgentExecutionContext | None = None,
    ) -> VariantGenerationAgentReport:
        """
        Génère 0 à N variantes de solution alternatives pour la question spécifiée.
        """
        # 1. Précondition de saut immédiat : mandated_method renseigné en mode proactif
        if trigger_type == "proactive" and mandated_method and mandated_method.strip():
            logger.info(
                "Question %s possède une méthode imposée ('%s'). Génération proactive sautée.",
                question_id, mandated_method
            )
            return VariantGenerationAgentReport(
                question_id=question_id,
                candidates=[],
                attempt_logs=[],
                total_llm_calls=0,
                skipping_reason=f"mandated_method: {mandated_method}",
            )

        trace_id = context.trace_id if context else str(uuid.uuid4())
        span_metadata = {
            "flow_type": context.flow_type if context else "exercise_setup",
            "question_id": str(question_id),
            "trigger_type": trigger_type,
        }

        existing_variants = existing_variants or []
        academic_envelope_set = set(academic_envelope) if academic_envelope else set()
        # Entrée de comparaison pour la solution du professeur — le service
        # appelant filtre `existing_variants` sur is_reference == False
        # (comparaison de variantes IA entre elles), donc SANS ceci la
        # référence n'est JAMAIS vue par _verify_strategic_distinction. Bug
        # trouvé en test réel : la toute première variante IA d'une question
        # (current_existing vide à ce moment) recevait alors un
        # distinction_score=1.0 automatique ("aucun existant") sans jamais
        # être comparée à la référence — une méthode reformulant exactement
        # l'équilibre nodal du professeur sous un nom différent ("approche
        # énergétique/matricielle") passait ainsi avec le score maximal.
        reference_existing_entry = (
            {
                "strategy_name": "Solution du professeur (référence)",
                "reasoning_summary": reference_conclusion or None,
                "steps": [
                    {"order": idx, "step_type": "reference", "formula": rs.formula, "description": rs.description}
                    for idx, rs in enumerate(reference_steps, 1)
                ],
            }
            if reference_steps else None
        )

        attempt_logs: list[VariantStrategyAttemptLog] = []
        accepted_candidates: list[GeneratedVariantCandidateSchema] = []
        rejected_feedbacks: list[str] = []

        total_llm_calls = 0
        # Dernier fournisseur:modèle ayant réellement répondu — reporté sur
        # VariantGenerationAgentReport pour que le service appelant trace la
        # vraie provenance dans AgentDecisionLog, au lieu d'une chaîne codée
        # en dur ("groq:llama-3.3-70b") devenue fausse depuis la migration
        # de TaskType.SOLUTION_VARIANT_GENERATION vers Gemini (constaté en
        # test réel : Groq/OpenAI cassés sur ce compte, cf. registry.py).
        last_model_used: str | None = None

        with AgentTraceSpan(self.AGENT_NAME, trace_id=trace_id, metadata=span_metadata) as span:
            t_start = time.perf_counter()

            for strategy_idx in range(1, self.MAX_STRATEGIES + 1):
                if total_llm_calls >= self.MAX_LLM_CALLS:
                    logger.warning("Plafond d'appels LLM (%d) atteint pour la question %s", self.MAX_LLM_CALLS, question_id)
                    break

                # Construction du prompt avec ré-injection des rejets précédents
                rejected_section = ""
                if rejected_feedbacks:
                    rejected_section = REJECTED_FEEDBACK_TEMPLATE.format(
                        rejected_attempts="\n".join(f"- {fb}" for fb in rejected_feedbacks)
                    )

                # Rejets HUMAINS (professeur, review_variant_decision) — distinct de
                # rejected_feedbacks ci-dessus (boucle interne à CETTE exécution). Le
                # service appelant pose "status"/"review_comment" sur chaque entrée
                # d'existing_variants (cf. generate_variants_for_question) ; seules
                # celles réellement REJECTED avec un commentaire non vide comptent —
                # une variante rejetée sans commentaire n'apporte aucune leçon
                # exploitable, jamais affichée comme "Aucun" qui n'aiderait en rien.
                professor_rejections = [
                    f"- Stratégie « {ev.get('strategy_name') or '(sans nom)'} » : {ev.get('review_comment')}"
                    for ev in existing_variants
                    if ev.get("status") == "rejected" and ev.get("review_comment")
                ]
                professor_rejection_section = ""
                if professor_rejections:
                    professor_rejection_section = PROFESSOR_REJECTION_FEEDBACK_TEMPLATE.format(
                        professor_rejections="\n".join(professor_rejections)
                    )

                hints_section = ""
                if method_hint or concept_hint:
                    hints_section = HINTS_TEMPLATE.format(
                        method_hint=method_hint or "Aucun",
                        concept_hints=", ".join(concept_hint) if concept_hint else "Aucun",
                    )

                student_section = ""
                if student_candidate_method:
                    student_section = STUDENT_CANDIDATE_TEMPLATE.format(
                        student_candidate_method=student_candidate_method
                    )

                user_msg = VARIANT_GENERATION_USER_TEMPLATE.format(
                    question_statement=question_statement,
                    reference_content=reference_content,
                    reference_conclusion=reference_conclusion or "Non spécifiée",
                    rejected_feedback_section=rejected_section,
                    professor_rejection_section=professor_rejection_section,
                    hints_section=hints_section,
                    student_candidate_section=student_section,
                )

                messages = [
                    {"role": "system", "content": VARIANT_GENERATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ]

                # 1 Retry métier par stratégie en cas d'erreur de schéma Pydantic
                # (structured output — plus de parsing JSON manuel, cf. docstring
                # module v1.1).
                candidate_schema: GeneratedVariantCandidateSchema | None = None

                for attempt_in_strat in range(2):
                    if total_llm_calls >= self.MAX_LLM_CALLS:
                        break

                    total_llm_calls += 1
                    result, spec, fallback, _ = await invoke_llm_with_fallback(
                        task_type=TaskType.SOLUTION_VARIANT_GENERATION,
                        messages=messages,
                        response_schema=GeneratedVariantCandidateSchema,
                        context=context,
                    )
                    last_model_used = f"{spec.provider}:{spec.model_name}"

                    try:
                        candidate_schema = (
                            result if isinstance(result, GeneratedVariantCandidateSchema)
                            else GeneratedVariantCandidateSchema.model_validate(result)
                        )
                        break  # Parsing Pydantic réussi !
                    except Exception as exc:
                        logger.warning("Erreur de validation schéma pour stratégie %d (essai %d) : %s", strategy_idx, attempt_in_strat + 1, exc)
                        if attempt_in_strat == 0:
                            continue

                if candidate_schema is None:
                    attempt_logs.append(
                        VariantStrategyAttemptLog(
                            strategy_name=f"Stratégie #{strategy_idx}",
                            attempt_number=strategy_idx,
                            status="REJECTED_SCHEMA",
                            rejection_reason="Échec de génération JSON/schéma valide après retentative.",
                        )
                    )
                    rejected_feedbacks.append(f"Stratégie #{strategy_idx} : schéma JSON invalide.")
                    continue

                # 1quater. LaTeX corrompu dans `content` (règle 7, cf.
                # _detect_corrupted_latex_fragments) — irrécupérable une fois
                # le caractère de contrôle perdu (pas de tentative de
                # reconstruction), donc une seule relance ciblée (même
                # conversation, cf. LATEX_CORRUPTION_RETRY_TEMPLATE) puis
                # rejet mécanique si toujours corrompu, jamais une
                # persistance silencieuse.
                corrupted_fragments = self._detect_corrupted_latex_fragments(candidate_schema.content)
                if corrupted_fragments and total_llm_calls < self.MAX_LLM_CALLS:
                    logger.info(
                        "LaTeX corrompu détecté dans content pour '%s' (%s) — une relance ciblée.",
                        candidate_schema.strategy_name, corrupted_fragments,
                    )
                    total_llm_calls += 1
                    retry_messages = messages + [
                        {
                            "role": "user",
                            "content": LATEX_CORRUPTION_RETRY_TEMPLATE.format(
                                fragments=", ".join(corrupted_fragments)
                            ),
                        }
                    ]
                    try:
                        retry_result, retry_spec, _, _ = await invoke_llm_with_fallback(
                            task_type=TaskType.SOLUTION_VARIANT_GENERATION,
                            messages=retry_messages,
                            response_schema=GeneratedVariantCandidateSchema,
                            context=context,
                        )
                        retry_schema = (
                            retry_result if isinstance(retry_result, GeneratedVariantCandidateSchema)
                            else GeneratedVariantCandidateSchema.model_validate(retry_result)
                        )
                        retry_fragments = self._detect_corrupted_latex_fragments(retry_schema.content)
                        if not retry_fragments:
                            candidate_schema = retry_schema
                            last_model_used = f"{retry_spec.provider}:{retry_spec.model_name}"
                            corrupted_fragments = []
                        else:
                            corrupted_fragments = retry_fragments
                    except Exception as exc:
                        logger.warning(
                            "Relance après LaTeX corrompu a échoué (schéma) pour '%s' : %s",
                            candidate_schema.strategy_name, exc,
                        )

                if corrupted_fragments:
                    reason = (
                        f"content contient des fragments LaTeX corrompus après relecture "
                        f"(signatures détectées : {', '.join(corrupted_fragments)})."
                    )
                    attempt_logs.append(
                        VariantStrategyAttemptLog(
                            strategy_name=candidate_schema.strategy_name,
                            attempt_number=strategy_idx,
                            status="REJECTED_CORRUPTED_LATEX",
                            rejection_reason=reason,
                        )
                    )
                    rejected_feedbacks.append(
                        f"Méthode '{candidate_schema.strategy_name}' : rejetée — {reason}"
                    )
                    continue

                # 1ter. Cohérence steps_summary <-> content/strategy_name
                # (hybride, v1.12, cf. docstring module) : détection légère
                # d'abord, re-décomposition CIBLÉE (jamais un rejet total)
                # uniquement si une incohérence est réellement détectée —
                # coût borné, jamais payé pour les candidates déjà cohérentes
                # (ex. coupe de Ritter, restée fidèle en test réel).
                if total_llm_calls >= self.MAX_LLM_CALLS:
                    logger.warning(
                        "Plafond d'appels LLM (%d) atteint avant la vérification de cohérence "
                        "steps_summary/content pour '%s' — non vérifié.",
                        self.MAX_LLM_CALLS, candidate_schema.strategy_name,
                    )
                else:
                    total_llm_calls += 1
                    is_coherent, coherence_reason = await self._verify_steps_coherence(
                        candidate=candidate_schema, context=context,
                    )
                    if not is_coherent:
                        logger.info(
                            "steps_summary incohérent avec content pour '%s' (%s) — re-décomposition ciblée.",
                            candidate_schema.strategy_name, coherence_reason,
                        )
                        if total_llm_calls >= self.MAX_LLM_CALLS:
                            logger.warning(
                                "Plafond d'appels LLM (%d) atteint avant la re-décomposition pour '%s' — "
                                "steps_summary incohérent conservé tel quel.",
                                self.MAX_LLM_CALLS, candidate_schema.strategy_name,
                            )
                        else:
                            total_llm_calls += 1
                            candidate_schema.steps_summary = await self._regenerate_steps_from_content(
                                candidate=candidate_schema, context=context,
                            )

                # 1bis. Dérivation réelle requise (règle 6 du prompt) — jamais
                # laissé à la seule consigne textuelle : constaté 2 fois de
                # suite en test réel (v1.10 puis ce ticket) qu'un LLM, même
                # explicitement instruit, continue de recopier le résultat
                # final déjà connu (visible dans reference_content) comme
                # `formula` sans jamais poser l'équation caractéristique de
                # la méthode revendiquée. Rejet mécanique, jamais un simple
                # avertissement silencieux, pour toute étape formula_
                # application/computation dont `derivation` est absent/vide.
                steps_missing_derivation = [
                    s for s in candidate_schema.steps_summary
                    if s.step_type in ("formula_application", "computation")
                    and not (s.derivation and s.derivation.strip())
                ]
                if steps_missing_derivation:
                    orders = ", ".join(str(s.order) for s in steps_missing_derivation)
                    reason = (
                        f"Étape(s) {orders} (formula_application/computation) sans `derivation` : "
                        "le résultat est donné sans jamais poser l'équation caractéristique de la "
                        f"méthode revendiquée ('{candidate_schema.strategy_name}')."
                    )
                    attempt_logs.append(
                        VariantStrategyAttemptLog(
                            strategy_name=candidate_schema.strategy_name,
                            attempt_number=strategy_idx,
                            status="REJECTED_NO_DERIVATION",
                            rejection_reason=reason,
                        )
                    )
                    rejected_feedbacks.append(
                        f"Méthode '{candidate_schema.strategy_name}' : rejetée — {reason}"
                    )
                    continue

                # 2. Vérification symbolique SymPy (Équivalence mathématique de la conclusion)
                is_math_valid, math_reason = self._verify_mathematical_equivalence(
                    reference_conclusion=reference_conclusion,
                    candidate_conclusion=candidate_schema.conclusion_formula or candidate_schema.content,
                    reference_content=reference_content,
                    candidate_content=candidate_schema.content,
                )

                if not is_math_valid:
                    attempt_logs.append(
                        VariantStrategyAttemptLog(
                            strategy_name=candidate_schema.strategy_name,
                            attempt_number=strategy_idx,
                            status="REJECTED_SYMPY",
                            rejection_reason=math_reason,
                        )
                    )
                    rejected_feedbacks.append(
                        f"Méthode '{candidate_schema.strategy_name}' : rejetée pour invalidité mathématique ({math_reason})."
                    )
                    continue

                # 2bis. Vérification de cohérence des grandeurs INTERMÉDIAIRES
                # (pas seulement la conclusion finale) — cf. mémoire de
                # session : la conclusion seule ne suffit pas, un LLM voit
                # reference_conclusion dans le prompt et peut la recopier
                # sans que le raisonnement intermédiaire soit réellement
                # dérivé. Ne compare QUE les grandeurs qui apparaissent dans
                # LES DEUX (référence ET candidat) — un candidat suit un
                # chemin différent par construction (méthode alternative),
                # donc une grandeur propre à son seul chemin n'a rien à
                # comparer et n'est jamais un motif de rejet.
                is_consistent, conflicts, verified_count, ambiguous_pairs = self._verify_intermediate_consistency(
                    reference_steps=reference_steps or [],
                    candidate_steps=candidate_schema.steps_summary,
                )

                # 2ter. Résolution sémantique des grandeurs au nommage
                # ambigu (v1.9, cf. docstring module) — ex. "N" générique
                # côté référence vs "N_5" spécialisé côté candidat, jamais
                # comparables par sympy sans savoir qu'ils désignent la même
                # grandeur physique. Un seul appel LLM holistique par
                # candidat (jamais paire par paire), 3 issues distinctes :
                # correspondance trouvée+cohérente, correspondance trouvée+
                # désaccord réel (conflit ajouté), correspondance non trouvée
                # (reste NON VÉRIFIÉ, jamais compté ni comme succès ni comme
                # conflit).
                correspondence_note = ""
                if ambiguous_pairs:
                    if total_llm_calls >= self.MAX_LLM_CALLS:
                        correspondence_note = (
                            f"{len(ambiguous_pairs)} grandeur(s) au nommage ambigu jamais tentée(s) "
                            "(plafond d'appels LLM atteint) — restent NON VÉRIFIÉES."
                        )
                        logger.warning(
                            "Plafond d'appels LLM (%d) atteint avant la résolution de correspondance de "
                            "symboles pour '%s' (%d paire(s) ambiguë(s)).",
                            self.MAX_LLM_CALLS, candidate_schema.strategy_name, len(ambiguous_pairs),
                        )
                    else:
                        total_llm_calls += 1
                        llm_conflicts, resolved_count, correspondence_note = (
                            await self._resolve_symbol_correspondences(
                                ambiguous_pairs=ambiguous_pairs,
                                reference_steps=reference_steps or [],
                                candidate_steps=candidate_schema.steps_summary,
                                context=context,
                            )
                        )
                        conflicts = conflicts + llm_conflicts
                        verified_count += resolved_count

                is_consistent = len(conflicts) == 0
                if not is_consistent:
                    conflict_summary = "; ".join(conflicts)
                    attempt_logs.append(
                        VariantStrategyAttemptLog(
                            strategy_name=candidate_schema.strategy_name,
                            attempt_number=strategy_idx,
                            status="REJECTED_INCONSISTENT",
                            rejection_reason=conflict_summary,
                            intermediate_verified_count=verified_count,
                        )
                    )
                    rejected_feedbacks.append(
                        f"Méthode '{candidate_schema.strategy_name}' : rejetée pour incohérence entre grandeurs "
                        f"intermédiaires et la référence ({conflict_summary})."
                    )
                    continue

                # Jamais confondre "vérifié et cohérent" avec "rien n'a pu
                # être comparé" — les deux ressortent avec is_consistent=True
                # (aucun conflit trouvé) mais ne portent PAS la même valeur
                # probante ; la note explicite ci-dessous est persistée dans
                # le log ACCEPTED final pour que ça reste visible pour le
                # professeur (jamais un simple bool interne muet).
                if verified_count > 0:
                    intermediate_check_note = (
                        f"{verified_count} grandeur(s) intermédiaire(s) partagée(s) avec la référence "
                        f"vérifiée(s) et symboliquement cohérente(s)."
                    )
                else:
                    intermediate_check_note = (
                        "Cohérence intermédiaire NON VÉRIFIÉE : aucune grandeur partagée résolvable entre "
                        "la référence et ce candidat (noms de symboles disjoints ou formules non comparables) "
                        "— accepté sur la seule base de la conclusion finale et de la distinction stratégique."
                    )
                if correspondence_note:
                    intermediate_check_note = f"{intermediate_check_note} {correspondence_note}"

                # 3. Vérification de distinction STRATÉGIQUE — jugement LLM
                # holistique (v1.7, cf. docstring module), jamais un score
                # déterministe substitut (nom/séquence/tags, mis en défaut
                # sur 3 tests réels consécutifs).
                current_existing = list(existing_variants)
                for acc_cand in accepted_candidates:
                    current_existing.append({
                        "strategy_name": acc_cand.strategy_name,
                        "reasoning_summary": acc_cand.reasoning_summary,
                        "steps": [s.model_dump() for s in acc_cand.steps_summary],
                    })
                if reference_existing_entry:
                    current_existing = [reference_existing_entry] + current_existing

                if not current_existing:
                    is_distinct, distinction_score, distinction_reason = (
                        True, 1.0, "Première variante alternative pour cette question (aucun existant)."
                    )
                elif total_llm_calls >= self.MAX_LLM_CALLS:
                    # Plafond atteint : jamais un blocage silencieux ni une
                    # invention de score — signalé, candidate acceptée par
                    # défaut plutôt que de perdre une méthode déjà validée
                    # mathématiquement (§2/2bis ci-dessus) faute de budget
                    # LLM restant pour CE contrôle spécifique.
                    is_distinct, distinction_score = True, None
                    distinction_reason = "Non vérifié (plafond d'appels LLM atteint) — accepté par défaut."
                    logger.warning(
                        "Plafond d'appels LLM (%d) atteint avant la vérification de distinction "
                        "stratégique pour '%s'.", self.MAX_LLM_CALLS, candidate_schema.strategy_name,
                    )
                else:
                    total_llm_calls += 1
                    is_distinct, distinction_score, distinction_reason = await self._verify_strategic_distinction(
                        candidate=candidate_schema,
                        existing_variants=current_existing,
                        context=context,
                    )

                if not is_distinct:
                    attempt_logs.append(
                        VariantStrategyAttemptLog(
                            strategy_name=candidate_schema.strategy_name,
                            attempt_number=strategy_idx,
                            status="REJECTED_DUPLICATE",
                            rejection_reason=distinction_reason,
                            distinction_score=distinction_score,
                        )
                    )
                    rejected_feedbacks.append(
                        f"Méthode '{candidate_schema.strategy_name}' : rejetée car même stratégie de résolution "
                        f"qu'une variante existante ({distinction_reason})."
                    )
                    continue

                # 4. Vérification de l'enveloppe académique (signal informatif non bloquant)
                is_outside, outside_concepts = self._check_academic_envelope(
                    candidate_concepts=candidate_schema.concept_tags,
                    academic_envelope_set=academic_envelope_set,
                )
                candidate_schema.outside_academic_envelope = is_outside
                candidate_schema.outside_concepts = outside_concepts

                # Validée avec succès !
                attempt_logs.append(
                    VariantStrategyAttemptLog(
                        strategy_name=candidate_schema.strategy_name,
                        attempt_number=strategy_idx,
                        status="ACCEPTED",
                        distinction_score=distinction_score,
                        intermediate_verified_count=verified_count,
                        intermediate_check_note=intermediate_check_note,
                    )
                )
                accepted_candidates.append(candidate_schema)

                # En mode guidé ou à la demande, 1 seule variante suffit
                if trigger_type in ("on_demand", "guided"):
                    break

            duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
            span.record_metrics(
                candidate_count=len(accepted_candidates),
                total_llm_calls=total_llm_calls,
                duration_ms=duration_ms,
            )

            return VariantGenerationAgentReport(
                question_id=question_id,
                candidates=accepted_candidates,
                attempt_logs=attempt_logs,
                total_llm_calls=total_llm_calls,
                model_version=last_model_used,
            )

    def _verify_mathematical_equivalence(
        self,
        reference_conclusion: str,
        candidate_conclusion: str,
        reference_content: str,
        candidate_content: str,
    ) -> tuple[bool, str]:
        """
        Vérifie la validité/équivalence mathématique de la conclusion candidate
        par rapport à la conclusion de référence en utilisant SymPy.
        """
        if not reference_conclusion or not reference_conclusion.strip():
            # Si pas de conclusion isolée, la démarche est acceptée par défaut
            return True, "Pas de conclusion de référence explicite pour vérification SymPy."

        ref_str = reference_conclusion.strip()
        cand_str = candidate_conclusion.strip()

        try:
            expr_ref = self._parse_conclusion_value(ref_str)
            expr_cand = self._parse_conclusion_value(cand_str)

            diff = sp.simplify(expr_ref - expr_cand)
            if diff == 0 or diff == 0.0:
                return True, "Équivalence symbolique SymPy vérifiée (diff = 0)."
            else:
                return False, f"Différence symbolique non nulle : {diff} (ref: {expr_ref}, cand: {expr_cand})"
        except Exception as exc:
            # Fallback déterministe sur normalisation textuelle/numérique si SymPy ne peut pas parser
            ref_nums = re.findall(r"[-+]?\d*\.?\d+", ref_str)
            cand_nums = re.findall(r"[-+]?\d*\.?\d+", cand_str)

            if ref_nums and cand_nums and ref_nums == cand_nums:
                return True, "Équivalence des valeurs numériques vérifiée (fallback textuel)."

            norm_ref = re.sub(r"\s+", "", ref_str.lower())
            norm_cand = re.sub(r"\s+", "", cand_str.lower())
            if norm_ref in norm_cand or norm_cand in norm_ref:
                return True, "Équivalence des termes texte/formule vérifiée (fallback inclusif)."

            return True, f"SymPy non applicable ('{exc}'), conclusion admise par fallback."

    # lowercase_symbols=False : "P" (ex. charge) et "p" (ex. pression) sont
    # des symboles distincts, jamais à fusionner. units=True : une unité en
    # \text{} (ex. "\text{ kN}") est écartée de l'expression symbolique
    # plutôt que transformée en pseudo-symbole — même config déjà validée
    # sur Extraction_Verification_Agent._compute_canonical_form ce jour.
    _LATEX2SYMPY_CONVERSION_CONFIG = ConversionConfig(lowercase_symbols=False)
    _LATEX2SYMPY_NORMALIZATION_CONFIG = NormalizationConfig(units=True)
    _LATEX_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")

    def _parse_expr_or_eq(self, text: str) -> sp.Expr:
        r"""
        Aiguille sur la présence d'un backslash : notation LaTeX ->
        latex2sympy2_extended, qui gère nativement une égalité "A = B" ->
        sympy.Eq. JAMAIS l'ancien chemin _extract_sympy_expression (regex
        naïves) sur du LaTeX : il transformait silencieusement
        "\frac{N}{A}" en un symbole unique "NA" — une expression qui PARSE
        mais qui est FAUSSE, plus dangereuse qu'un échec de parsing puisque
        ça peut faire rejeter à tort un candidat mathématiquement valide.
        Notation standard (pas de backslash) -> chemin existant inchangé
        (_extract_sympy_expression, déjà testé sur des conclusions
        numériques du type "A = 12 cm2" -> "12").
        """
        if "\\" in text:
            normalized = self._LATEX_DECIMAL_COMMA_RE.sub(".", text)
            return latex2sympy(
                normalized,
                conversion_config=self._LATEX2SYMPY_CONVERSION_CONFIG,
                normalization_config=self._LATEX2SYMPY_NORMALIZATION_CONFIG,
            )
        return sp.parse_expr(self._extract_sympy_expression(text))

    @staticmethod
    def _clean_symbol_or_expr(text: str) -> str:
        """
        Nettoyage minimal pour un membre d'égalité en notation standard,
        utilisé UNIQUEMENT par _parse_equation — préserve les noms de
        symboles (N_5, sigma_max...), contrairement à
        _extract_sympy_expression dont la liste blanche stricte (seules les
        lettres x/y/z passent) est conçue pour extraire un nombre final
        avec unités (ex. "12 cm2" -> "12"), pas un symbole général : trouvé
        en testant _verify_intermediate_consistency (2026-08-17), "N_5"
        aggressivement nettoyé devenait juste "5", rendant toute
        comparaison muette. Une formule LLM en notation standard est déjà
        une syntaxe sympy quasi valide telle quelle — seul ^ -> ** et les
        accolades résiduelles sont normalisés.
        """
        return text.strip().replace("^", "**").replace("{", "(").replace("}", ")")

    def _parse_conclusion_value(self, text: str) -> sp.Expr:
        """
        Si le résultat est une égalité, seul le membre DROIT (la valeur/
        l'expression conclue) est retourné : le nom de la variable à gauche
        peut légitimement différer entre référence et candidate (ex.
        "P = 28 kN" vs "F = 28 kN") sans que ce soit une différence
        mathématique réelle. reference_conclusion vient de ReasoningStep.
        formula, jamais canonical_form (cf. solution_variant_generation_
        service.py).
        """
        expr = self._parse_expr_or_eq(text)
        return expr.rhs if isinstance(expr, sp.Eq) else expr

    def _parse_equation(self, text: str) -> tuple[str, sp.Expr] | None:
        """
        Contrairement à _parse_conclusion_value (qui ne garde QUE le membre
        droit), retourne (nom_du_symbole, membre_droit) — nécessaire pour
        _verify_intermediate_consistency qui doit savoir QUELLE grandeur
        chaque formule définit, afin de comparer les définitions d'une même
        grandeur entre référence et candidat. None si la formule n'est pas
        de la forme "symbole = expression" (LHS composé, ex. "N/A = ...",
        ou absence de "=", ou échec de parsing) — jamais une exception,
        même contrat de tolérance que le reste de cet agent.
        """
        if not text or not text.strip():
            return None
        cleaned = text.strip()
        # Garde commune LaTeX + notation standard : exactement UN "=" — une
        # formule combinant deux équations séparées par une virgule (ex.
        # "\sin α = ..., \cos α = ...", vu sur test réel 2026-08-17) n'est
        # PAS une définition unique de grandeur ; la laisser passer telle
        # quelle à latex2sympy produisait un comportement imprévisible
        # (avertissement Python interne) sans jamais rien comparer utilement
        # — autant la rejeter proprement en amont, comme le faisait déjà la
        # branche notation standard seule avant ce fix.
        if cleaned.count("=") != 1:
            return None
        try:
            if "\\" in cleaned:
                expr = self._parse_expr_or_eq(cleaned)
            else:
                lhs_raw, rhs_raw = cleaned.split("=")
                lhs_expr = sp.parse_expr(self._clean_symbol_or_expr(lhs_raw))
                rhs_expr = sp.parse_expr(self._clean_symbol_or_expr(rhs_raw))
                expr = sp.Eq(lhs_expr, rhs_expr)
        except Exception:
            return None
        if not isinstance(expr, sp.Eq) or not expr.lhs.is_symbol:
            return None
        return str(expr.lhs), expr.rhs

    def _extract_symbol_definitions(self, formulas: list[str | None]) -> dict[str, sp.Expr]:
        """
        Construit {nom_symbole: expression} depuis une liste de formules —
        la PREMIÈRE définition rencontrée pour un symbole donné est
        conservée (une grandeur physique ne devrait pas être redéfinie
        différemment au sein d'un même texte ; en cas de doublon apparent,
        garder la première plutôt qu'écraser silencieusement en fait foi).
        """
        definitions: dict[str, sp.Expr] = {}
        for formula in formulas:
            if not formula:
                continue
            parsed = self._parse_equation(formula)
            if parsed is None:
                continue
            symbol, expr = parsed
            definitions.setdefault(symbol, expr)
        return definitions

    @staticmethod
    def _lookup_symbol_case_insensitive(definitions: dict[str, sp.Expr], symbol: str) -> sp.Expr | None:
        """
        Repli de _verify_intermediate_consistency quand la correspondance
        exacte échoue — un LLM peut nommer la même grandeur "N_5" dans un
        appel et "n_5" dans un autre sans que ce soit une différence
        physique réelle. None si aucune clé ne correspond même en ignorant
        la casse (jamais un faux positif inventé).
        """
        symbol_lower = symbol.lower()
        for key, expr in definitions.items():
            if key.lower() == symbol_lower:
                return expr
        return None

    def _verify_intermediate_consistency(
        self,
        reference_steps: list[ReferenceStepContext],
        candidate_steps: list[CandidateStepSummarySchema],
    ) -> tuple[bool, list[str], int, list["_AmbiguousSymbolPair"]]:
        """
        Vérifie que toute grandeur (symbole isolé à gauche d'une égalité,
        ex. "N_5", "σ_max") définie À LA FOIS dans la référence et dans le
        candidat a la MÊME expression symbolique des deux côtés — pas
        seulement la conclusion finale (cf. mémoire de session : un LLM voit
        reference_conclusion dans le prompt et peut la recopier sans que le
        raisonnement intermédiaire soit réellement dérivé ; deux formules
        qui donnent par coïncidence la même conclusion mais des grandeurs
        intermédiaires incompatibles ne décrivent pas la même physique).

        Une grandeur qui n'apparaît QUE dans le candidat n'est jamais un
        motif de rejet : une méthode alternative suit par construction un
        chemin de dérivation différent (ex. "travaux virtuels" au lieu d'un
        équilibre nœud par nœud), donc introduit ses propres grandeurs
        intermédiaires qui n'ont simplement rien à comparer côté référence.
        Seul un DÉSACCORD sur une grandeur partagée est un conflit réel.

        Retourne (is_consistent, conflicts, verified_count, ambiguous_pairs).
        verified_count est le nombre de grandeurs où une comparaison RÉELLE a
        pu avoir lieu (les deux côtés partageaient un symbole résolvable),
        qu'elle ait confirmé une égalité ou révélé un conflit. Distinct et
        nécessaire : is_consistent=True quand verified_count=0 signifie "rien
        n'a pu être vérifié PAR CETTE ÉTAPE", PAS "vérifié et confirmé
        cohérent" — l'appelant doit distinguer ces deux cas (jamais le même
        statut ACCEPTED muet, cf. gap de traçabilité trouvé le 2026-08-17).
        ambiguous_pairs liste les grandeurs partagées (même LHS) dont le diff
        dépend de symboles exclusifs à un seul côté (ex. "N" générique vs
        "N_5" spécialisé) — non résolues PAR SYMPY SEUL ici, mais candidates
        à une résolution sémantique par LLM (_resolve_symbol_correspondences,
        v1.9) ; tant que cette résolution n'a pas eu lieu (ou échoue/n'est
        pas tentée faute de budget), elles restent NON VÉRIFIÉES — jamais
        comptées dans verified_count ni dans conflicts à ce stade.
        """
        ref_definitions = self._extract_symbol_definitions([s.formula for s in reference_steps])
        cand_formulas = [s.formula for s in candidate_steps]
        cand_definitions = self._extract_symbol_definitions(cand_formulas)

        conflicts: list[str] = []
        verified_count = 0
        ambiguous_pairs: list[_AmbiguousSymbolPair] = []
        for symbol, cand_expr in cand_definitions.items():
            # Correspondance exacte d'abord, insensible à la casse en repli
            # (ex. "N_5" côté référence vs "n_5" côté candidat — même
            # grandeur, notation LLM légèrement différente d'un appel à
            # l'autre ; jamais l'inverse d'un vrai désaccord de valeur).
            ref_expr = ref_definitions.get(symbol)
            if ref_expr is None:
                ref_expr = self._lookup_symbol_case_insensitive(ref_definitions, symbol)
            if ref_expr is None:
                continue
            try:
                diff = sp.simplify(ref_expr - cand_expr)
            except Exception:
                continue  # non comparable (types incompatibles) — jamais bloquant
            if diff == 0 or diff == 0.0:
                verified_count += 1
                continue
            # Un diff non nul n'est une VRAIE contradiction que s'il ne
            # dépend que de symboles PARTAGÉS par les deux côtés. Trouvé sur
            # test réel (2026-08-17) : référence "σ_max = N/A·ω" (N générique,
            # jamais résolu ailleurs dans la référence) vs candidat
            # "σ_max = N_5/A·ω" (N_5 = grandeur explicitement nommée, cf.
            # règle 5 du prompt) — sympy traite N et N_5 comme deux symboles
            # indépendants donc diff=ω(N-N_5)/A ≠ 0, mais ce n'est qu'un
            # nommage générique-vs-spécifique de la RÉFÉRENCE elle-même, pas
            # un désaccord de valeur du candidat. Si le diff ne dépend QUE de
            # symboles exclusifs à un seul côté (jamais résolus en commun),
            # rien n'est réellement comparable PAR SYMPY SEUL — mais peut
            # l'être via correspondance sémantique (v1.9, cf.
            # _resolve_symbol_correspondences) : collectée ici plutôt que
            # jetée, jamais comptée comme vérifiée ni comme conflit à ce
            # stade (l'appelant décide si un appel LLM est tenté). Le cas
            # déjà validé (ex. N_5=2P vs N_5=3P√5, où P est partagé des deux
            # côtés) reste détecté sans changement.
            shared_symbols = ref_expr.free_symbols & cand_expr.free_symbols
            exclusive_symbols = diff.free_symbols - shared_symbols
            if exclusive_symbols:
                ref_only = sorted(str(s) for s in (exclusive_symbols & ref_expr.free_symbols))
                cand_only = sorted(str(s) for s in (exclusive_symbols & cand_expr.free_symbols))
                if ref_only and cand_only:
                    ambiguous_pairs.append(_AmbiguousSymbolPair(
                        shared_symbol=symbol,
                        reference_expr=ref_expr,
                        candidate_expr=cand_expr,
                        reference_exclusive_symbols=ref_only,
                        candidate_exclusive_symbols=cand_only,
                    ))
                continue
            verified_count += 1
            conflicts.append(
                f"{symbol} : référence donne {ref_expr}, candidat donne {cand_expr} "
                f"(différence non nulle : {diff})"
            )

        return len(conflicts) == 0, conflicts, verified_count, ambiguous_pairs

    def _extract_sympy_expression(self, text: str) -> str:
        """Nettoie une chaîne pour extraire une expression algébrique parsable par SymPy."""
        # Supprimer le texte environnant et ne garder que l'équation ou le nombre
        parts = text.split("=")
        target = parts[-1] if len(parts) > 1 else text
        # Enlever les unités courantes et symboles LaTeX
        cleaned = re.sub(r"\\(?:cm|m|kg|g|s|h|deg|rad|unit|frac)\b", "", target)
        cleaned = re.sub(r"[a-zA-Z]{2,}", "", cleaned)  # Enlever mots longs (mètres, etc.)
        cleaned = cleaned.replace("^", "**").replace("{", "(").replace("}", ")")
        cleaned = re.sub(r"[^\d\+\-\*\/\(\)\.\,\ xXyYzZ]", "", cleaned)
        cleaned = cleaned.strip()
        return cleaned if cleaned else text

    async def _verify_strategic_distinction(
        self,
        candidate: GeneratedVariantCandidateSchema,
        existing_variants: list[dict],
        context: AgentExecutionContext | None,
    ) -> tuple[bool, float | None, str]:
        """
        Jugement LLM holistique (v1.7, cf. docstring module) : la candidate
        ET TOUTES les variantes existantes sont vues ensemble dans un seul
        appel (jamais paire par paire, jamais un score texte/séquence
        substitut) — le LLM juge si la STRATÉGIE de résolution est
        réellement différente, sur le contenu complet (principe, séquence,
        formules), jamais sur le nom seul. Retourne (is_distinct,
        distinction_score, justification).

        Best-effort mais jamais silencieux : un échec de parsing/appel LLM
        ici ne doit jamais faire perdre une candidate déjà validée
        mathématiquement (§2/2bis ci-dessus) — traité comme "non
        vérifiable" (accepté par défaut, motif explicite dans le log/la
        justification), jamais un blocage strict pour une panne d'outil.
        """
        candidate_steps_text = "\n".join(
            f"  {s.order}. [{s.step_type}] {s.formula or s.description}"
            for s in candidate.steps_summary
        ) or "  (aucune étape détaillée)"

        existing_blocks = []
        for idx, ev in enumerate(existing_variants, 1):
            ev_steps = ev.get("steps", [])
            steps_text = "\n".join(
                f"    {s.get('order', '?')}. [{s.get('step_type', '?')}] "
                f"{s.get('formula') or s.get('description', '')}"
                for s in ev_steps
            ) or "    (aucune étape détaillée)"
            existing_blocks.append(
                f"#{idx} — {ev.get('strategy_name') or '(sans nom)'}\n"
                f"  Résumé : {ev.get('reasoning_summary') or '(aucun résumé)'}\n"
                f"  Étapes :\n{steps_text}"
            )

        user_msg = STRATEGIC_DISTINCTION_USER_TEMPLATE.format(
            candidate_name=candidate.strategy_name,
            candidate_summary=candidate.reasoning_summary,
            candidate_steps=candidate_steps_text,
            existing_variants="\n\n".join(existing_blocks),
        )
        messages = [
            {"role": "system", "content": STRATEGIC_DISTINCTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            result, _spec, _fallback, _ = await invoke_llm_with_fallback(
                task_type=TaskType.SOLUTION_VARIANT_GENERATION,
                messages=messages,
                response_schema=_StrategicDistinctionSchema,
                context=context,
            )
            parsed = (
                result if isinstance(result, _StrategicDistinctionSchema)
                else _StrategicDistinctionSchema.model_validate(result)
            )
        except Exception as exc:
            logger.warning(
                "Échec du jugement de distinction stratégique pour '%s' : %s. "
                "Candidate acceptée par défaut (non bloquant).", candidate.strategy_name, exc,
            )
            return True, None, f"Non vérifié (échec technique : {exc}) — accepté par défaut."

        reason = parsed.justification
        if not parsed.is_distinct and parsed.most_similar_existing_index:
            idx = parsed.most_similar_existing_index
            if 1 <= idx <= len(existing_variants):
                similar_name = existing_variants[idx - 1].get("strategy_name") or f"variante #{idx}"
                reason = f"Même stratégie que « {similar_name} » — {parsed.justification}"

        return parsed.is_distinct, parsed.distinction_score, reason

    # Signatures connues de commandes LaTeX imbriquées mal ré-échappées par
    # le LLM en sortie JSON structurée (constaté en test réel, 2026-08-30,
    # variante "Principe de superposition") : `\b`, `\f`, `\t` sont des
    # échappements JSON valides (backspace/form-feed/tab) — un backslash
    # simple au lieu d'un double devant une commande LaTeX commençant par
    # b/f/t produit un caractère de contrôle silencieusement perdu en aval,
    # laissant le reste de la commande orphelin (\big -> "ig", \frac ->
    # "rac", \textstyle -> "extstyle", \boldsymbol -> "oldsymbol"). Jamais un
    # parseur LaTeX complet (LatexWalker échouerait sur toute ligne de prose
    # mélangée aux maths dans `content`) — une liste de signatures littérales
    # ciblant précisément CE mode de défaillance connu, pas une validation
    # syntaxique générale.
    # Lookbehind négatif sur une lettre : un fragment comme "rac{" est un
    # défaut UNIQUEMENT s'il n'est pas déjà précédé de son "f" manquant (i.e.
    # PAS à l'intérieur d'un "\frac{" parfaitement valide) — sans ce garde,
    # "rac{" matchait aussi la sous-chaîne interne de "frac{" lui-même,
    # rejetant à tort toute fraction valide (faux positif constaté en test
    # de ce fix avant intégration).
    _CORRUPTED_LATEX_PATTERNS = (
        re.compile(r"(?<![a-zA-Z])ig\("),
        re.compile(r"(?<![a-zA-Z])ig\)"),
        re.compile(r"(?<![a-zA-Z])rac\{"),
        re.compile(r"(?<![a-zA-Z])extstyle"),
        re.compile(r"(?<![a-zA-Z])oldsymbol\{"),
    )

    @classmethod
    def _detect_corrupted_latex_fragments(cls, content: str) -> list[str]:
        return [m.group(0) for pat in cls._CORRUPTED_LATEX_PATTERNS if (m := pat.search(content))]

    async def _verify_steps_coherence(
        self,
        candidate: GeneratedVariantCandidateSchema,
        context: AgentExecutionContext | None,
    ) -> tuple[bool, str]:
        """
        Détection légère (v1.12, cf. docstring module) de la divergence
        content/steps_summary — jamais bloquant seule : le résultat pilote
        _regenerate_steps_from_content, jamais un rejet de la candidate déjà
        validée par ailleurs. Échec technique = non vérifié, steps_summary
        conservé tel quel (même discipline que _verify_strategic_distinction).
        """
        steps_text = "\n".join(
            f"  {s.order}. [{s.step_type}] derivation={s.derivation or '(absente)'} | formula={s.formula or s.description}"
            for s in candidate.steps_summary
        ) or "  (aucune étape détaillée)"

        user_msg = STEPS_COHERENCE_USER_TEMPLATE.format(
            strategy_name=candidate.strategy_name,
            content=candidate.content,
            reasoning_summary=candidate.reasoning_summary,
            steps_text=steps_text,
        )
        messages = [
            {"role": "system", "content": STEPS_COHERENCE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            result, _spec, _fallback, _ = await invoke_llm_with_fallback(
                task_type=TaskType.SOLUTION_VARIANT_GENERATION,
                messages=messages,
                response_schema=_StepsCoherenceSchema,
                context=context,
            )
            parsed = (
                result if isinstance(result, _StepsCoherenceSchema)
                else _StepsCoherenceSchema.model_validate(result)
            )
            return parsed.is_coherent, parsed.justification
        except Exception as exc:
            logger.warning(
                "Échec de la vérification de cohérence steps_summary/content pour '%s' : %s. "
                "steps_summary conservé tel quel (non bloquant).", candidate.strategy_name, exc,
            )
            return True, f"Non vérifié (échec technique : {exc}) — conservé tel quel."

    async def _regenerate_steps_from_content(
        self,
        candidate: GeneratedVariantCandidateSchema,
        context: AgentExecutionContext | None,
    ) -> list[CandidateStepSummarySchema]:
        """
        Re-décomposition CIBLÉE (v1.12) : `content` déjà accepté sert de
        SEULE entrée — jamais un nouvel appel de génération complète —
        pour que steps_summary ne puisse plus structurellement diverger de
        la méthode réellement décrite. Best-effort : un échec conserve
        l'original plutôt que de perdre la candidate (même discipline que
        le reste de ce fichier).
        """
        user_msg = STEPS_REDERIVATION_USER_TEMPLATE.format(
            strategy_name=candidate.strategy_name,
            content=candidate.content,
        )
        messages = [
            {"role": "system", "content": STEPS_REDERIVATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            result, _spec, _fallback, _ = await invoke_llm_with_fallback(
                task_type=TaskType.SOLUTION_VARIANT_GENERATION,
                messages=messages,
                response_schema=_StepsRederivationSchema,
                context=context,
            )
            parsed = (
                result if isinstance(result, _StepsRederivationSchema)
                else _StepsRederivationSchema.model_validate(result)
            )
            if parsed.steps_summary:
                return parsed.steps_summary
            logger.warning(
                "Re-décomposition de steps_summary vide pour '%s' — original conservé.",
                candidate.strategy_name,
            )
            return candidate.steps_summary
        except Exception as exc:
            logger.warning(
                "Échec de la re-décomposition de steps_summary pour '%s' : %s. "
                "steps_summary original conservé (non bloquant).", candidate.strategy_name, exc,
            )
            return candidate.steps_summary

    async def _resolve_symbol_correspondences(
        self,
        ambiguous_pairs: list[_AmbiguousSymbolPair],
        reference_steps: list[ReferenceStepContext],
        candidate_steps: list[CandidateStepSummarySchema],
        context: AgentExecutionContext | None,
    ) -> tuple[list[str], int, str]:
        """
        Résolution sémantique (v1.9, cf. docstring module) des grandeurs
        partagées dont le nom diffère entre référence et candidat (ex. "N"
        générique vs "N_5" spécialisé) — un seul appel LLM holistique voit
        TOUTES les paires ambiguës de ce candidat EN MÊME TEMPS, avec le
        contexte complet (formule + description) des deux côtés, jamais
        paire par paire.

        Retourne (new_conflicts, resolved_count, note) avec EXACTEMENT 3
        issues possibles par paire, jamais confondues :
          1. correspondance trouvée + cohérente -> resolved_count += 1,
             rien dans new_conflicts.
          2. correspondance trouvée + désaccord réel (diff != 0 même après
             substitution) -> resolved_count += 1 ET une entrée dans
             new_conflicts (fait rejeter la candidate, comme un conflit
             direct).
          3. correspondance non trouvée (LLM répond corresponds=false, ne
             couvre pas la paire, ou couverture partielle des symboles
             exclusifs candidat) -> NI resolved_count NI new_conflicts —
             reste NON VÉRIFIÉ, exactement comme si cette méthode n'avait
             jamais été appelée pour cette paire.

        Best-effort mais jamais silencieux sur le sens : un échec technique
        (appel LLM, parsing) traite TOUTES les paires comme le cas 3 — ne
        fait jamais perdre une candidate déjà validée mathématiquement par
        ailleurs, et n'invente jamais une confirmation.
        """
        pairs_lines = []
        for p in ambiguous_pairs:
            pairs_lines.append(
                f"  - Grandeur partagée « {p.shared_symbol} » (référence: {p.reference_expr}, "
                f"candidat: {p.candidate_expr}) : référence utilise le(s) symbole(s) "
                f"{p.reference_exclusive_symbols}, candidat utilise {p.candidate_exclusive_symbols} — "
                f"désignent-ils la même grandeur physique ?"
            )
        pairs_text = "\n".join(pairs_lines) or "  (aucune)"

        ref_context_text = "\n".join(
            f"  {s.formula} — {s.description or '(pas de description)'}"
            for s in reference_steps if s.formula
        ) or "  (aucune)"
        cand_context_text = "\n".join(
            f"  {s.formula} — {s.description or '(pas de description)'}"
            for s in candidate_steps if s.formula
        ) or "  (aucune)"

        user_msg = SYMBOL_CORRESPONDENCE_USER_TEMPLATE.format(
            ambiguous_pairs=pairs_text,
            reference_context=ref_context_text,
            candidate_context=cand_context_text,
        )
        messages = [
            {"role": "system", "content": SYMBOL_CORRESPONDENCE_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            result, _spec, _fallback, _ = await invoke_llm_with_fallback(
                task_type=TaskType.SOLUTION_VARIANT_GENERATION,
                messages=messages,
                response_schema=_SymbolCorrespondenceSchema,
                context=context,
            )
            parsed = (
                result if isinstance(result, _SymbolCorrespondenceSchema)
                else _SymbolCorrespondenceSchema.model_validate(result)
            )
        except Exception as exc:
            logger.warning(
                "Échec de la résolution de correspondance de symboles : %s. "
                "%d grandeur(s) restent NON VÉRIFIÉES (non bloquant).", exc, len(ambiguous_pairs),
            )
            return [], 0, (
                f"{len(ambiguous_pairs)} grandeur(s) au nommage ambigu non vérifiée(s) "
                f"(échec technique : {exc})."
            )

        conflicts: list[str] = []
        resolved_count = 0
        unresolved = 0
        for pair in ambiguous_pairs:
            # Une correspondance n'est retenue QUE si le LLM la confirme
            # (corresponds=True) ET qu'elle porte EXACTEMENT sur des
            # symboles que NOUS avons proposés pour CETTE paire — jamais une
            # correspondance hors périmètre inventée par le LLM. Repli
            # insensible à la casse (même convention que
            # _lookup_symbol_case_insensitive), mais la substitution sympy
            # utilise TOUJOURS notre propre casse stockée (jamais celle,
            # potentiellement différente, échouée par le LLM).
            substitutions: dict[sp.Symbol, sp.Symbol] = {}
            for entry in parsed.correspondences:
                if not entry.corresponds:
                    continue
                ref_match = next(
                    (s for s in pair.reference_exclusive_symbols if s.lower() == entry.reference_symbol.lower()),
                    None,
                )
                cand_match = next(
                    (s for s in pair.candidate_exclusive_symbols if s.lower() == entry.candidate_symbol.lower()),
                    None,
                )
                if ref_match and cand_match:
                    substitutions[sp.Symbol(cand_match)] = sp.Symbol(ref_match)

            # Couverture EXHAUSTIVE requise : si un seul symbole exclusif du
            # candidat reste sans correspondance confirmée, une substitution
            # partielle produirait un diff dont le sens serait trompeur
            # (ni vraiment vérifié, ni vraiment un conflit) — traité comme
            # non résolu plutôt que de risquer une conclusion fausse.
            cand_symbols_needed = {sp.Symbol(s) for s in pair.candidate_exclusive_symbols}
            if not substitutions or set(substitutions.keys()) != cand_symbols_needed:
                unresolved += 1
                continue

            try:
                substituted_cand = pair.candidate_expr.subs(substitutions)
                diff = sp.simplify(pair.reference_expr - substituted_cand)
            except Exception:
                unresolved += 1
                continue

            resolved_count += 1
            if diff != 0 and diff != 0.0:
                mapping_text = ", ".join(f"{c}↔{r}" for c, r in substitutions.items())
                conflicts.append(
                    f"{pair.shared_symbol} : correspondance sémantique établie ({mapping_text}) mais "
                    f"désaccord réel après substitution — référence donne {pair.reference_expr}, "
                    f"candidat donne {pair.candidate_expr} (différence non nulle : {diff})"
                )

        note_parts = []
        if resolved_count:
            note_parts.append(
                f"{resolved_count} grandeur(s) vérifiée(s) via correspondance sémantique (LLM) entre "
                f"symbole(s) générique(s) et spécialisé(s)."
            )
        if unresolved:
            note_parts.append(
                f"{unresolved} grandeur(s) restent NON VÉRIFIÉES (aucune correspondance fiable établie)."
            )
        return conflicts, resolved_count, " ".join(note_parts)

    def _check_academic_envelope(
        self,
        candidate_concepts: list[str],
        academic_envelope_set: set[str],
    ) -> tuple[bool, list[str]]:
        """
        Vérifie si les concepts de la variante dépassent l'enveloppe académique du module.
        Retourne (is_outside, list_of_new_concepts). Signal informatif non bloquant.
        """
        if not academic_envelope_set:
            return False, []

        outside = [c for c in candidate_concepts if c not in academic_envelope_set]
        return bool(outside), outside
