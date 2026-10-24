"""
SolutionVariant = une méthode de résolution valide pour une Question.
La correction originale du professeur est aussi une variante
(is_reference=True), les autres sont générées par l'agent de variantes
puis validées par le prof avant utilisation en comparaison (§2.3 CHAABI).

reasoning_summary est dénormalisé/mis en cache : évite de charger tous
les ReasoningStep liés juste pour afficher un aperçu en liste (ex. le
prof comparant plusieurs variantes côte à côte).
"""
import uuid
from enum import StrEnum

from sqlalchemy import Boolean, Enum as PgEnum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class VariantDifficulty(StrEnum):
    FACILE = "facile"
    INTERMEDIAIRE = "intermediaire"
    AVANCE = "avance"


class VariantStatus(StrEnum):
    PENDING_VALIDATION = "pending_validation"
    APPROVED = "approved"
    REJECTED = "rejected"


class VariantSource(StrEnum):
    TEACHER_ORIGINAL = "teacher_original"   # la correction déposée par le prof
    TEACHER_MANUAL = "teacher_manual"       # variante ajoutée manuellement par le prof
    AI_GENERATED = "ai_generated"           # générée par l'agent de variantes


class SolutionVariant(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "solution_variants"

    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Même format que ExtractionCorrection.structured_output : permet à
    # l'agent de comparaison de confronter structure contre structure
    # (ex. LaTeX contre LaTeX) plutôt que texte brut contre structure.
    structured_content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[VariantSource] = mapped_column(
        PgEnum(VariantSource, name="variant_source"), nullable=False
    )
    difficulty_level: Mapped[VariantDifficulty] = mapped_column(
        PgEnum(VariantDifficulty, name="variant_difficulty"), nullable=False
    )
    status: Mapped[VariantStatus] = mapped_column(
        PgEnum(VariantStatus, name="variant_status"),
        nullable=False,
        default=VariantStatus.PENDING_VALIDATION,
    )
    validated_by_professor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=True
    )
    # Rempli par le prof à la validation — essentiel en cas de REJECTED
    # (pourquoi cette variante ne convient pas), réutilisé par la boucle
    # d'apprentissage few-shot (§6 : indexé en base vectorielle pour
    # améliorer les générations futures de l'agent de variantes).
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Versionnement & Auditabilité (Reasoning_Graph_Agent)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("solution_variants.id"), nullable=True
    )