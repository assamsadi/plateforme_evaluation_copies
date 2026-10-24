"""
Feedback = conteneur pour le retour pédagogique d'UNE question d'UNE
soumission. Le contenu réel vit dans FeedbackVersion (fichier suivant) —
permet un historique complet des itérations (feedback socratique évolutif,
§2.6 CHAABI), plutôt qu'un simple champ content écrasé à chaque édition.
"""
import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class Feedback(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "feedbacks"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "question_id", name="uq_feedback_submission_question"
        ),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=False
    )