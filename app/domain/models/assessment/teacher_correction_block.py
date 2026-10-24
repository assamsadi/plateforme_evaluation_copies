"""
TeacherCorrectionBlock = un bloc de la correction du professeur tel qu'extrait
par le Document_Structuring_Agent lors de l'analyse du document déposé.

Chaque bloc correspond à une zone de l'image identifiée comme appartenant
à la correction d'un exercice (et éventuellement d'une question précise).
Le level d'évidence trace la confiance du rattachement :
  - LABEL_EXPLICITE : un label textuel ("Q1", "Ex2.a") était présent
  - INFERRED_SINGLE_QUESTION : aucun label, mais une seule Question existait
    dans la section — rattachement automatique sans ambiguïté possible
  - CONTENT_MATCHED : aucun label, plusieurs Questions candidates — rattaché
    par correspondance de contenu via un passage LLM dédié (jamais un label)
  - UNRESOLVED_NO_LABEL : aucun label ET aucune décision fiable possible
    (déterministe ou par le sens), l'agent ne peut pas décider seul

Seuls les blocs UNRESOLVED_NO_LABEL déclenchent une ReasoningClarification
Request (mécanisme HITL) avant que l'exercice puisse être publié (complétude
bloquante vérifiée dans exercise_service.publish() /
teacher_correction_block_repository.list_unresolved_by_exercise, qui filtre
strictement sur cette valeur) — LABEL_EXPLICITE, INFERRED_SINGLE_QUESTION et
CONTENT_MATCHED sont tous les trois des blocs RÉSOLUS (question_id renseigné),
jamais bloquants, qui ne diffèrent que par le degré de confiance affiché au
professeur.

professor_resolution : rempli par le prof si le bloc était UNRESOLVED —
trace la décision humaine pour la boucle d'apprentissage few-shot (§6).

ocr_confidence (B11, backlog_bugs_c2pct.md) : combined_confidence calculée
par OCR_Extraction_Agent (déjà portée par RawExtractedBlock.confidence_score,
déjà après la relecture ciblée éventuelle) — jusqu'ici jamais transmise
jusqu'ici, un bloc mal lu restait indiscernable d'un bloc fiable dans
l'interface professeur. Nullable : blocs créés avant ce champ, ou tout bloc
sans confiance OCR à proprement parler (aucun cas actuel, mais pas garanti
à vie). Flag visible non-bloquant (cf. TeacherCorrectionBlockRead.
is_low_ocr_confidence) — contrairement à UNRESOLVED_NO_LABEL, ne bloque
jamais la publication : une confiance OCR faible est un signal à vérifier,
pas une ambiguïté de rattachement sans décision possible.
"""
import uuid
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class BlockEvidenceLevel(StrEnum):
    LABEL_EXPLICITE = "label_explicite"       # label textuel présent, rattachement certain
    INFERRED_SINGLE_QUESTION = "inferred_single_question"  # aucun label, mais 1 seule Question candidate — sans ambiguïté
    CONTENT_MATCHED = "content_matched"       # aucun label, rattaché par le sens du contenu (LLM) parmi plusieurs Questions
    UNRESOLVED_NO_LABEL = "unresolved_no_label"  # aucun label, intervention prof requise


class TeacherCorrectionBlock(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "teacher_correction_blocks"

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercises.id"), nullable=False
    )
    # nullable : un bloc peut concerner l'exercice entier avant rattachement question
    question_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=True
    )

    # Chemin blob Azure de l'image recadrée sur ce bloc
    image_crop_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Position réelle dans le document source (RawExtractedBlock.page_number/
    # block_order_index, OCR_Extraction_Agent) — nullable (blocs créés avant
    # ce champ). Sans ça, list_by_exercise() ne pouvait trier qu'avec
    # created_at (ordre d'INSERTION pendant le pipeline, jamais garanti égal
    # à l'ordre de LECTURE du document) — constaté en test réel (B5,
    # backlog_bugs_c2pct.md) : le texte de correction reconstruit
    # (_combine_block_text, extraction_verification_service.py) mélangeait
    # des réponses de phases différentes du document sans respecter leur
    # ordre d'origine.
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    content_type: Mapped[ExtractionContentType] = mapped_column(
        PgEnum(ExtractionContentType, name="extraction_content_type"), nullable=False
    )
    # Texte brut OCR du bloc (RawExtractedBlock.prediction_ocr) — nécessaire à
    # Extraction_Verification_Agent pour décomposer/noter une correction TEXTE,
    # qui n'a par nature aucun structured_content (réservé aux blocs STRUCTURE/EQUATION).
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Contenu structuré du bloc (LaTeX, éléments de schéma, etc.)
    structured_content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    evidence_level: Mapped[BlockEvidenceLevel] = mapped_column(
        PgEnum(BlockEvidenceLevel, name="block_evidence_level", values_callable=lambda x: [e.value for e in x]), nullable=False
    )

    # cf. docstring de classe (B11) — confiance OCR combinée, après relecture
    # ciblée éventuelle, telle que calculée par OCR_Extraction_Agent.
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)

    # Rempli par le prof pour les blocs UNRESOLVED_NO_LABEL :
    # décision humaine ("rattaché à Q3", "ignorer ce bloc", etc.)
    professor_resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Justification obligatoire (agent ou prof) : pourquoi ce rattachement ?
    # Pour l'agent : résumé de la heuristique utilisée.
    # Pour le prof : libre, trace la décision HITL.
    justification: Mapped[str] = mapped_column(Text, nullable=False)
