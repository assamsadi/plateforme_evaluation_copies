"""
Agent — Reasoning_Graph_Agent v2.

Enrichit la décomposition déjà produite par Extraction_Verification_Agent
(Agent 4) — jamais un second parseur indépendant du texte brut. Prend en
entrée les ReasoningStep déjà persistés pour une variante (référence ou
variante), et détermine UNIQUEMENT ce que le contenu déjà décomposé ne
capture pas : les arêtes de dépendance formant un DAG, is_core_step,
tools_used, concept_tags.

Pourquoi ce changement (v1 -> v2) : v1 reparsait le texte source brut
indépendamment d'Agent 4, ce qui causait une perte de données active — les
deux agents persistaient des ReasoningStep concurrents pour la même
variante (matching fragile par `order`), et la seconde passe (Agent 5)
supersédait la première (Agent 4) sans jamais reporter canonical_form/
dimensional_check_result/anomaly_detected — signaux qu'Agent 4 seul calcule
(cf. Extraction_Verification_Agent._compute_canonical_form et
_compute_dimensional_check). Comparative_Evaluation_Agent lit ces signaux
sur les steps actifs (non supersédés) : ils étaient donc silencieusement
perdus avant d'atteindre la comparaison avec la copie de l'étudiant.

Principes directeurs :
- LLM-as-Parser restreint : ne réinvente JAMAIS step_ref/order/step_type/
  description/formula/source_span (déjà fixés par Agent 4) — juge
  uniquement la structure logique (dépendances) et quelques tags.
- Flow exercise_setup uniquement : scopé sur les SolutionVariant, jamais sur
  les réponses d'étudiants.
- Validation déterministe NetworkX : détection de cycle DAG, tri topologique,
  calcul séquentiel de downstream_step_refs (fermeture transitive), et
  validation de la disponibilité des variables (constraint-based reasoning).
- HITL conditionnel : déclenché automatiquement si construction_confidence < 0.6.
  (source_coverage_ratio disparaît avec la v1 : plus de redécouverte de
  contenu depuis du texte brut, donc plus rien à "manquer" structurellement.)
"""
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

import networkx as nx
from pydantic import BaseModel, Field

from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import ClarificationRequest, ClarificationSeverity
from app.agents.reasoning_graph_exceptions import (
    ReasoningGraphCycleError,
    ReasoningGraphError,
)
from app.domain.models.assessment.reasoning_step import ReasoningStepType
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType
from app.observability.langfuse import AgentTraceSpan
from app.prompts.reasoning_graph_prompt import (
    REASONING_GRAPH_RETRY_CYCLE_TEMPLATE,
    REASONING_GRAPH_SYSTEM_PROMPT,
    REASONING_GRAPH_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Entrée / Sortie Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ExistingStepInput:
    """
    Une étape déjà décomposée par Extraction_Verification_Agent (Agent 4) et
    persistée en base (ReasoningStep) — jamais réinventée ici. step_id est le
    vrai ReasoningStep.id (UUID, passé en str), utilisé tel quel comme
    identifiant opaque dans les depends_on_refs retournés par le LLM : pas de
    relabellisation à gérer côté service appelant.
    """
    step_id: str
    order: int
    step_type: ReasoningStepType
    description: str
    formula: str | None = None
    source_span: str = ""


@dataclass
class CompetencyWeightProposal:
    code: C2PCTSkillCode
    weight: float = 0.0


@dataclass
class ReasoningStepGraphOutput:
    step_ref: str
    order: int
    step_type: ReasoningStepType
    description: str
    formula: str | None = None
    concept_tags: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    competency_weights: list[CompetencyWeightProposal] = field(default_factory=list)
    is_core_step: bool = True
    depends_on_refs: list[str] = field(default_factory=list)
    downstream_step_refs: list[str] = field(default_factory=list)  # Calculé via networkx.descendants
    source_span: str = ""


@dataclass
class ReasoningGraphReport:
    variant_id: uuid.UUID
    steps: list[ReasoningStepGraphOutput]
    construction_confidence: float
    clarifications: list[ClarificationRequest] = field(default_factory=list)
    is_valid_dag: bool = True
    model_version: str | None = None


# ---------------------------------------------------------------------------
# Schéma de sortie LLM (structured output) — tâche étroite : uniquement les
# champs qu'Agent 4 ne fournit pas (dépendances, is_core_step, tools_used,
# concept_tags), jamais le contenu de l'étape elle-même. Structured output
# élimine par construction le bug regex-JSON déjà rencontré/corrigé sur
# Document_Structuring_Agent et Extraction_Verification_Agent (cf. mémoire
# de session) — inutile de le réintroduire ici via une extraction manuelle.
# ---------------------------------------------------------------------------

class _CompetencyWeightSchema(BaseModel):
    code: C2PCTSkillCode
    weight: float = 0.0


class _StepEnrichmentSchema(BaseModel):
    step_id: str
    depends_on_refs: list[str] = Field(default_factory=list)
    is_core_step: bool = True
    tools_used: list[str] = Field(default_factory=list)
    concept_tags: list[str] = Field(default_factory=list)
    competency_weights: list[_CompetencyWeightSchema] = Field(default_factory=list)


class _GraphEnrichmentSchema(BaseModel):
    construction_confidence: float = 1.0
    enrichments: list[_StepEnrichmentSchema] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ReasoningGraphAgent:
    """Agent d'enrichissement du graphe de raisonnement (DAG) sur des étapes déjà décomposées."""

    AGENT_NAME = "Reasoning_Graph_Agent"
    # Identifiant = lettre initiale + suite alphanumérique, puis un indice
    # optionnel après underscore — SOIT un caractère seul sans accolades
    # (N_5, N_i, syntaxe LaTeX valide pour un indice d'UN SEUL caractère),
    # SOIT un indice complet ENTRE ACCOLADES (K_{red}, u_{ libres},
    # k_{local}) : la syntaxe LaTeX correcte pour un indice de PLUSIEURS
    # caractères EXIGE des accolades ("K_red" ne mettrait en indice que le
    # "r" à l'affichage) — un LLM qui écrit un indice multi-caractères
    # l'entoure donc presque toujours d'accolades. Avant ce fix (juste
    # `[a-zA-Z0-9_]*` sans notion d'accolade), une accolade n'étant pas un
    # caractère de \b, elle coupait le token en deux à chaque fois
    # (constaté en test réel, 2026-08-30 : "K_{red}" -> "k_" + "red"
    # séparés, "u_{ libres}" -> "u_" + "libres", "k_{local}" -> "k_" +
    # "local" — 5 fausses alertes BLOCKING sur le graphe de raisonnement,
    # cf. backlog). `\s*` de part et d'autre du contenu tolère un espace
    # parasite immédiatement après l'accolade ouvrante (vu tel quel dans
    # "u_{ libres}"). Un underscore isolé sans rien de valide après (ex.
    # "N_" en fin de chaîne) ne fait matcher QUE la base ("N") — le "_"
    # reste non consommé, jamais un fragment tronqué reconstruit à tort.
    _VAR_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9]*(?:_\{?\s*[a-zA-Z0-9]+\s*\}?)?")
    # §9bis, bruit LaTeX : une commande de contrôle ("\frac", "\cdot", "\sin",
    # "\alpha"...) ne dénote jamais un symbole de variable — règle
    # structurelle générale (tout ce qui suit un backslash), pas une liste de
    # noms de commandes à maintenir indéfiniment. \text{...} est retiré en
    # bloc (commande + argument) : c'est de l'annotation en mode texte
    # (unités, ex. "\text{ kN}"), jamais un symbole algébrique — un simple
    # retrait de "\text" laisserait le contenu ("kN") être re-capturé comme
    # faux symbole par _VAR_PATTERN juste après.
    _LATEX_TEXT_BLOCK_RE = re.compile(r"\\text\{[^{}]*\}")
    _LATEX_COMMAND_RE = re.compile(r"\\[a-zA-Z]+")
    _RESERVED_WORDS = {
        "sin", "cos", "tan", "log", "ln", "exp", "sqrt", "min", "max",
        "sum", "lim", "int", "true", "false", "and", "or", "not", "if", "then",
        "est", "et", "ou", "donc", "car", "par", "pour", "avec", "sur", "dans",
        "le", "la", "les", "un", "une", "des", "du", "de", "d", "l", "au", "aux",
        "cm", "cm2", "cm3", "m", "m2", "m3", "kg", "g", "s", "h", "min", "km",
        "n", "kn", "mpa", "pa", "gpa", "rad", "deg",
        "ainsi", "alors", "soit", "on", "a", "ce", "cette", "ces", "qui", "que",
        "donc", "ainsi", "calcul", "résultat", "valeur", "égal", "égale"
    }

    async def execute(
        self,
        variant_id: uuid.UUID,
        steps: list[ExistingStepInput],
        question_domain_type: str = "open_ended",
        context: AgentExecutionContext | None = None,
    ) -> ReasoningGraphReport:
        trace_id = context.trace_id if context else str(uuid.uuid4())
        span_metadata = {
            "flow_type": context.flow_type if context else "exercise_setup",
            "variant_id": str(variant_id),
            "question_domain_type": question_domain_type,
            "step_count": len(steps),
        }

        with AgentTraceSpan(self.AGENT_NAME, trace_id=trace_id, metadata=span_metadata) as span:
            t_start = time.perf_counter()

            valid_ids = {s.step_id for s in steps}
            steps_payload = [
                {
                    "step_id": s.step_id,
                    "order": s.order,
                    "step_type": s.step_type.value,
                    "description": s.description,
                    "formula": s.formula,
                    "source_span": s.source_span,
                }
                for s in steps
            ]
            steps_json = json.dumps(steps_payload, ensure_ascii=False, indent=2)

            user_msg = REASONING_GRAPH_USER_TEMPLATE.format(
                question_domain_type=question_domain_type,
                steps_json=steps_json,
            )
            messages = [
                {"role": "system", "content": REASONING_GRAPH_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ]

            final_spec = None
            fallback_occurred = False
            G_final: nx.DiGraph | None = None
            steps_output: list[ReasoningStepGraphOutput] = []
            confidence = 1.0

            # Tentative d'exécution (1 retry en cas de cycle détecté par networkx)
            for attempt in range(2):
                result, spec, fallback, _ = await invoke_llm_with_fallback(
                    task_type=TaskType.REASONING_GRAPH,
                    messages=messages,
                    response_schema=_GraphEnrichmentSchema,
                    context=context,
                )
                final_spec = spec
                fallback_occurred = fallback_occurred or fallback

                try:
                    parsed: _GraphEnrichmentSchema = (
                        result if isinstance(result, _GraphEnrichmentSchema)
                        else _GraphEnrichmentSchema.model_validate(result)
                    )
                    steps_output = self._merge_enrichments(steps, parsed.enrichments, valid_ids)
                    confidence = parsed.construction_confidence
                except Exception as exc:
                    if attempt == 0:
                        continue
                    raise ReasoningGraphError(
                        f"Erreur de parsing de l'enrichissement pour variante {variant_id} : {exc}"
                    ) from exc

                # Validation NetworkX : Détection de cycle DAG
                G = nx.DiGraph()
                for step in steps_output:
                    G.add_node(step.step_ref)

                for step in steps_output:
                    for dep_ref in step.depends_on_refs:
                        if dep_ref in G:
                            G.add_edge(dep_ref, step.step_ref)

                if not nx.is_directed_acyclic_graph(G):
                    cycle_info = str(list(nx.simple_cycles(G)))
                    logger.warning("Cycle détecté dans le graphe (essai %d) pour variante %s : %s", attempt + 1, variant_id, cycle_info)
                    if attempt == 0:
                        retry_msg = REASONING_GRAPH_RETRY_CYCLE_TEMPLATE.format(
                            cycle_details=cycle_info,
                            steps_json=steps_json,
                        )
                        messages.append({"role": "assistant", "content": parsed.model_dump_json()})
                        messages.append({"role": "user", "content": retry_msg})
                        continue
                    else:
                        raise ReasoningGraphCycleError(variant_id, cycle_info)

                # DAG validé ! On conserve G_final
                G_final = G
                break

            if G_final is None:
                raise ReasoningGraphError(f"Échec de la construction du graphe DAG pour variante {variant_id}")

            # ------------------------------------------------------------------
            # Traitements déterministes séquentiels sur G_final uniquement
            # ------------------------------------------------------------------
            clarifications: list[ClarificationRequest] = []

            # 1. Calcul séquentiel des downstream_step_refs (fermeture transitive)
            for step in steps_output:
                descendants = nx.descendants(G_final, step.step_ref)
                step.downstream_step_refs = sorted(list(descendants))

            # 2. Validation de la disponibilité des variables (constraint-based reasoning §9bis)
            self._validate_variable_availability(steps_output, G_final, clarifications)

            # 3. Gardes-fous et seuils d'incertitude -> ClarificationRequest(BLOCKING)
            if confidence < 0.6:
                clarifications.append(
                    ClarificationRequest(
                        related_field="construction_confidence",
                        agent_question=(
                            f"L'agent a exprimé une faible confiance ({confidence:.2f}) "
                            f"sur les dépendances inférées pour le graphe de raisonnement. "
                            f"Veuillez vérifier les arêtes du graphe."
                        ),
                        proposed_answer=None,
                        severity=ClarificationSeverity.BLOCKING,
                    )
                )

            # 4. Garde-fou sur le nombre d'étapes démesuré (> 20) — reflète
            # désormais le découpage d'Agent 4, plus celui de cet agent, mais
            # reste un signal utile de sur-découpage à vérifier.
            if len(steps_output) > 20:
                clarifications.append(
                    ClarificationRequest(
                        related_field="steps_count",
                        agent_question=(
                            f"Le graphe produit comporte {len(steps_output)} étapes (supérieur au plafond recommandé de 20). "
                            f"Vérifiez qu'il n'y a pas eu de sur-découpage artificiel."
                        ),
                        proposed_answer=None,
                        severity=ClarificationSeverity.WARNING,
                    )
                )

            model_version = f"{final_spec.provider}:{final_spec.model_name}" if final_spec else None
            if fallback_occurred and model_version:
                model_version += "+fallback"

            duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
            span.record_metrics(
                step_count=len(steps_output),
                confidence=confidence,
                clarification_count=len(clarifications),
                duration_ms=duration_ms,
                model_version=model_version,
            )

            return ReasoningGraphReport(
                variant_id=variant_id,
                steps=steps_output,
                construction_confidence=confidence,
                clarifications=clarifications,
                is_valid_dag=True,
                model_version=model_version,
            )

    _BASE_COMPETENCY_WEIGHTS: dict[ReasoningStepType, dict[C2PCTSkillCode, float]] = {
        ReasoningStepType.GIVEN_DATA: {
            C2PCTSkillCode.DATA_AND_PLANNING: 0.8,
            C2PCTSkillCode.DECOMPOSITION_AND_ORGANIZATION: 0.2,
        },
        ReasoningStepType.CASE_SPLIT: {
            C2PCTSkillCode.DECOMPOSITION_AND_ORGANIZATION: 0.7,
            C2PCTSkillCode.ALGORITHMIC_STRUCTURING: 0.3,
        },
        ReasoningStepType.FORMULA_APPLICATION: {
            C2PCTSkillCode.ALGORITHMIC_STRUCTURING: 0.6,
            C2PCTSkillCode.DATA_AND_PLANNING: 0.4,
        },
        ReasoningStepType.COMPUTATION: {
            C2PCTSkillCode.ALGORITHMIC_STRUCTURING: 0.7,
            C2PCTSkillCode.DATA_AND_PLANNING: 0.3,
        },
        ReasoningStepType.INTERMEDIATE_RESULT: {
            C2PCTSkillCode.ALGORITHMIC_STRUCTURING: 0.5,
            C2PCTSkillCode.DECOMPOSITION_AND_ORGANIZATION: 0.5,
        },
        ReasoningStepType.CONCLUSION: {
            C2PCTSkillCode.SOLUTION_COMMUNICATION: 0.5,
            C2PCTSkillCode.GENERALIZATION_AND_TRANSFER: 0.3,
            C2PCTSkillCode.SELF_EVALUATION_AND_CREATIVITY: 0.2,
        },
        ReasoningStepType.INVERSE_SOLVE: {
            C2PCTSkillCode.ALGORITHMIC_STRUCTURING: 0.5,
            C2PCTSkillCode.SELF_EVALUATION_AND_CREATIVITY: 0.3,
            C2PCTSkillCode.DATA_AND_PLANNING: 0.2,
        },
    }


    _JUSTIFICATION_MARKERS = {
        "car", "parce que", "puisque", "justification", "explication", "ainsi", "donc"
    }

    def _compute_deterministic_competency_weights(
        self,
        step_type: ReasoningStepType | None,
        tools_used: list[str],
        description: str,
        llm_weights: list[CompetencyWeightProposal] | None = None,
    ) -> list[CompetencyWeightProposal]:
        """
        Calcule de façon déterministe la répartition des 7 composantes C2PCT.

        S_total = 1.0 * S_base(step_type) + 0.4 * S_tools + 0.3 * S_justif
        Chaque score est individuellement plafonné à [0.0, 1.0].
        Le LLM n'intervient qu'en cas d'absence totale de signal (step_type hors table et 0 signal contextuel).
        """
        base_scores = self._BASE_COMPETENCY_WEIGHTS.get(step_type) if step_type else None
        has_tools = bool(tools_used and len(tools_used) > 0)

        desc_lower = description.lower()
        words = set(re.findall(r"\b\w+\b", desc_lower))
        has_justification = any(marker in words or marker in desc_lower for marker in self._JUSTIFICATION_MARKERS)

        has_any_signal = (base_scores is not None) or has_tools or has_justification

        if not has_any_signal and llm_weights:
            weights_by_code = {cw.code: cw.weight for cw in llm_weights}
            return [
                CompetencyWeightProposal(
                    code=code,
                    weight=round(max(0.0, min(1.0, weights_by_code.get(code, 0.0))), 3),
                )
                for code in C2PCTSkillCode
            ]

        scores: dict[C2PCTSkillCode, float] = {code: 0.0 for code in C2PCTSkillCode}

        if base_scores:
            for code, weight in base_scores.items():
                scores[code] += 1.0 * weight

        if has_tools:
            scores[C2PCTSkillCode.SELF_EVALUATION_AND_CREATIVITY] += 0.4 * 1.0

        if has_justification:
            scores[C2PCTSkillCode.SOLUTION_COMMUNICATION] += 0.3 * 0.6
            scores[C2PCTSkillCode.REFLECTION_AND_METACOGNITION] += 0.3 * 0.4

        result: list[CompetencyWeightProposal] = []
        for code in C2PCTSkillCode:
            final_score = min(1.0, max(0.0, scores[code]))
            result.append(CompetencyWeightProposal(code=code, weight=round(final_score, 3)))

        return result

    def _merge_enrichments(
        self,
        steps: list[ExistingStepInput],
        enrichments: list[_StepEnrichmentSchema],
        valid_ids: set[str],
    ) -> list[ReasoningStepGraphOutput]:
        """
        Fusion déterministe : step_ref/order/step_type/description/formula/
        source_span viennent TOUJOURS de `steps` (déjà validés par Agent 4,
        jamais réinventés ici) — seuls depends_on_refs/is_core_step/
        tools_used/concept_tags/competency_weights viennent du LLM.
        depends_on_refs est filtré aux step_id réellement présents en entrée
        (jamais une dépendance fantôme) et ne peut jamais s'auto-référencer.
        Un step d'entrée sans enrichissement correspondant reçoit des valeurs
        par défaut sûres (aucune dépendance, is_core_step=True) plutôt que
        d'être exclu — jamais de perte silencieuse d'une étape d'Agent 4.
        """
        enrich_by_id = {e.step_id: e for e in enrichments}
        result: list[ReasoningStepGraphOutput] = []
        for s in steps:
            e = enrich_by_id.get(s.step_id)
            depends_on_refs = [
                r for r in (e.depends_on_refs if e else [])
                if r in valid_ids and r != s.step_id
            ]
            tools_used = list(e.tools_used) if e else []
            llm_weights = [
                CompetencyWeightProposal(code=cw.code, weight=cw.weight)
                for cw in (e.competency_weights if e else [])
            ]
            weights = self._compute_deterministic_competency_weights(
                step_type=s.step_type,
                tools_used=tools_used,
                description=s.description,
                llm_weights=llm_weights,
            )
            result.append(ReasoningStepGraphOutput(
                step_ref=s.step_id,
                order=s.order,
                step_type=s.step_type,
                description=s.description,
                formula=s.formula,
                concept_tags=list(e.concept_tags) if e else [],
                tools_used=tools_used,
                competency_weights=weights,
                is_core_step=e.is_core_step if e else True,
                depends_on_refs=depends_on_refs,
                source_span=s.source_span,
            ))
        return result

    # Même motif d'identifiant que _VAR_PATTERN (cf. son commentaire) — sans
    # ce même fix, une définition "K_{red} = ..." ne matchait pas du tout
    # (le "{" cassait la capture avant même d'atteindre le "="), laissant
    # K_red jamais enregistré comme défini pour les étapes suivantes.
    _ASSIGNMENT_PATTERN = re.compile(r"([a-zA-Z][a-zA-Z0-9]*(?:_\{?\s*[a-zA-Z0-9]+\s*\}?)?)\s*(?:=|\:=|:)", re.MULTILINE)

    @staticmethod
    def _normalize_var_token(raw: str) -> str:
        """
        Un même symbole doit produire la MÊME clé de comparaison qu'il soit
        écrit avec ou sans accolades/espace parasite (K_{red}, K_{ red },
        K_red doivent tous normaliser vers "k_red") — sans ça, une
        définition braced et une consommation non-braced du même symbole
        (ou l'inverse) se manqueraient mutuellement malgré le fix de
        _VAR_PATTERN/_ASSIGNMENT_PATTERN ci-dessus.
        """
        return raw.replace("{", "").replace("}", "").replace(" ", "").lower()

    # Cause 2a (backlog, 2026-08-30) : "l_i"/"n_i" (longueur et effort
    # virtuel PAR BARRE, méthode de la charge unitaire/Maxwell-Mohr) sont
    # des DONNÉES du problème (géométrie, système de charge fictive
    # standard), jamais un résultat à dériver par une étape GIVEN_DATA
    # explicite — un professeur/étudiant ne "calcule" pas la longueur d'une
    # barre, il la lit sur le schéma. Motif générique sur le PRÉFIXE (l_/n_
    # + n'importe quel indice), jamais une liste figée de noms exacts
    # (l_5, l_i, l_a... tous couverts pareil).
    _IMPLICIT_BASE_QUANTITY_PATTERN = re.compile(r"^[ln]_[a-z0-9]+$")

    # E (module de Young), A (aire), I (inertie), G (module de cisaillement),
    # L (longueur) — constantes matérielles/géométriques quasi universelles
    # en mécanique des structures, presque jamais introduites par leur PROPRE
    # étape GIVEN_DATA à une lettre (le professeur/LLM les mentionne dans le
    # matériau — "acier S275" — ou les utilise directement dans une formule
    # composée, jamais "E = ..." isolé) — jamais flaguées seules de toute
    # façon (filtre déjà existant len(v) > 1), utilisées ICI uniquement pour
    # que la décomposition d'un symbole composé (EA, EI...) puisse aboutir
    # même si E/A n'apparaissent nulle part ailleurs comme tokens isolés
    # dans CETTE variante précise.
    _IMPLICIT_SINGLE_LETTER_QUANTITIES = frozenset({"e", "a", "i", "g", "l"})

    @classmethod
    def _is_recognized_compound_symbol(cls, token: str, available_vars: set[str]) -> bool:
        """
        Cause 2b (backlog, 2026-08-30) : "ea" (= E×A, rigidité axiale —
        convention de juxtaposition très répandue en mécanique des
        structures : EA, EI, GJ...) n'est jamais lui-même introduit sous ce
        nom composé — seuls E et A le sont, séparément (ou implicitement,
        cf. _IMPLICIT_SINGLE_LETTER_QUANTITIES). Reconnaissance MÉCANIQUE
        (chaque lettre du token doit déjà être, individuellement, un
        symbole disponible ou une constante implicite) — jamais une liste
        figée de noms composés connus (EA, EI...), qui ne couvrirait que
        les cas déjà vus.
        """
        if "_" in token or len(token) < 2:
            return False
        return all(ch in available_vars or ch in cls._IMPLICIT_SINGLE_LETTER_QUANTITIES for ch in token)

    @classmethod
    def _strip_latex_noise(cls, text: str) -> str:
        text = cls._LATEX_TEXT_BLOCK_RE.sub(" ", text)
        return cls._LATEX_COMMAND_RE.sub(" ", text)

    def _validate_variable_availability(
        self,
        steps: list[ReasoningStepGraphOutput],
        G: nx.DiGraph,
        clarifications: list[ClarificationRequest],
    ) -> None:
        """
        Vérification constraint-based reasoning (§9bis) :
        S'assure que chaque symbole de variable utilisé dans une étape est soit
        posé dans une étape GIVEN_DATA, soit produit dans un ancêtre direct/indirect
        de SA PROPRE chaîne de dépendance (networkx.ancestors(G, step_ref)).

        consumed_vars_by_ref est dérivé du SEUL formula (jamais description) :
        un symbole "consommé nécessitant une définition" est par nature un
        symbole algébrique, pas un mot de la prose française qui décrit
        l'étape (ex. "cosinus", "exploitation", "appuis" ne sont pas des
        variables) — description reste utilisée pour defined_vars_by_ref
        des étapes GIVEN_DATA uniquement (une donnée posée en toutes lettres,
        sans formule, doit quand même compter comme "définie").
        """
        steps_by_ref = {s.step_ref: s for s in steps}
        defined_vars_by_ref: dict[str, set[str]] = {}
        consumed_vars_by_ref: dict[str, set[str]] = {}

        for s in steps:
            formula_clean = self._strip_latex_noise(s.formula) if s.formula else ""
            text = f"{s.description} {formula_clean}"
            all_tokens = {self._normalize_var_token(v) for v in self._VAR_PATTERN.findall(text)} - self._RESERVED_WORDS
            formula_tokens = {self._normalize_var_token(v) for v in self._VAR_PATTERN.findall(formula_clean)} - self._RESERVED_WORDS

            lhs_matches = self._ASSIGNMENT_PATTERN.findall(formula_clean or s.description)
            lhs_vars = {self._normalize_var_token(v) for v in lhs_matches} - self._RESERVED_WORDS

            if s.step_type == ReasoningStepType.GIVEN_DATA:
                defined_vars_by_ref[s.step_ref] = all_tokens
                consumed_vars_by_ref[s.step_ref] = set()
            else:
                defined_vars_by_ref[s.step_ref] = lhs_vars if lhs_vars else set()
                consumed_vars_by_ref[s.step_ref] = formula_tokens - lhs_vars

        for s in steps:
            if s.step_type == ReasoningStepType.GIVEN_DATA:
                continue

            used_vars = consumed_vars_by_ref[s.step_ref]
            if not used_vars:
                continue

            ancestors = nx.ancestors(G, s.step_ref)
            available_vars: set[str] = set()

            for anc_ref in ancestors:
                available_vars.update(defined_vars_by_ref.get(anc_ref, set()))

            for given_ref, given_step in steps_by_ref.items():
                if given_step.step_type == ReasoningStepType.GIVEN_DATA:
                    available_vars.update(defined_vars_by_ref.get(given_ref, set()))

            missing = used_vars - available_vars
            missing = {v for v in missing if not v.isdigit() and len(v) > 1}
            # Cause 2 (backlog, 2026-08-30) — deux catégories de faux positifs
            # DISTINCTES du bug de parsing ci-dessus, jamais un symbole
            # réellement absent de la chaîne de dépendances :
            missing = {
                v for v in missing
                if not self._is_recognized_compound_symbol(v, available_vars)
                and not self._IMPLICIT_BASE_QUANTITY_PATTERN.match(v)
            }
            if missing:
                clarifications.append(
                    ClarificationRequest(
                        related_field=f"steps[{s.step_ref}].variable_availability",
                        agent_question=(
                            f"L'étape « {s.step_ref} » ({s.description}) utilise des symboles ({', '.join(sorted(missing))}) "
                            f"qui ne figurent pas dans la chaîne de dépendances directes de cette étape. "
                            f"Veuillez vérifier les arêtes du graphe."
                        ),
                        proposed_answer=None,
                        # WARNING, pas BLOCKING (2026-08-30) — ce contrôle est un
                        # parsing heuristique sur du texte quasi-naturel (LaTeX
                        # généré librement par un LLM), jamais garanti fiable à
                        # 100% (5 faux positifs confirmés sur un seul test réel,
                        # cf. backlog). Un faux positif ici NE DOIT JAMAIS geler
                        # tout le pipeline exercise_setup via la pause HITL de
                        # reasoning_graph_node.py (qui ne compte que les
                        # clarifications BLOCKING) — un vrai symbole orphelin
                        # reste visible et vérifiable par le professeur, mais
                        # sans bloquer la publication.
                        severity=ClarificationSeverity.WARNING,
                    )
                )
