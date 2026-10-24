"""
SubmissionIncident = signalement d'un incident empêchant une soumission
normale (scan en panne EN SALLE juste après l'examen, wifi coupé, etc.)
— distinct d'une absence non justifiée. Arbitré par le professeur.

parent_incident_id : regroupe plusieurs signalements individuels causés
par le MÊME incident racine (ex. coupure wifi de toute la salle touchant
15 étudiants) — le prof résout l'incident racine une fois, la résolution
peut être propagée aux incidents enfants (logique dans arbitration_service.py).

Si resolution == RETRY_GRANTED, le système crée automatiquement une
nouvelle tentative sur le MÊME Exercise (§ discussion : rattrapage
automatique, pas d'Exercise séparé) — new_submission_id trace ce lien.

--- Systèmes prévus dans arbitration_service.py (pas ici, modèle pur) ---
1. Détection auto de cluster : 3+ incidents TECHNICAL sur le même
   exercise_id en <15min -> regroupés sous un parent_incident_id commun.
2. Résolution en masse : resolve_incident_cluster(parent_incident_id, ...)
   applique une décision à tous les incidents enfants d'un coup.
3. Détection de fraude (§4.2 CHAABI) : ratio d'incidents REJECTED par
   étudiant au-delà d'un seuil -> déclenche une IntegrityAlert.
4. Anti-doublon : refuse un nouvel incident PENDING si un autre existe
   déjà pour le même (student_id, exercise_id).
5. Escalade : Notification automatique au prof si un incident reste
   PENDING trop près de la deadline finale des notes.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum as PgEnum, ForeignKey, Integer, Sequence, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class IncidentCategory(StrEnum):
    TECHNICAL = "technical"  # wifi, scanner, matériel
    HEALTH = "health"        # malaise, urgence médicale
    OTHER = "other"


class IncidentStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"


class IncidentResolution(StrEnum):
    JUSTIFIED_ABSENCE = "justified_absence"
    RETRY_GRANTED = "retry_granted"
    DEADLINE_EXTENDED = "deadline_extended"
    REJECTED = "rejected"  # le prof ne retient pas l'incident, absence reste non justifiée


class SubmissionIncident(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "submission_incidents"

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercises.id"), nullable=False
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False
    )
    # Identifiant lisible séquentiel (audit "ids manquants") — cf. commentaire
    # Admin.admin_number pour le principe.
    incident_number: Mapped[int] = mapped_column(
        Integer, Sequence("incident_number_seq"), unique=True, nullable=False
    )
    reported_by_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    parent_incident_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submission_incidents.id"), nullable=True
    )

    category: Mapped[IncidentCategory] = mapped_column(
        PgEnum(IncidentCategory, name="incident_category"), nullable=False
    )
    incident_occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # blob_path Azure

    status: Mapped[IncidentStatus] = mapped_column(
        PgEnum(IncidentStatus, name="incident_status"),
        nullable=False,
        default=IncidentStatus.PENDING,
    )
    resolution: Mapped[IncidentResolution | None] = mapped_column(
        PgEnum(IncidentResolution, name="incident_resolution"), nullable=True
    )
    resolved_by_professor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=True
    )
    resolution_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    extended_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # rempli seulement si resolution == DEADLINE_EXTENDED
    new_submission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True
    )  # rempli seulement si resolution == RETRY_GRANTED
    # Note: student_full_name est positionné dynamiquement en mémoire
    # par le service pour SubmissionIncidentRead, pas comme colonne ORM.

