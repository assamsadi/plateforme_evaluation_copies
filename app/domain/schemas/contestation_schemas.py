"""
Schemas Pydantic pour Contestation_Verification_Agent.

ContestExtractionRequest : contrat d'entrée du endpoint de contestation
étudiant — porte un indicateur de type explicite (4 cas distincts), jamais
un champ texte libre unique (§2 étape 2 du doc de référence agent).

ContestationVerdict : contrat de sortie de l'agent, avant persistance par
contestation_verification_service.py. Porte la traçabilité complète exigée
par §9 (version exacte de l'image utilisée, modèle réel y compris fallback)
pour reconstituer les conditions exactes d'une décision en cas de
contestation ultérieure (grade_appeal_service.py).
"""
import uuid
from typing import Literal

from pydantic import BaseModel, model_validator

from app.domain.models.assessment.extraction_correction import ContestationType


class ContestExtractionRequest(BaseModel):
    contestation_type: ContestationType
    # Cas A (contenu) ou Cas C (valeur réclamée pour l'élément STRUCTURE)
    claimed_content: str | None = None
    # Cas C — id de l'élément contesté dans structured_output (cellule, champ, nœud)
    contested_element_id: str | None = None
    # Cas B — au moins un des deux ; les deux ensemble = rattachement élargi (§4)
    claimed_question_id: uuid.UUID | None = None
    claimed_section_id: uuid.UUID | None = None
    # Cas D
    fusion_claim: Literal["wrongly_merged", "should_have_merged"] | None = None

    @model_validator(mode="after")
    def _validate_fields_for_type(self) -> "ContestExtractionRequest":
        if self.contestation_type == ContestationType.CONTENT and not self.claimed_content:
            raise ValueError("claimed_content requis pour une contestation de type CONTENT")
        if self.contestation_type == ContestationType.STRUCTURE_ELEMENT and (
            not self.claimed_content or not self.contested_element_id
        ):
            raise ValueError(
                "claimed_content et contested_element_id requis pour une contestation "
                "de type STRUCTURE_ELEMENT"
            )
        if self.contestation_type == ContestationType.ATTACHMENT and (
            self.claimed_question_id is None and self.claimed_section_id is None
        ):
            raise ValueError(
                "claimed_question_id et/ou claimed_section_id requis pour une contestation "
                "de type ATTACHMENT"
            )
        if self.contestation_type == ContestationType.FUSION and self.fusion_claim is None:
            raise ValueError("fusion_claim requis pour une contestation de type FUSION")
        return self


class ContestationVerdict(BaseModel):
    extraction_correction_id: uuid.UUID
    contestation_type: ContestationType
    verdict: Literal["PLAUSIBLE", "IMPLAUSIBLE", "AMBIGU"]
    verified_content: str | None = None  # None si AMBIGU
    justification: str
    # Cas A/C uniquement
    ocr2_result: str | None = None
    ocr2_confidence: float | None = None
    full_resolution_crop_path: str | None = None  # §9 — chemin exact utilisé, jamais une référence vague
    # Cas B uniquement
    resolved_question_id: uuid.UUID | None = None
    resolved_section_id: uuid.UUID | None = None
    # Cas D uniquement
    fused_correction_ids: list[uuid.UUID] | None = None
    defusion_applied: bool = False
    model_version: str  # §9/§10 — modèle réellement utilisé, fallback inclus
    anomaly_flag: bool = False  # ligne 3 de la table de vérité — cas dégénéré, signalement d'audit
    # §7 — relevé par l'agent pour un verdict tranché (PLAUSIBLE/IMPLAUSIBLE),
    # None si AMBIGU (le score reste bas jusqu'à la décision du professeur,
    # cf. correction_arbitration_repository.create_and_apply_verdict).
    confidence_score: float | None = None
