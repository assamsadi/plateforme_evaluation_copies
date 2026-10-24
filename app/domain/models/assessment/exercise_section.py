"""
ExerciseSection = niveau intermédiaire entre Exercise et Question.

Permet d'organiser les questions d'un examen ou devoir en parties/sections
(ex: "Exercice 1 : Analyse", "Partie B : Probabilités").

Créé automatiquement par le Document_Structuring_Agent lors de la
structuration d'un sujet scanné/déposé.
"""
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.domain.models.assessment.exercise import Exercise
    from app.domain.models.assessment.question import Question


class ExerciseSection(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "exercise_sections"
    __table_args__ = (
        UniqueConstraint("exercise_id", "order", name="uq_exercise_section_exercise_order"),
    )

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercises.id", ondelete="CASCADE"), nullable=False
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)

    exercise: Mapped["Exercise"] = relationship(back_populates="sections")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="section", order_by="Question.order"
    )
