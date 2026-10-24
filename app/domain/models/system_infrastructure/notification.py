"""
Notification = notification persistée envoyée à un utilisateur, avec
suivi complet de livraison (distinct de "lue" : une notification peut
être envoyée mais jamais lue, ou même échouer à l'envoi).

related_entity_type/id : référence polymorphe (même pattern
qu'AgentDecisionLog) — permet de rediriger l'utilisateur directement
vers l'objet concerné (submission, incident, appeal...) au clic.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum as PgEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class NotificationChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"


class NotificationPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class NotificationDeliveryStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class Notification(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: "grade_published"

    channel: Mapped[NotificationChannel] = mapped_column(
        PgEnum(NotificationChannel, name="notification_channel"), nullable=False
    )
    priority: Mapped[NotificationPriority] = mapped_column(
        PgEnum(NotificationPriority, name="notification_priority"),
        nullable=False,
        default=NotificationPriority.NORMAL,
    )
    delivery_status: Mapped[NotificationDeliveryStatus] = mapped_column(
        PgEnum(NotificationDeliveryStatus, name="notification_delivery_status"),
        nullable=False,
        default=NotificationDeliveryStatus.PENDING,
    )
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    related_entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    action_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)