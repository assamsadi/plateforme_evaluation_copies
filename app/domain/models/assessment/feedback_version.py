"""
FeedbackVersion = une itération du feedback d'une Question (§2.6 CHAABI :
"le professeur garde la main pour affiner les conseils personnalisés
générés par l'IA"). Chaque édition crée une NOUVELLE version plutôt que
d'écraser la précédente — historique complet consultable.
"""
import uuid
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class FeedbackAuthorType(StrEnum):
    AI = "ai"
    TEACHER = "teacher"


class FeedbackVersion(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "feedback_versions"
    __table_args__ = (
        UniqueConstraint(
            "feedback_id", "version_number", name="uq_feedback_version_number"
        ),
    )

    feedback_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("feedbacks.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author_type: Mapped[FeedbackAuthorType] = mapped_column(
        PgEnum(FeedbackAuthorType, name="feedback_author_type"), nullable=False
    )
    # NULL si author_type == AI (généré automatiquement, pas d'utilisateur humain)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Note: author_full_name est positionné dynamiquement en mémoire
    # par le service pour FeedbackVersionRead, pas comme colonne ORM.

