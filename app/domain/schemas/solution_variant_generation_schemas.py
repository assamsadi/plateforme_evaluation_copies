"""
Schémas Pydantic pour la génération de variantes de solution et le rapport de revue professeur.
"""
from enum import StrEnum
import uuid
from typing import Optional
from pydantic import BaseModel, Field

from datetime import datetime

from app.domain.models.assessment.solution_variant import VariantDifficulty, VariantSource, VariantStatus


class VariantReviewAction(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


class ReferenceStepContext(BaseModel):
    """
    Formule + description d'une étape de référence, pour
    _verify_intermediate_consistency / _resolve_symbol_correspondences —
    remplace l'ancien `reference_formulas: list[str]` (bare, sans contexte)
    qui jetait la description alors qu'elle était déjà chargée côté service
    (`ref_steps`), nécessaire pour établir une correspondance sémantique
    entre un symbole générique et sa version spécialisée (cf. mémoire de
    session 2026-08-17).
    """
    formula: str
    description: str = ""


class CandidateStepSummarySchema(BaseModel):
    order: int
    step_type: str = "computation"
    description: str
    # Équation posée AVANT résolution (ex. "ΣM_O = 0 : N_1·h_1 + N_5·h_5 -
    # P·d = 0"), distincte de `formula` (le résultat une fois résolu, ex.
    # "N_5 = 3P√5") — sans ce champ séparé, le LLM se contentait
    # systématiquement de recopier le résultat final déjà connu (visible
    # dans la solution de référence donnée en contexte) sans jamais montrer
    # comment la méthode revendiquée (Ritter, énergie, matricielle...) y
    # mène réellement, constaté sur 2 générations réelles consécutives
    # malgré une instruction textuelle en ce sens (cf. Solution_Variant_
    # Generation_Agent v1.10) — vérifié non vide par le code pour les step_
    # type formula_application/computation, jamais laissé à une simple
    # consigne de prompt.
    derivation: Optional[str] = None
    formula: Optional[str] = None
    concept_tags: list[str] = Field(default_factory=list)


class GeneratedVariantCandidateSchema(BaseModel):
    strategy_name: str
    content: str
    reasoning_summary: str
    difficulty_level: VariantDifficulty = VariantDifficulty.INTERMEDIAIRE
    conclusion_formula: Optional[str] = None
    concept_tags: list[str] = Field(default_factory=list)
    steps_summary: list[CandidateStepSummarySchema] = Field(default_factory=list)
    outside_academic_envelope: bool = False
    outside_concepts: list[str] = Field(default_factory=list)


class VariantStrategyAttemptLog(BaseModel):
    strategy_name: str
    attempt_number: int
    status: str  # "ACCEPTED", "REJECTED_SYMPY", "REJECTED_INCONSISTENT", "REJECTED_DUPLICATE", "REJECTED_SCHEMA", "REJECTED_NO_DERIVATION", "REJECTED_CORRUPTED_LATEX"
    rejection_reason: Optional[str] = None
    distinction_score: Optional[float] = None
    # Nombre de grandeurs intermédiaires réellement comparées (référence ET
    # candidat partageaient un symbole résolvable) par
    # _verify_intermediate_consistency — 0 signifie qu'AUCUNE comparaison n'a
    # pu avoir lieu (jamais confondu avec "vérifié cohérent" : un candidat
    # jamais comparé ne doit jamais porter le même statut qu'un candidat
    # réellement prouvé équivalent, cf. gap trouvé le 2026-08-17).
    intermediate_verified_count: Optional[int] = None
    intermediate_check_note: Optional[str] = None


class VariantGenerationAgentReport(BaseModel):
    question_id: uuid.UUID
    candidates: list[GeneratedVariantCandidateSchema] = Field(default_factory=list)
    attempt_logs: list[VariantStrategyAttemptLog] = Field(default_factory=list)
    total_llm_calls: int = 0
    skipping_reason: Optional[str] = None  # ex: "mandated_method"
    # Dernier fournisseur:modèle ayant réellement répondu (None si aucun
    # appel LLM n'a eu lieu, ex. skipping_reason renseigné) — cf. docstring
    # Solution_Variant_Generation_Agent.execute() pour le bug corrigé.
    model_version: Optional[str] = None


class VariantReviewRequest(BaseModel):
    # Optionnel : POST /solution-variants/{variant_id}/review (router)
    # écrase TOUJOURS ce champ avec l'UUID du chemin d'URL (jamais celui du
    # corps, cf. sa docstring "variant_id vient toujours du chemin, jamais
    # du corps") — le rendre requis forçait pourtant le frontend à l'envoyer
    # en double dans le corps JSON, provoquant un 422 "Field required" dès
    # qu'il en manquait (constaté en test réel : reviewSolutionVariant()
    # n'envoie que {action}, jamais variant_id).
    variant_id: uuid.UUID | None = None
    action: VariantReviewAction
    modified_content: Optional[str] = None
    modified_summary: Optional[str] = None
    review_comment: Optional[str] = None
    # Utilisés UNIQUEMENT quand action == REJECTED (cf. mémoire de session) :
    # review_variant_decision déclenche automatiquement une nouvelle
    # génération guidée pour la question après un rejet — ces 2 champs, s'ils
    # sont renseignés, pilotent CETTE régénération exactement comme le
    # déclencheur guidé existant (2.3, GuidedVariantGenerationRequest).
    # Silencieusement ignorés pour toute autre action.
    method_hint: Optional[str] = None
    concept_hint: Optional[list[str]] = None


class SolutionVariantSummaryRead(BaseModel):
    """
    Ligne de liste pour GET /questions/{question_id}/solution-variants —
    volontairement plus léger que SolutionVariantRead (solution_schemas.py) :
    ce dernier exige reasoning_steps: list[ReasoningStepRead] (agrégat
    imbriqué complet, et référence une relation ORM SolutionVariant.
    reasoning_steps qui n'existe pas réellement, bug préexistant hors
    périmètre ici) — inadapté à une simple liste de découverte. Construit
    manuellement depuis structured_content (jamais via model_validate/
    from_attributes, ces champs ne sont pas de vraies colonnes).
    """
    id: uuid.UUID
    question_id: uuid.UUID
    is_reference: bool
    source: VariantSource
    difficulty_level: VariantDifficulty
    status: VariantStatus
    strategy_name: Optional[str] = None
    distinction_score: Optional[float] = None
    reasoning_summary: Optional[str] = None
    # Absent jusqu'ici de ce résumé "léger" — le professeur ne voyait donc
    # JAMAIS le texte réel de la solution dans "Voir les variantes", juste
    # reasoning_summary (une phrase de résumé, jamais la solution complète),
    # constaté en test réel ("solution incomplète" alors que le contenu
    # réel était bien complet en base, simplement jamais transmis ici).
    content: str
    created_at: datetime


class RetroactiveEquityReport(BaseModel):
    exercise_id: uuid.UUID
    question_id: uuid.UUID
    newly_accepted_variant_id: uuid.UUID
    impacted_submission_ids: list[uuid.UUID] = Field(default_factory=list)
    message: str


class VariantReviewResponse(BaseModel):
    """Réponse de l'endpoint des 4 actions (Accepter/Refuser/Modifier/Supprimer)."""
    variant_id: Optional[uuid.UUID] = None
    status: Optional[VariantStatus] = None
    content: Optional[str] = None
    deleted: bool = False
    retroactive_equity: Optional[RetroactiveEquityReport] = None
    # Traçabilité (cf. mémoire de session) : None pour une variante non
    # générée par IA (créée manuellement par le professeur, structured_
    # content n'a jamais ces clés dans ce cas) — jamais une valeur inventée.
    strategy_name: Optional[str] = None
    distinction_score: Optional[float] = None
    intermediate_check_note: Optional[str] = None


class GuidedVariantGenerationRequest(BaseModel):
    """Corps de requête du déclencheur guidé (2.3) — method_hint/concept_hint
    optionnels, périmètre strict respecté par l'agent (jamais une exploration
    hors de ce qui est demandé, cf. audit §1)."""
    method_hint: Optional[str] = None
    concept_hint: Optional[list[str]] = None


class GuidedVariantGenerationAck(BaseModel):
    question_id: uuid.UUID
    status: str = "queued"
