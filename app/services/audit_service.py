"""
Service de journalisation des actions sensibles (audit trail).

Règles métier appliquées :
1. Chaque action significative sur le système (création, modification, suppression
   d'entités sensibles, tentatives d'accès refusées) doit être tracée via
   log_action(). C'est la seule méthode publique : on ne lit pas les logs
   depuis ce service, cela relève d'un endpoint admin dédié.
2. La sévérité est déterminée automatiquement selon le type d'action si elle
   n'est pas fournie explicitement.
3. Le service ne lève jamais d'exception vers l'appelant : un échec de
   journalisation ne doit pas bloquer l'opération métier principale. L'erreur
   est loguée localement (logger Python).
"""
import logging
import uuid
from typing import Protocol

from app.domain.models.system_infrastructure.audit_log import AuditLog, AuditSeverity
from app.domain.repositories.audit_log_repository import AuditLogRepositoryProtocol
from app.domain.repositories.pagination import DEFAULT_PAGE_SIZE, CursorPage
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.system_schemas import AuditLogRead

logger = logging.getLogger(__name__)

# Actions automatiquement classées WARNING ou CRITICAL
_WARNING_ACTIONS = {"delete", "deactivate", "revoke", "suspend"}
_CRITICAL_ACTIONS = {"erasure", "grade_override", "admin_create", "force_resolve"}


def _infer_severity(action: str) -> AuditSeverity:
    action_lower = action.lower()
    if any(kw in action_lower for kw in _CRITICAL_ACTIONS):
        return AuditSeverity.CRITICAL
    if any(kw in action_lower for kw in _WARNING_ACTIONS):
        return AuditSeverity.WARNING
    return AuditSeverity.INFO


class AuditServiceProtocol(Protocol):
    async def log_action(
        self,
        user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        diff: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        severity: AuditSeverity | None = None,
    ) -> AuditLogRead | None: ...
    async def list_logs(
        self,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        entity_type: str | None = None,
        user_id: uuid.UUID | None = None,
        severity: AuditSeverity | None = None,
        action: str | None = None,
    ) -> CursorPage[AuditLogRead]: ...


class AuditService:
    def __init__(
        self,
        audit_log_repo: AuditLogRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
    ) -> None:
        self._repo = audit_log_repo
        self._user_repo = user_repo

    async def log_action(
        self,
        user_id: uuid.UUID,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        diff: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        severity: AuditSeverity | None = None,
    ) -> AuditLogRead | None:
        """
        Trace une action sensible. Ne lève jamais d'exception vers l'appelant :
        un échec de journalisation ne doit pas bloquer l'opération principale.
        """
        effective_severity = severity if severity is not None else _infer_severity(action)
        try:
            audit_log = await self._repo.create(
                user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                diff=diff,
                ip_address=ip_address,
                user_agent=user_agent,
                success=success,
                severity=effective_severity,
            )
            user = await self._user_repo.get_by_id(user_id)
            audit_log.user_full_name = f"{user.first_name} {user.last_name}" if user else "Unknown"
            return AuditLogRead.model_validate(audit_log)
        except Exception as exc:
            logger.error(
                "Échec de journalisation audit [user=%s action=%s entity=%s/%s]: %s",
                user_id, action, entity_type, entity_id, exc,
                exc_info=True,
            )
            return None

    async def list_logs(
        self,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        entity_type: str | None = None,
        user_id: uuid.UUID | None = None,
        severity: AuditSeverity | None = None,
        action: str | None = None,
    ) -> CursorPage[AuditLogRead]:
        page = await self._repo.list_page(
            cursor=cursor,
            limit=limit,
            entity_type=entity_type,
            user_id=user_id,
            severity=severity,
            action=action,
        )

        # Une requête par utilisateur DISTINCT présent sur la page (pas par
        # ligne) : plusieurs entrées consécutives du même acteur (cas
        # fréquent) ne redéclenchent pas de lookup redondant. Les entités
        # visées de type "User" (ex. gestion de compte) partagent le même
        # cache — gap relevé en test réel : "User#ff4e93ce" ne dit rien à un
        # admin, jamais un nom/prénom résolu pour l'entité elle-même, alors
        # que l'acteur l'était déjà.
        unique_user_ids = {log.user_id for log in page.items}
        unique_user_ids.update(log.entity_id for log in page.items if log.entity_type == "User")
        names_by_user_id: dict[uuid.UUID, str] = {}
        for uid in unique_user_ids:
            user = await self._user_repo.get_by_id(uid)
            names_by_user_id[uid] = f"{user.first_name} {user.last_name}" if user else "Unknown"

        items: list[AuditLogRead] = []
        for log in page.items:
            log.user_full_name = names_by_user_id[log.user_id]
            log.entity_label = names_by_user_id.get(log.entity_id) if log.entity_type == "User" else None
            items.append(AuditLogRead.model_validate(log))

        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

