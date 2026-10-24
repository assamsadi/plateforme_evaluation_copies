"""
Service de gestion des alertes d'intégrité académique.

Règles métier appliquées :
1. Les alertes peuvent être générées automatiquement (par ArbitrationService
   lors d'un taux de rejet anormal) ou manuellement par un admin.
2. Une alerte manuelle peut être levée par un professeur ou admin sur tout
   déclencheur : plagiat suspecté, pattern suspect, signalement direct.
3. Seul un administrateur peut statuer sur une alerte (review) et enregistrer
   l'action prise.
4. Une alerte DISMISSED est un faux positif — aucune action réelle prise.
"""
import uuid
from typing import Protocol

from app.core.exceptions import AlertNotFoundError
from app.domain.models.system_infrastructure.integrity_alert import (
    IntegrityActionTaken,
    IntegrityAlert,
    IntegrityAlertStatus,
    IntegrityTriggerType,
)
from app.domain.repositories.integrity_alert_repository import (
    IntegrityAlertRepositoryProtocol,
)
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.system_schemas import IntegrityAlertRead


class IntegrityServiceProtocol(Protocol):
    async def flag_student(
        self,
        student_id: uuid.UUID,
        trigger_type: IntegrityTriggerType,
        reason: str,
        evidence: dict | None,
        auto_generated: bool,
    ) -> IntegrityAlertRead: ...

    async def review_alert(
        self,
        alert_id: uuid.UUID,
        reviewed_by_user_id: uuid.UUID,
        status: IntegrityAlertStatus,
        action_taken: IntegrityActionTaken | None,
        review_notes: str | None,
    ) -> IntegrityAlertRead: ...

    async def list_pending(self) -> list[IntegrityAlertRead]: ...

    async def get_student_history(self, student_id: uuid.UUID) -> list[IntegrityAlertRead]: ...


class IntegrityService:
    def __init__(
        self,
        integrity_repo: IntegrityAlertRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
    ) -> None:
        self._integrity_repo = integrity_repo
        self._user_repo = user_repo

    async def _to_alert_read(self, alert: IntegrityAlert) -> IntegrityAlertRead:
        student = await self._user_repo.get_by_id(alert.student_id)
        alert.student_full_name = f"{student.first_name} {student.last_name}" if student else "Unknown"
        return IntegrityAlertRead.model_validate(alert)

    async def flag_student(
        self,
        student_id: uuid.UUID,
        trigger_type: IntegrityTriggerType,
        reason: str,
        evidence: dict | None = None,
        auto_generated: bool = False,
    ) -> IntegrityAlertRead:
        """
        Bug corrigé (audit espace admin, en câblant enfin un appelant réel
        pour cette méthode) : evidence=None (défaut déclaré ici) atteignait
        IntegrityAlertRepository.create() tel quel, qui l'assigne
        directement à IntegrityAlert.evidence — colonne JSONB nullable=
        False. Un appel avec evidence omis (le cas normal d'un signalement
        manuel, cf. docstring module "signalement direct") aurait toujours
        levé une IntegrityError en base, jamais détecté faute d'appelant.
        """
        alert = await self._integrity_repo.create(
            student_id=student_id,
            trigger_type=trigger_type,
            reason=reason,
            auto_generated=auto_generated,
            evidence=evidence or {},
        )
        return await self._to_alert_read(alert)

    async def review_alert(
        self,
        alert_id: uuid.UUID,
        reviewed_by_user_id: uuid.UUID,
        status: IntegrityAlertStatus,
        action_taken: IntegrityActionTaken | None,
        review_notes: str | None,
    ) -> IntegrityAlertRead:
        alert = await self._integrity_repo.review(
            alert_id=alert_id,
            reviewed_by_user_id=reviewed_by_user_id,
            status=status,
            action_taken=action_taken,
            review_notes=review_notes,
        )
        if not alert:
            raise AlertNotFoundError(alert_id)
        return await self._to_alert_read(alert)

    async def list_pending(self) -> list[IntegrityAlertRead]:
        alerts = await self._integrity_repo.list_pending()
        result: list[IntegrityAlertRead] = []
        for alert in alerts:
            result.append(await self._to_alert_read(alert))
        return result

    async def get_student_history(self, student_id: uuid.UUID) -> list[IntegrityAlertRead]:
        alerts = await self._integrity_repo.list_by_student(student_id)
        result: list[IntegrityAlertRead] = []
        for alert in alerts:
            result.append(await self._to_alert_read(alert))
        return result

