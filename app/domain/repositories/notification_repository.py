"""
Repository Notification — multi-canal avec suivi de livraison.

mark_delivery_failed() incrémente delivery_attempts de façon ATOMIQUE via
une expression SQL (Notification.delivery_attempts + 1), pas un
read-then-write Python — évite une race condition si deux workers
tentent de marquer le même échec en même temps (même classe de problème
que Submission.attempt_number, résolue différemment ici : incrémentation
via expression SQL au lieu d'un verrou pessimiste, suffisant car ce n'est
qu'un compteur informatif, pas une contrainte d'unicité stricte).
"""
import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.notification import (
    Notification,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationPriority,
)


class NotificationRepositoryProtocol(Protocol):
    async def get_by_id(self, notification_id: uuid.UUID) -> Notification | None: ...
    async def list_by_user(
        self, user_id: uuid.UUID, unread_only: bool = False
    ) -> list[Notification]: ...
    async def create(
        self,
        user_id: uuid.UUID,
        content: str,
        type_: str,
        channel: NotificationChannel,
        priority: NotificationPriority,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        action_url: str | None = None,
        expires_at: datetime | None = None,
    ) -> Notification: ...
    async def mark_read(self, notification_id: uuid.UUID) -> Notification | None: ...
    async def mark_delivered(self, notification_id: uuid.UUID) -> Notification | None: ...
    async def mark_delivery_failed(self, notification_id: uuid.UUID) -> Notification | None: ...
    async def list_undelivered_for_retry(
        self, max_attempts: int = 3
    ) -> list[Notification]: ...


class SQLAlchemyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        return await self._session.get(Notification, notification_id)

    async def list_by_user(
        self, user_id: uuid.UUID, unread_only: bool = False
    ) -> list[Notification]:
        query = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            query = query.where(Notification.read_at.is_(None))
        query = query.order_by(Notification.created_at.desc())
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        user_id: uuid.UUID,
        content: str,
        type_: str,
        channel: NotificationChannel,
        priority: NotificationPriority,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        action_url: str | None = None,
        expires_at: datetime | None = None,
    ) -> Notification:
        notification = Notification(
            user_id,
            content,
            type_,  # Pass as positional arg to avoid 'type' keyword conflict
            channel,
            priority,
            related_entity_type,
            related_entity_id,
            action_url,
            expires_at,
            NotificationDeliveryStatus.PENDING,
        )
        self._session.add(notification)
        await self._session.flush()
        return notification

    async def mark_read(self, notification_id: uuid.UUID) -> Notification | None:
        notification = await self.get_by_id(notification_id)
        if notification is None:
            return None
        notification.read_at = datetime.now(timezone.utc)
        await self._session.flush()
        return notification

    async def mark_delivered(self, notification_id: uuid.UUID) -> Notification | None:
        notification = await self.get_by_id(notification_id)
        if notification is None:
            return None
        notification.delivery_status = NotificationDeliveryStatus.DELIVERED
        await self._session.flush()
        return notification

    async def mark_delivery_failed(self, notification_id: uuid.UUID) -> Notification | None:
        """Incrémentation atomique via expression SQL, cf. docstring module."""
        from sqlalchemy import update

        stmt = (
            update(Notification)
            .where(Notification.id == notification_id)
            .values(
                delivery_status=NotificationDeliveryStatus.FAILED,
                delivery_attempts=Notification.delivery_attempts + 1,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()
        return await self.get_by_id(notification_id)

    async def list_undelivered_for_retry(
        self, max_attempts: int = 3
    ) -> list[Notification]:
        """
        Candidates au retry : status FAILED, pas trop de tentatives déjà
        faites, et pas expirées (une notification "examen dans 1h" n'a
        plus aucun sens après le début de l'examen — cf. modèle).
        """
        now = datetime.now(timezone.utc)
        query = select(Notification).where(
            Notification.delivery_status == NotificationDeliveryStatus.FAILED,
            Notification.delivery_attempts < max_attempts,
            or_(Notification.expires_at.is_(None), Notification.expires_at > now),
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())