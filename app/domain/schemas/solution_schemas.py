"""
Schemas Pydantic pour SolutionVariant/ReasoningStep.

Défi de conception : ReasoningStep forme un graphe (DAG). À la création,
les étapes n'ont pas encore d'UUID (créées ensemble, même requête) —
donc les dépendances entre étapes utilisent une référence TEMPORAIRE
côté client (step_ref, ex. "s1"), résolue en vrais UUID par le service
après insertion.

Détection de cycle par DFS appliquée ICI, sur le graphe temporaire
(step_ref), en plus de celle prévue côté repository sur le graphe déjà
persisté (reasoning_step_repository.py) — fail-fast avant la DB.

SolutionVariant est la racine d'agrégat pour ReasoningStep (même
principe que Exercise/Question) : imbrication complète.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationSeverity,
    ClarificationStatus,
    ComparativeClarificationKind,
)
from app.domain.models.assessment.reasoning_step import ReasoningStepType
from app.domain.models.assessment.solution_variant import VariantDifficulty, VariantSource, VariantStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode


# --- ReasoningStep ---

class ReasoningStepCreate(BaseModel):
    step_ref: str  # référence temporaire unique DANS cette requête, ex: "s1"
    order: int
    step_type: ReasoningStepType
    description: str
    formula: str | None = None
    concept_tags: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    related_competency_code: C2PCTSkillCode | None = None
    depends_on_refs: list[str] = Field(default_factory=list)  # step_ref d'autres étapes


class ReasoningStepRead(BaseModel):
    id: uuid.UUID
    variant_id: uuid.UUID
    order: int
    step_type: ReasoningStepType
    description: str
    formula: str | None
    concept_tags: list[str]
    tools_used: list[str]
    related_competency_code: C2PCTSkillCode | None
    related_competency_name: str | None  # aplati, résolu depuis le fichier .md côté agent
    depends_on_step_ids: list[uuid.UUID]  # résolus (vrais UUID, plus des step_ref)

    model_config = {"from_attributes": True}


class ReasoningStepUpdateRequest(BaseModel):
    """
    Correction ciblée d'UNE étape du graphe de raisonnement par le professeur
    (cf. mémoire de session) — distinct de VariantReviewRequest(action=
    MODIFIED), qui ne permet que de réécrire TOUT le `content` en bloc. Une
    petite erreur dans une seule étape (une dérivation fausse, une formule
    mal recopiée) obligeait jusqu'ici à retaper toute la solution autour
    pour la corriger. `step_type`/`order`/dépendances restent inchangés :
    seul le contenu de l'étape (texte, formule) est corrigible ici, jamais
    sa position dans le graphe.
    """
    description: str | None = None
    formula: str | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> "ReasoningStepUpdateRequest":
        if self.description is None and self.formula is None:
            raise ValueError("Au moins un champ (description ou formula) doit être fourni.")
        return self


class ReasoningStepUpdateResponse(BaseModel):
    """
    Réponse allégée de PATCH /reasoning-steps/{step_id} — volontairement PAS
    ReasoningStepRead (qui exige depends_on_step_ids/related_competency_name,
    jamais modifiés par une correction ciblée et donc pas ré-résolus ici) :
    le frontend a déjà ces champs depuis le chargement initial du graphe,
    seuls description/formula viennent d'être corrigés.
    """
    id: uuid.UUID
    description: str
    formula: str | None


# --- SolutionVariant ---

class SolutionVariantCreate(BaseModel):
    question_id: uuid.UUID
    content: str
    structured_content: dict | None = None
    reasoning_summary: str | None = None
    is_reference: bool = False
    source: VariantSource
    difficulty_level: VariantDifficulty
    reasoning_steps: list[ReasoningStepCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reasoning_graph(self) -> "SolutionVariantCreate":
        self._check_refs_exist()
        self._check_no_cycle()
        return self

    def _check_refs_exist(self) -> None:
        known_refs = {s.step_ref for s in self.reasoning_steps}
        if len(known_refs) != len(self.reasoning_steps):
            raise ValueError("Les step_ref doivent être uniques dans une même requête")
        for step in self.reasoning_steps:
            for dep in step.depends_on_refs:
                if dep not in known_refs:
                    raise ValueError(
                        f"L'étape '{step.step_ref}' dépend de '{dep}', "
                        f"qui n'existe pas dans cette requête"
                    )
                if dep == step.step_ref:
                    raise ValueError(f"L'étape '{step.step_ref}' ne peut pas dépendre d'elle-même")

    def _check_no_cycle(self) -> None:
        """
        DFS classique avec pile de récursion : si on retombe sur un nœud
        encore "en cours de visite" (pas juste "déjà visité"), il y a un
        cycle. Complexité O(V + E). Même algorithme prévu côté
        reasoning_step_repository.py pour les graphes déjà persistés.
        """
        graph = {s.step_ref: s.depends_on_refs for s in self.reasoning_steps}
        visited: set[str] = set()
        in_progress: set[str] = set()

        def dfs(node: str) -> None:
            if node in in_progress:
                raise ValueError(f"Cycle détecté dans le graphe de raisonnement (via '{node}')")
            if node in visited:
                return
            in_progress.add(node)
            for neighbor in graph.get(node, []):
                dfs(neighbor)
            in_progress.discard(node)
            visited.add(node)

        for step_ref in graph:
            if step_ref not in visited:
                dfs(step_ref)


class SolutionVariantRead(BaseModel):
    id: uuid.UUID
    question_id: uuid.UUID
    content: str
    structured_content: dict | None
    reasoning_summary: str | None
    is_reference: bool
    source: VariantSource
    difficulty_level: VariantDifficulty
    status: VariantStatus
    validated_by_professor_id: uuid.UUID | None
    review_comment: str | None
    reasoning_steps: list[ReasoningStepRead]  # imbriqué, même agrégat

    model_config = {"from_attributes": True}


class VariantValidationRequest(BaseModel):
    status: VariantStatus
    review_comment: str | None = None


# --- ReasoningClarificationRequest ---
# Mécanisme d'Active Learning (§ conversation) : le Reasoning Graph Agent
# pose une question au prof face à une partie floue de sa correction,
# AVANT de créer la ReasoningStep correspondante — jamais de correction
# rétroactive d'une étape déjà enregistrée.

class ReasoningClarificationRequestCreate(BaseModel):
    """Créé par l'agent (pas par un utilisateur humain), via le service
    appelé depuis le node LangGraph correspondant à l'interrupt
    REASONING_CLARIFICATION."""
    variant_id: uuid.UUID
    unclear_content: str
    agent_question: str


class ReasoningClarificationAnswerRequest(BaseModel):
    """Réponse du professeur à la question de l'agent."""
    professor_answer: str


class ValidateAlternativeAnswerRequest(BaseModel):
    """
    Câblage HITL indexation RAG (Priorité 1) — décision du professeur sur
    une clarification MULTIPLE_DISTINCT_ANSWERS (Comparative_Evaluation_
    Agent) : accepte ou rejette la réponse candidate de l'étudiant comme
    variante légitime. Jamais un texte libre (cf. ReasoningClarification
    AnswerRequest) détourné pour encoder cette décision booléenne.
    """
    accepted: bool


class ResolveCoherenceAmbiguityRequest(BaseModel):
    """
    Correctif AMBIGUOUS_COHERENCE — décision du professeur sur une
    clarification MULTIPLE_DISTINCT_ANSWERS de sous-type COHERENCE_
    AMBIGUITY : PAS un accept/reject de réponse candidate (cf.
    ValidateAlternativeAnswerRequest, sémantique différente), une décision
    sur la nature même du cas — "comme si le filtre de cohérence avait
    initialement renvoyé COHERENT ou INCOHERENT".
    """
    resolved_as: Literal["coherent", "incoherent"]


class ReasoningClarificationRequestRead(BaseModel):
    id: uuid.UUID
    # Nullable depuis la Phase 6 : élargi à des agents qui référencent une
    # Question/un Bareme (related_entity_type/related_entity_id) plutôt
    # qu'une SolutionVariant — les deux formes sont mutuellement exclusives.
    variant_id: uuid.UUID | None
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    # Câblage HITL indexation RAG — non-None uniquement pour les
    # clarifications MULTIPLE_DISTINCT_ANSWERS (Comparative_Evaluation_Agent).
    # Défaut None (pas juste Optional) : les appelants existants (mocks de
    # test, réponses construites à la main) qui ne le fournissent pas
    # doivent rester valides — champ ajouté après coup, jamais rétroactivement
    # obligatoire.
    criterion_id: str | None = None
    # Correctif AMBIGUOUS_COHERENCE — discriminant entre les 2 sous-types
    # MULTIPLE_DISTINCT_ANSWERS (cf. docstring modèle ComparativeClarification
    # Kind). Mêmes défauts None que criterion_id ci-dessus.
    comparative_clarification_kind: ComparativeClarificationKind | None = None
    resolved_as_coherent: bool | None = None
    unclear_content: str | None
    agent_question: str
    proposed_answer: str | None
    severity: ClarificationSeverity
    status: ClarificationStatus
    professor_answer: str | None
    answered_by_professor_id: uuid.UUID | None
    answered_by_professor_name: str | None  # aplati
    answered_at: datetime | None
    resulting_step_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}