"""
Service de gestion de la persistance et du suivi des notifications.

Règles métier appliquées :
1. Ce service gère uniquement la création et le cycle de vie de la notification
   en base de données. L'envoi réseau (email, push) est géré de manière asynchrone
   (ex: via Celery).
2. Permet de lister les notifications ayant échoué pour réessayer l'envoi (retry).
3. Met à jour le statut de distribution (delivered ou failed) en fonction du résultat
   de la tâche asynchrone.
"""
import uuid
from datetime import datetime
from typing import Protocol

from app.core.exceptions import NotificationNotFoundError
from app.domain.models.system_infrastructure.notification import (
    Notification,
    NotificationChannel,
    NotificationPriority,
)
from app.domain.repositories.notification_repository import NotificationRepositoryProtocol


class NotificationServiceProtocol(Protocol):
    async def notify(
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

    async def mark_as_read(self, notification_id: uuid.UUID) -> Notification: ...

    async def list_for_retry(self, max_attempts: int = 3) -> list[Notification]: ...

    async def report_delivery_result(
        self, notification_id: uuid.UUID, success: bool
    ) -> Notification: ...


class NotificationService:
    def __init__(self, notification_repo: NotificationRepositoryProtocol) -> None:
        self._notification_repo = notification_repo

    async def notify(
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
        return await self._notification_repo.create(
            user_id=user_id,
            content=content,
            type_=type_,
            channel=channel,
            priority=priority,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            action_url=action_url,
            expires_at=expires_at,
        )

    async def mark_as_read(self, notification_id: uuid.UUID) -> Notification:
        notification = await self._notification_repo.mark_read(notification_id)
        if not notification:
            raise NotificationNotFoundError(notification_id)
        return notification

    async def list_for_retry(self, max_attempts: int = 3) -> list[Notification]:
        return await self._notification_repo.list_undelivered_for_retry(max_attempts)

    async def report_delivery_result(
        self, notification_id: uuid.UUID, success: bool
    ) -> Notification:
        if success:
            notification = await self._notification_repo.mark_delivered(notification_id)
        else:
            notification = await self._notification_repo.mark_delivery_failed(notification_id)
            
        if not notification:
            raise NotificationNotFoundError(notification_id)
            
        return notification
