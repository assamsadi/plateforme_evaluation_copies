"""
ExtractionCorrection = l'extraction OCR/agent pour UNE question d'UNE
soumission, avec la correction éventuelle demandée par l'étudiant.

Triplet exploité pour le fine-tuning OCR périodique (§6) :
(image_crop_path, prediction_ocr, human_correction, confidence_score).

content_type + structured_output : distinguent texte / équation / schéma
pour permettre à l'agent de comparaison d'appliquer une stratégie adaptée
(comparaison symbolique pour une équation, pas juste texte brut).

bounding_box : ancrage visuel (§4.2 CHAABI, "Visual Grounding") — toute
contestation étudiante doit pouvoir être localisée précisément sur
l'image source, jamais acceptée sur la seule parole de l'étudiant.

page_number : nécessaire à Contestation_Verification_Agent (Cas A/C) pour
ré-imprimer la page en pleine résolution depuis le document original —
image_crop_path seul ne suffit pas s'il a été compressé pour le stockage.

Champs de contestation (Contestation_Verification_Agent) :
- human_correction reste la réclamation ORIGINALE de l'étudiant, jamais
  écrasée une fois posée (§9bis — chronologie complète nécessaire).
- verified_content porte la vérité tranchée (PLAUSIBLE auto-accepté, ou
  décision professeur) — distinct de human_correction précisément pour
  ne jamais perdre la réclamation d'origine.
- contestation_type distingue les 4 cas (contenu/rattachement/élément
  STRUCTURE/fusion) — jamais un champ texte libre.
- contestation_status trace l'état du traitement, sert aussi de verrou
  "un seul passage automatique" (§8 du doc de référence agent).
- contested_element_id (Cas C) référence l'id d'un élément dans
  structured_output ; claimed_question_id/claimed_section_id (Cas B) la
  question/section réclamée par l'étudiant.
- fused_extraction_correction_ids trace les lignes fusionnées par
  Question_Attachment_Agent lors de la continuité inter-pages/renvoi —
  nécessaire pour que Contestation_Verification_Agent puisse retrouver
  le partenaire de fusion d'un bloc contesté (Cas D).
"""
import uuid
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class ExtractionContentType(StrEnum):
    TEXT = "TEXT"
    EQUATION = "EQUATION"
    DIAGRAM = "DIAGRAM"
    STRUCTURE = "STRUCTURE"


class StructureType(StrEnum):
    TABLE = "TABLE"
    FORM = "FORM"
    ANNOTATED_DIAGRAM = "ANNOTATED_DIAGRAM"
    MULTI_COLUMN_LIST = "MULTI_COLUMN_LIST"
    OTHER = "OTHER"


class ExtractionOrigin(StrEnum):
    PRINTED = "PRINTED"
    HANDWRITTEN = "HANDWRITTEN"


class ExtractionEvidenceLevel(StrEnum):
    LABEL_EXPLICITE = "label_explicite"       # un label écrit "Q1", "Ex2.a", etc. était présent
    CONTENU_VS_REFERENCE = "contenu_vs_reference"  # rattaché par comparaison structurelle au corrigé
    AMBIGU = "ambigu"                         # rattachement probable mais non certain
    ORPHELIN = "orphelin"                     # bloc non rattaché à aucune question


class ContestationType(StrEnum):
    CONTENT = "content"                        # Cas A — transcription en cause
    ATTACHMENT = "attachment"                  # Cas B — question/section en cause
    STRUCTURE_ELEMENT = "structure_element"    # Cas C — un élément interne d'une STRUCTURE
    FUSION = "fusion"                          # Cas D — la fusion de continuité elle-même


class ContestationStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"  # contestation posée, agent pas encore passé
    PLAUSIBLE = "plausible"
    IMPLAUSIBLE = "implausible"
    AMBIGU = "ambigu"                              # en attente de CorrectionArbitration
    RESOLVED = "resolved"                          # AMBIGU tranché par le professeur


class ExtractionCorrection(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "extraction_corrections"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=True
    )

    image_crop_path: Mapped[str] = mapped_column(Text, nullable=False)  # blob_path Azure
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[ExtractionContentType] = mapped_column(
        PgEnum(ExtractionContentType, name="extraction_content_type"), nullable=False
    )
    prediction_ocr: Mapped[str] = mapped_column(Text, nullable=False)

    # Ex équation: {"latex": "I = \\frac{bh^3}{12}"} ; ex schéma: {"elements": [...]}
    structured_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    human_correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)

    # {"x": 120, "y": 340, "width": 200, "height": 60} — coordonnées sur image_crop_path
    bounding_box: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Niveau de confiance du rattachement à la question (produit par l'agent OCR)
    evidence_level: Mapped[ExtractionEvidenceLevel] = mapped_column(
        PgEnum(ExtractionEvidenceLevel, name="extraction_evidence_level", values_callable=lambda x: [e.value for e in x]), nullable=False
    )

    # --- Contestation_Verification_Agent ---
    contestation_type: Mapped[ContestationType | None] = mapped_column(
        PgEnum(ContestationType, name="contestation_type", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    contestation_status: Mapped[ContestationStatus | None] = mapped_column(
        PgEnum(ContestationStatus, name="contestation_status", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    contested_element_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_question_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=True
    )
    claimed_section_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercise_sections.id"), nullable=True
    )
    verified_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    fused_extraction_correction_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)