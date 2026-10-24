"""
Bareme = le barème d'une Question (points + critères), saisi par le
professeur EN AMONT, en même temps que sa correction (§3 du résumé
d'architecture) — la génération de variantes est ensuite contrainte
par ce barème, pas l'inverse.

Un seul Bareme par Question (contrainte unique sur question_id).

validation_status (Phase 6, Extraction_Verification_Agent) : CONFIRMED pour
un barème détaillé fourni tel quel par le prof (Cas 1) ou saisi
manuellement (create_with_questions). PENDING_REVIEW pour une répartition
proposée par l'agent (Cas 2, BaremeResult.status="PENDING_REVIEW") — jamais
appliquée automatiquement, ne doit jamais être consommée comme une vérité
acquise tant que le prof ne l'a pas confirmée (cf. la ClarificationRequest
BLOCKING correspondante, persistée séparément en ReasoningClarificationRequest).
"""
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as PgEnum, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.domain.models.assessment.question import Question


class BaremeValidationStatus(StrEnum):
    CONFIRMED = "confirmed"
    PENDING_REVIEW = "pending_review"


class Bareme(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "baremes"

    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), unique=True, nullable=False
    )
    points: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    # Structure libre, chaque critère DOIT avoir un id (UUID string) pour
    # être référencé par EvaluationCriteria.criterion_id :
    # ex: [{"id": "a1b2...", "label": "Calcul de l'aire", "points": 2.0}, ...]
    criteria: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    validation_status: Mapped[BaremeValidationStatus] = mapped_column(
        # values_callable : la migration crée le type Postgres avec des
        # valeurs minuscules ('confirmed', 'pending_review'), pas les noms
        # membres Python — sans ça, asyncpg reçoit "PENDING_REVIEW" (le nom)
        # et rejette une valeur inexistante dans l'enum SQL.
        PgEnum(
            BaremeValidationStatus, name="bareme_validation_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=BaremeValidationStatus.CONFIRMED,
    )

    question: Mapped["Question"] = relationship(back_populates="bareme")