"""
Repository SubmissionIncident — implémente les 5 systèmes documentés
dans le modèle (submission_incident.py) :
1. detect_cluster_candidates() : fenêtre de temps SQL directe
2. list_cluster_members() : lecture des membres d'un cluster (racine + enfants) —
   ArbitrationService.resolve_cluster résout ENSUITE chaque membre via
   resolve_single() (jamais un bulk UPDATE ici, cf. son docstring pour le
   bug corrigé : un bulk UPDATE ne peut ni créer de nouvelle tentative pour
   RETRY_GRANTED, ni poser extended_deadline par incident).
3. get_rejection_ratio() : agrégation SQL directe (anti-fraude §4.2 CHAABI)
4. has_pending_incident() : anti-doublon (EXISTS)
5. list_pending_near_deadline() : pour l'escalade (Notification, ailleurs)

Renforcements de sécurité (défense en profondeur) :
- Validation de bornes sur TOUS les paramètres numériques d'entrée, même
  si déjà validés par un schema Pydantic en amont — ne jamais faire
  confiance à une seule couche de validation.
- requesting_professor_id exigé explicitement sur les méthodes de
  résolution : force l'appelant à fournir le professeur demandeur, et le
  repository VÉRIFIE que l'incident (via son Exercise) appartient bien à
  ce professeur avant toute modification — un service qui oublierait
  cette vérification ne pourrait pas silencieusement modifier un incident
  hors périmètre (RLS applicative, à défaut de RLS PostgreSQL native).
- MAX_CLUSTER_SIZE reste le plafond dur (vérifié par le service avant de
  boucler sur resolve_single) : un bug créant accidentellement des
  milliers d'incidents liés au même parent ne peut pas déclencher une
  résolution de masse incontrôlée.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.domain.models.assessment.submission_incident import (
    IncidentCategory,
    IncidentResolution,
    IncidentStatus,
    SubmissionIncident,
)

# Bornes de sécurité, validées à l'entrée de chaque méthode concernée.
MIN_WINDOW_MINUTES, MAX_WINDOW_MINUTES = 1, 24 * 60
MIN_CLUSTER_THRESHOLD, MAX_CLUSTER_THRESHOLD = 2, 100
MIN_DEADLINE_HOURS, MAX_DEADLINE_HOURS = 1, 24 * 30
MAX_CLUSTER_SIZE = 200  # plafond dur, un cluster réel dépasse rarement une salle d'examen


class UnauthorizedIncidentAccessError(ForbiddenError):
    """
    Levée si un professeur tente de résoudre un incident dont l'exercice
    ne lui appartient pas (garde-fou applicatif — voir docstring module).

    Bug corrigé (audit arbitrage) : héritait de Exception nue, jamais
    mappée par les handlers globaux de main.py (ForbiddenError -> 403) —
    aurait fait planter en 500 non géré la première fois que ce garde-fou
    se déclenchait réellement, cf. même correctif déjà appliqué à
    UnauthorizedAppealAccessError.
    """
    def __init__(self, incident_id: uuid.UUID, professor_id: uuid.UUID) -> None:
        super().__init__(
            f"Le professeur {professor_id} n'est pas autorisé à résoudre "
            f"l'incident {incident_id} (exercice hors périmètre)"
        )


class SubmissionIncidentRepositoryProtocol(Protocol):
    async def get_by_id(self, incident_id: uuid.UUID) -> SubmissionIncident | None: ...
    async def has_pending_incident(
        self, student_id: uuid.UUID, exercise_id: uuid.UUID
    ) -> bool: ...
    async def create(
        self,
        exercise_id: uuid.UUID,
        student_id: uuid.UUID,
        reported_by_user_id: uuid.UUID,
        category: IncidentCategory,
        reason: str,
        incident_occurred_at: datetime | None,
        attachment_path: str | None,
        parent_incident_id: uuid.UUID | None = None,
    ) -> SubmissionIncident: ...
    async def detect_cluster_candidates(
        self, exercise_id: uuid.UUID, window_minutes: int = 15, min_count: int = 3
    ) -> list[uuid.UUID]: ...
    async def list_cluster_members(
        self, parent_incident_id: uuid.UUID
    ) -> list[SubmissionIncident]: ...
    async def resolve_single(
        self,
        incident_id: uuid.UUID,
        resolution: IncidentResolution,
        resolution_comment: str | None,
        resolved_by_professor_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        extended_deadline: datetime | None = None,
        new_submission_id: uuid.UUID | None = None,
    ) -> SubmissionIncident | None: ...
    async def get_rejection_ratio(self, student_id: uuid.UUID) -> Decimal: ...
    async def list_pending_near_deadline(
        self, deadline_threshold_hours: int = 24
    ) -> list[SubmissionIncident]: ...
    async def list_pending_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[SubmissionIncident]: ...
    async def set_parent(
        self, incident_id: uuid.UUID, parent_id: uuid.UUID
    ) -> SubmissionIncident | None: ...


class SQLAlchemySubmissionIncidentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, incident_id: uuid.UUID) -> SubmissionIncident | None:
        return await self._session.get(SubmissionIncident, incident_id)

    async def has_pending_incident(
        self, student_id: uuid.UUID, exercise_id: uuid.UUID
    ) -> bool:
        """Anti-doublon (système 4) : EXISTS pur, appelé avant chaque création."""
        from sqlalchemy import exists

        stmt = select(
            exists().where(
                SubmissionIncident.student_id == student_id,
                SubmissionIncident.exercise_id == exercise_id,
                SubmissionIncident.status == IncidentStatus.PENDING,
            )
        )
        result = await self._session.execute(stmt)
        return bool(result.scalar())

    async def create(
        self,
        exercise_id: uuid.UUID,
        student_id: uuid.UUID,
        reported_by_user_id: uuid.UUID,
        category: IncidentCategory,
        reason: str,
        incident_occurred_at: datetime | None,
        attachment_path: str | None,
        parent_incident_id: uuid.UUID | None = None,
    ) -> SubmissionIncident:
        incident = SubmissionIncident(
            exercise_id=exercise_id,
            student_id=student_id,
            reported_by_user_id=reported_by_user_id,
            category=category,
            reason=reason,
            incident_occurred_at=incident_occurred_at,
            attachment_path=attachment_path,
            parent_incident_id=parent_incident_id,
            status=IncidentStatus.PENDING,
        )
        self._session.add(incident)
        await self._session.flush()
        return incident

    async def detect_cluster_candidates(
        self, exercise_id: uuid.UUID, window_minutes: int = 15, min_count: int = 3
    ) -> list[uuid.UUID]:
        """
        Système 1 : fenêtre de temps SQL directe. Retourne les IDs des
        incidents TECHNICAL récents sur cet exercice s'ils dépassent
        min_count, dans les window_minutes dernières minutes — candidats
        à regrouper sous un parent_incident_id commun (fait par le
        service, qui choisit lequel devient la racine).
        """
        if not (MIN_WINDOW_MINUTES <= window_minutes <= MAX_WINDOW_MINUTES):
            raise ValueError(
                f"window_minutes doit être entre {MIN_WINDOW_MINUTES} et {MAX_WINDOW_MINUTES}"
            )
        if not (MIN_CLUSTER_THRESHOLD <= min_count <= MAX_CLUSTER_THRESHOLD):
            raise ValueError(
                f"min_count doit être entre {MIN_CLUSTER_THRESHOLD} et {MAX_CLUSTER_THRESHOLD}"
            )

        threshold = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        count_stmt = (
            select(func.count())
            .select_from(SubmissionIncident)
            .where(
                SubmissionIncident.exercise_id == exercise_id,
                SubmissionIncident.category == IncidentCategory.TECHNICAL,
                SubmissionIncident.created_at >= threshold,
                SubmissionIncident.parent_incident_id.is_(None),  # pas déjà groupés
            )
        )
        count_result = await self._session.execute(count_stmt)
        if count_result.scalar_one() < min_count:
            return []

        ids_stmt = select(SubmissionIncident.id).where(
            SubmissionIncident.exercise_id == exercise_id,
            SubmissionIncident.category == IncidentCategory.TECHNICAL,
            SubmissionIncident.created_at >= threshold,
            SubmissionIncident.parent_incident_id.is_(None),
        )
        ids_result = await self._session.execute(ids_stmt)
        return list(ids_result.scalars().all())

    async def list_cluster_members(
        self, parent_incident_id: uuid.UUID
    ) -> list[SubmissionIncident]:
        """
        Système 2 : membres d'un cluster — l'incident racine LUI-MÊME ET
        tous ses enfants (parent_incident_id == parent_incident_id). Liste
        vide si parent_incident_id n'existe pas du tout (l'appelant décide
        s'il s'agit d'une erreur, cf. ArbitrationService.resolve_cluster).
        Ordonné par created_at pour un traitement déterministe.
        """
        from sqlalchemy import or_

        cluster_membership = or_(
            SubmissionIncident.id == parent_incident_id,
            SubmissionIncident.parent_incident_id == parent_incident_id,
        )
        stmt = select(SubmissionIncident).where(cluster_membership).order_by(SubmissionIncident.created_at)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def resolve_single(
        self,
        incident_id: uuid.UUID,
        resolution: IncidentResolution,
        resolution_comment: str | None,
        resolved_by_professor_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        extended_deadline: datetime | None = None,
        new_submission_id: uuid.UUID | None = None,
    ) -> SubmissionIncident | None:
        from app.domain.models.assessment.exercise import Exercise

        incident = await self.get_by_id(incident_id)
        if incident is None:
            return None

        exercise = await self._session.get(Exercise, incident.exercise_id)
        if exercise is None or exercise.created_by_professor_id != requesting_professor_id:
            raise UnauthorizedIncidentAccessError(incident_id, requesting_professor_id)

        incident.status = IncidentStatus.RESOLVED
        incident.resolution = resolution
        incident.resolution_comment = resolution_comment
        incident.resolved_by_professor_id = resolved_by_professor_id
        incident.resolved_at = datetime.now(timezone.utc)
        if extended_deadline is not None:
            incident.extended_deadline = extended_deadline
        if new_submission_id is not None:
            incident.new_submission_id = new_submission_id
        await self._session.flush()
        return incident

    async def get_rejection_ratio(self, student_id: uuid.UUID) -> Decimal:
        """
        Système 3 (anti-fraude, §4.2 CHAABI) : ratio calculé ENTIÈREMENT
        en SQL via une expression CASE conditionnelle dans un SUM,
        divisée par un COUNT total — aucune ligne rapatriée, juste un
        Decimal. Retourne 0 si l'étudiant n'a aucun incident résolu
        (évite une division par zéro également gérée en SQL).
        """
        rejected_count = func.sum(
            case((SubmissionIncident.resolution == IncidentResolution.REJECTED, 1), else_=0)
        )
        total_count = func.count().filter(SubmissionIncident.status == IncidentStatus.RESOLVED)

        stmt = select(
            func.coalesce(rejected_count, 0), func.coalesce(total_count, 0)
        ).where(SubmissionIncident.student_id == student_id)

        result = await self._session.execute(stmt)
        rejected, total = result.one()
        if total == 0:
            return Decimal(0)
        return Decimal(rejected) / Decimal(total)

    async def list_pending_near_deadline(
        self, deadline_threshold_hours: int = 24
    ) -> list[SubmissionIncident]:
        """
        Système 5 (escalade) : incidents PENDING dont l'exercice lié
        approche de sa deadline — candidats à une Notification urgente
        vers le prof (logique de notification elle-même dans le service,
        pas ici — ce repository ne fait que sélectionner les candidats).

        Nécessite un JOIN vers Exercise pour la deadline ; import différé
        pour éviter une dépendance circulaire entre modules de modèles.
        """
        if not (MIN_DEADLINE_HOURS <= deadline_threshold_hours <= MAX_DEADLINE_HOURS):
            raise ValueError(
                f"deadline_threshold_hours doit être entre {MIN_DEADLINE_HOURS} "
                f"et {MAX_DEADLINE_HOURS}"
            )

        from app.domain.models.assessment.exercise import Exercise

        threshold = datetime.now(timezone.utc) + timedelta(hours=deadline_threshold_hours)
        stmt = (
            select(SubmissionIncident)
            .join(Exercise, SubmissionIncident.exercise_id == Exercise.id)
            .where(
                SubmissionIncident.status == IncidentStatus.PENDING,
                Exercise.deadline.is_not(None),
                Exercise.deadline <= threshold,
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[SubmissionIncident]:
        """
        Gap trouvé lors de l'audit arbitrage : aucune file de découverte
        n'existait pour les incidents PENDING d'un professeur —
        /incidents/{id}/resolve exigeait déjà l'ID, jamais fourni par
        aucune liste (list_pending_near_deadline existe mais est filtrée
        par deadline pour l'escalade, pas un usage général de découverte).
        """
        from app.domain.models.assessment.exercise import Exercise

        stmt = (
            select(SubmissionIncident)
            .join(Exercise, SubmissionIncident.exercise_id == Exercise.id)
            .where(
                Exercise.created_by_professor_id == professor_id,
                SubmissionIncident.status == IncidentStatus.PENDING,
            )
            .order_by(SubmissionIncident.created_at)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def set_parent(
        self, incident_id: uuid.UUID, parent_id: uuid.UUID
    ) -> SubmissionIncident | None:
        incident = await self.get_by_id(incident_id)
        if incident is None:
            return None
        incident.parent_incident_id = parent_id
        await self._session.flush()
        return incident