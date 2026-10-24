"""
Submission = la copie d'un étudiant pour un Exercise donné. L'id de cette
table EST le thread_id LangGraph (§7 du résumé d'architecture) : garantit
l'idempotence, un thread_id rejoué ne duplique jamais une soumission.

attempt_number : en mode PUBLISHED_AS_EXAM/HOMEWORK, une seule tentative
valide ; en mode ARCHIVED_IN_LIBRARY, plusieurs tentatives autorisées
(§5). La contrainte d'unicité empêche seulement les doublons EXACTS
(même numéro de tentative répété), pas la logique métier "une seule
tentative en examen" — celle-ci est appliquée par submission_service.py.
"""
import uuid
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Integer, Sequence, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class SubmissionStatus(StrEnum):
    PENDING_OCR = "pending_ocr"
    PENDING_STUDENT_VERIFICATION = "pending_student_verification"
    # Au moins un bloc contesté a reçu un verdict AMBIGU — toute la
    # soumission est en pause (pas seulement le bloc) tant que la
    # CorrectionArbitration correspondante n'est pas résolue (§2 étape 6
    # du doc Contestation_Verification_Agent).
    PENDING_ARBITRATION = "pending_arbitration"
    PENDING_EVALUATION = "pending_evaluation"
    EVALUATED = "evaluated"
    ABSENT = "absent"  # créé automatiquement par le job de deadline (§4, gestion d'absence)


class Submission(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint(
            "exercise_id", "student_id", "attempt_number",
            name="uq_submission_exercise_student_attempt",
        ),
    )

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercises.id"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Identifiant lisible séquentiel (audit "ids manquants") — cf. commentaire
    # Admin.admin_number pour le principe. Distinct d'attempt_number (relatif
    # à un (exercise_id, student_id) précis, pas une identification globale).
    submission_number: Mapped[int] = mapped_column(
        Integer, Sequence("submission_number_seq"), unique=True, nullable=False
    )
    status: Mapped[SubmissionStatus] = mapped_column(
        PgEnum(SubmissionStatus, name="submission_status"),
        nullable=False,
        default=SubmissionStatus.PENDING_OCR,
    )
    document_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Note: exercise_title et student_full_name sont positionnés dynamiquement en mémoire
    # par le service pour SubmissionRead, pas comme colonnes ORM.

