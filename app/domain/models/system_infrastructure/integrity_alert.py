"""
IntegrityAlert = alerte d'intégrité académique sur un étudiant. Répond
au mécanisme explicite du document CHAABI (§4.2) : "Un taux anormalement
élevé de contestations rejetées peut déclencher une alerte de
supervision" — étendu à d'autres sources de détection (similarité
anormale entre copies, patterns suspects), pas seulement les rejets
d'incidents/contestations.

evidence (JSONB) : structure flexible car chaque trigger_type produit des
preuves différentes, ex. :
  HIGH_REJECTION_RATE  -> {"rejection_rate": 0.75, "total": 4, "rejected": 3}
  SUSPECTED_PLAGIARISM -> {"similarity_score": 0.92, "compared_submission_id": "..."}
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum as PgEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class IntegrityTriggerType(StrEnum):
    HIGH_REJECTION_RATE = "high_rejection_rate"
    SUSPECTED_PLAGIARISM = "suspected_plagiarism"
    SUSPICIOUS_PATTERN = "suspicious_pattern"
    MANUAL_FLAG = "manual_flag"
    # Plus de 50% des blocs d'UNE soumission contestés (§8 du doc
    # Contestation_Verification_Agent) — distinct de HIGH_REJECTION_RATE,
    # qui porte sur le taux de rejet d'incidents d'UN étudiant agrégé sur
    # plusieurs soumissions, pas sur le volume de contestation d'une copie.
    SYSTEMATIC_CONTESTATION = "systematic_contestation"


class IntegrityAlertStatus(StrEnum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"  # faux positif


class IntegrityActionTaken(StrEnum):
    WARNING_ISSUED = "warning_issued"
    GRADE_INVALIDATED = "grade_invalidated"
    ESCALATED = "escalated"
    NO_ACTION = "no_action"


class IntegrityAlert(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "integrity_alerts"

    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False
    )
    trigger_type: Mapped[IntegrityTriggerType] = mapped_column(
        PgEnum(IntegrityTriggerType, name="integrity_trigger_type"), nullable=False
    )
    auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    reason: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[IntegrityAlertStatus] = mapped_column(
        PgEnum(IntegrityAlertStatus, name="integrity_alert_status"),
        nullable=False,
        default=IntegrityAlertStatus.PENDING,
    )
    action_taken: Mapped[IntegrityActionTaken | None] = mapped_column(
        PgEnum(IntegrityActionTaken, name="integrity_action_taken"), nullable=True
    )

    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Note: student_full_name est positionné dynamiquement en mémoire
    # par le service pour IntegrityAlertRead, pas comme colonne ORM.

