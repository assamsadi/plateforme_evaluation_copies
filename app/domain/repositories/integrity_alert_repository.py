"""
Repository IntegrityAlert.

Garde-fou d'autorisation ADAPTÉ à ce cas précis (différent du pattern
"appartenance à un Exercise" utilisé pour SubmissionIncident/GradeAppeal,
car IntegrityAlert n'a pas de propriétaire naturel — elle concerne un
étudiant, déclenchée automatiquement ou signalée par n'importe quel
prof/admin) : le vrai risque ici est un CONFLIT D'INTÉRÊT — un étudiant
ne doit JAMAIS pouvoir réviser/rejeter sa propre alerte d'intégrité.

create_from_rejection_ratio() illustre la consommation cohérente de
submission_incident_repository.get_rejection_ratio() (§4.2 CHAABI) —
le service appelle ce ratio, décide du seuil, puis crée l'alerte ici.
"""
import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.integrity_alert import (
    IntegrityActionTaken,
    IntegrityAlert,
    IntegrityAlertStatus,
    IntegrityTriggerType,
)


class SelfReviewConflictError(Exception):
    """L'étudiant concerné par l'alerte ne peut pas la réviser lui-même."""
    def __init__(self, alert_id: uuid.UUID) -> None:
        super().__init__(
            f"L'étudiant concerné par l'alerte {alert_id} ne peut pas la réviser lui-même "
            f"(conflit d'intérêt)"
        )


class IntegrityAlertRepositoryProtocol(Protocol):
    async def get_by_id(self, alert_id: uuid.UUID) -> IntegrityAlert | None: ...
    async def list_by_student(self, student_id: uuid.UUID) -> list[IntegrityAlert]: ...
    async def list_pending(self) -> list[IntegrityAlert]: ...
    async def create(
        self,
        student_id: uuid.UUID,
        trigger_type: IntegrityTriggerType,
        auto_generated: bool,
        evidence: dict,
        reason: str,
    ) -> IntegrityAlert: ...
    async def review(
        self,
        alert_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        status: IntegrityAlertStatus,
        action_taken: IntegrityActionTaken | None,
        review_notes: str | None,
    ) -> IntegrityAlert | None: ...


class SQLAlchemyIntegrityAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, alert_id: uuid.UUID) -> IntegrityAlert | None:
        return await self._session.get(IntegrityAlert, alert_id)

    async def list_by_student(self, student_id: uuid.UUID) -> list[IntegrityAlert]:
        result = await self._session.execute(
            select(IntegrityAlert)
            .where(IntegrityAlert.student_id == student_id)
            .order_by(IntegrityAlert.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_pending(self) -> list[IntegrityAlert]:
        result = await self._session.execute(
            select(IntegrityAlert)
            .where(IntegrityAlert.status == IntegrityAlertStatus.PENDING)
            .order_by(IntegrityAlert.created_at)
        )
        return list(result.scalars().all())

    async def create(
        self,
        student_id: uuid.UUID,
        trigger_type: IntegrityTriggerType,
        auto_generated: bool,
        evidence: dict,
        reason: str,
    ) -> IntegrityAlert:
        alert = IntegrityAlert(
            student_id=student_id,
            trigger_type=trigger_type,
            auto_generated=auto_generated,
            evidence=evidence,
            reason=reason,
            status=IntegrityAlertStatus.PENDING,
        )
        self._session.add(alert)
        await self._session.flush()
        return alert

    async def review(
        self,
        alert_id: uuid.UUID,
        requesting_user_id: uuid.UUID,
        status: IntegrityAlertStatus,
        action_taken: IntegrityActionTaken | None,
        review_notes: str | None,
    ) -> IntegrityAlert | None:
        alert = await self.get_by_id(alert_id)
        if alert is None:
            return None

        if alert.student_id == requesting_user_id:
            raise SelfReviewConflictError(alert_id)

        alert.status = status
        alert.action_taken = action_taken
        alert.review_notes = review_notes
        alert.reviewed_by_user_id = requesting_user_id
        alert.reviewed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return alert