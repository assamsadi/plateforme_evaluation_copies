"""
GradeAppeal = contestation d'une note par l'étudiant, distincte d'un
SubmissionIncident (qui gère absence/incident technique, pas un désaccord
sur la notation elle-même). Peut cibler une Evaluation précise (une seule
question) ou la Submission entière selon le cas.

extraction_correction_id : ancrage visuel (§4.2 CHAABI, "Visual
Grounding") — l'étudiant peut pointer vers la zone précise en litige.

original_score / revised_score : snapshot avant/après, pour l'audit et
la défense en cas de litige plus large (cohérent avec AuditLog).
"""
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, Enum as PgEnum, ForeignKey, Integer, Numeric, Sequence, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class AppealStatus(StrEnum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"


class AppealResolution(StrEnum):
    GRADE_UPHELD = "grade_upheld"
    GRADE_REVISED = "grade_revised"
    PARTIAL_REVISION = "partial_revision"


class GradeAppeal(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "grade_appeals"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    evaluation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("evaluations.id"), nullable=True
    )
    extraction_correction_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("extraction_corrections.id"), nullable=True
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False
    )
    # Identifiant lisible séquentiel (audit "ids manquants") — cf. commentaire
    # Admin.admin_number pour le principe.
    appeal_number: Mapped[int] = mapped_column(
        Integer, Sequence("appeal_number_seq"), unique=True, nullable=False
    )

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    original_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    status: Mapped[AppealStatus] = mapped_column(
        PgEnum(AppealStatus, name="appeal_status"),
        nullable=False,
        default=AppealStatus.PENDING,
    )
    resolution: Mapped[AppealResolution | None] = mapped_column(
        PgEnum(AppealResolution, name="appeal_resolution"), nullable=True
    )
    revised_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)

    resolved_by_professor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=True
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Escalade optionnelle si l'étudiant n'est pas satisfait de la
    # décision du prof (ex. responsable de filière tranche en dernier
    # recours).
    escalated_to_admin_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("admins.id"), nullable=True
    )

    # Vérification croisée (§4.2 CHAABI) : un second agent d'évaluation,
    # indépendant de celui qui a noté initialement, réévalue la réponse
    # SANS connaître la première note — donne au prof une deuxième
    # opinion chiffrée avant de trancher. Volontairement PAS de champ
    # "preuve fournie par l'étudiant" : contournerait l'ancrage visuel
    # (bounding_box) et ouvrirait une brèche de fraude a posteriori.
    ai_reevaluation_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    ai_reevaluation_justification: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Même structure que Evaluation.classic_criteria_observed (liste de
    # {"criterion": ..., "score": ..., "justification": ...}) — la
    # réévaluation reproduit la même granularité que la notation initiale,
    # pour rester réellement comparable critère par critère. Ne porte
    # JAMAIS sur les compétences C2PCT (qui n'affectent pas la note,
    # aucune raison de les réévaluer dans une contestation de note).
    ai_reevaluation_criteria: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Note: student_full_name est positionné dynamiquement en mémoire
    # par le service pour GradeAppealRead, pas comme colonne ORM.

