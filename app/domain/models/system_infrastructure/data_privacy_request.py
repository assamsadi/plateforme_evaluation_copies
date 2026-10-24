"""
DataPrivacyRequest = demande RGPD d'un utilisateur, couvrant les 5 droits
réels (pas juste export/suppression simplifiés) :
- ACCESS_EXPORT   : droit d'accès/portabilité
- ERASURE         : droit à l'effacement
- RECTIFICATION   : droit de rectification
- RESTRICTION     : droit à la limitation du traitement
- OBJECTION       : droit d'opposition

legal_deadline : calculé à la création (created_at + délai légal, ex. 30
jours), pour prouver la conformité et permettre une alerte avant échéance
(via Notification, système à prévoir dans un service dédié).

identity_verified : point de sécurité CRITIQUE — un traitement ne doit
JAMAIS commencer avant vérification que le demandeur est bien le
propriétaire du compte concerné (sinon n'importe qui pourrait demander
l'effacement des données de quelqu'un d'autre).

resolution_detail : une ERASURE ne mène pas toujours à une suppression
totale — l'établissement a souvent une obligation légale de conserver
les notes (retention_reason documente ce conflit), la vraie réponse
étant alors une PSEUDONYMIZATION plutôt qu'un FULL_DELETION.

export_file_expires_at : sécurité — un export de données personnelles
téléchargeable ne doit jamais rester accessible indéfiniment.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum as PgEnum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class PrivacyRequestType(StrEnum):
    ACCESS_EXPORT = "access_export"
    ERASURE = "erasure"
    RECTIFICATION = "rectification"
    RESTRICTION = "restriction"
    OBJECTION = "objection"


class PrivacyRequestStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


class PrivacyResolutionDetail(StrEnum):
    FULL_DELETION = "full_deletion"
    PSEUDONYMIZED = "pseudonymized"          # ex: notes conservées, identité effacée
    PARTIAL_RETENTION_LEGAL = "partial_retention_legal"
    EXPORTED = "exported"
    RECTIFIED = "rectified"
    # Bug corrigé (audit espace admin, migration c0d1e2f3a4b5) : RESTRICTION
    # et OBJECTION (2 des 5 droits réels ci-dessus) n'avaient aucune
    # résolution correspondante — un admin était forcé de choisir un
    # résultat sémantiquement faux (ex. RECTIFIED pour une opposition).
    # Purs enregistrements documentaires, même statut que PARTIAL_
    # RETENTION_LEGAL — aucune donnée modifiée automatiquement (cf.
    # docstring DataPrivacyService.complete_erasure).
    PROCESSING_RESTRICTED = "processing_restricted"
    OBJECTION_UPHELD = "objection_upheld"
    REJECTED = "rejected"


class DataPrivacyRequest(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "data_privacy_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    request_type: Mapped[PrivacyRequestType] = mapped_column(
        PgEnum(PrivacyRequestType, name="privacy_request_type"), nullable=False
    )
    status: Mapped[PrivacyRequestStatus] = mapped_column(
        PgEnum(PrivacyRequestStatus, name="privacy_request_status"),
        nullable=False,
        default=PrivacyRequestStatus.PENDING,
    )
    legal_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Sécurité : aucun traitement ne doit commencer tant que False.
    identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    processed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_detail: Mapped[PrivacyResolutionDetail | None] = mapped_column(
        PgEnum(PrivacyResolutionDetail, name="privacy_resolution_detail"), nullable=True
    )
    retention_or_rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Rempli seulement pour ACCESS_EXPORT
    export_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # blob_path Azure
    export_file_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Note: export_file_url est positionné dynamiquement en mémoire
    # par le service pour DataPrivacyRequestRead, pas comme colonne ORM.

