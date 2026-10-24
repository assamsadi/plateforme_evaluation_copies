"""
CorrectionArbitration = décision du professeur sur un cas AMBIGU remonté
par Contestation_Verification_Agent — seul cas où le prof est sollicité,
les verdicts PLAUSIBLE/IMPLAUSIBLE sont auto-résolus en amont sans jamais
créer de ligne ici.

status : la ligne est créée en PENDING dès que l'agent tranche AMBIGU
(teacher_arbitration_node) — teacher_professor_id/verdict/comment restent
NULL jusqu'à la résolution. Ce n'est qu'à la résolution qu'ils sont posés
et que status passe à RESOLVED. created_at (TimestampMixin) sert de point
d'ancrage pour le futur job de rappel/escalade (§10 du doc de référence
agent) — pas géré ici, seulement le point d'ancrage nécessaire.

claimed_correction : ce que le professeur a effectivement retenu comme
vérité — jamais un choix binaire limité aux deux versions existantes, il
peut saisir sa propre version (§9bis).

comment réutilisé par la boucle d'apprentissage few-shot (§6) : chaque
arbitrage indexé en base vectorielle pour calibrer les seuils au fil du
temps.
"""
import uuid
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class ArbitrationVerdict(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ArbitrationStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"


class CorrectionArbitration(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "correction_arbitrations"

    extraction_correction_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("extraction_corrections.id"), nullable=False
    )
    status: Mapped[ArbitrationStatus] = mapped_column(
        PgEnum(ArbitrationStatus, name="arbitration_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=ArbitrationStatus.PENDING,
    )
    # Nullable : posés seulement à la résolution, pas à la création PENDING.
    teacher_professor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=True
    )
    verdict: Mapped[ArbitrationVerdict | None] = mapped_column(
        PgEnum(ArbitrationVerdict, name="arbitration_verdict", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    claimed_correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Note: teacher_full_name est positionné dynamiquement en mémoire
    # par le service pour CorrectionArbitrationRead, pas comme colonne ORM.
