"""
Service d'orchestration des contestations de notes (Grade Appeals).

Règles métier appliquées :
1. Une contestation peut porter sur une question spécifique (evaluation_id) ou
   sur l'ensemble de la copie.
2. Un deuxième agent indépendant peut évaluer la copie (ai_reevaluation) pour 
   fournir un avis purement informatif.
3. Seul le professeur associé à l'exercice peut trancher définitivement (resolve)
   la contestation. Toute modification de note (revised_score) ne s'applique 
   que par cette décision humaine.
"""
import uuid
from decimal import Decimal
from typing import Protocol

from app.core.exceptions import AppealNotFoundError, NotFoundError
from app.domain.models.assessment.grade_appeal import AppealResolution, GradeAppeal
from app.domain.repositories.evaluation_repository import EvaluationRepositoryProtocol
from app.domain.repositories.grade_appeal_repository import GradeAppealRepositoryProtocol
from app.domain.repositories.pagination import DEFAULT_PAGE_SIZE, CursorPage
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.arbitration_schemas import GradeAppealRead


class GradeAppealServiceProtocol(Protocol):
    async def file_appeal(
        self,
        submission_id: uuid.UUID,
        student_id: uuid.UUID,
        reason: str,
        evaluation_id: uuid.UUID | None = None,
        extraction_correction_id: uuid.UUID | None = None,
    ) -> GradeAppealRead: ...

    async def record_ai_reevaluation(
        self,
        appeal_id: uuid.UUID,
        score: Decimal,
        justification: str,
        criteria: list[dict],
    ) -> GradeAppealRead: ...

    async def resolve_appeal(
        self,
        appeal_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolution: AppealResolution,
        review_comment: str | None,
        revised_score: Decimal | None = None,
    ) -> GradeAppealRead: ...

    async def escalate_to_admin(
        self, appeal_id: uuid.UUID, admin_id: uuid.UUID
    ) -> GradeAppealRead: ...

    async def list_pending_for_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[GradeAppealRead]: ...

    async def list_by_submission_for_student(
        self, submission_id: uuid.UUID, requesting_student_id: uuid.UUID,
    ) -> list[GradeAppealRead]: ...


class GradeAppealService:
    def __init__(
        self,
        appeal_repo: GradeAppealRepositoryProtocol,
        evaluation_repo: EvaluationRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
    ) -> None:
        self._appeal_repo = appeal_repo
        self._evaluation_repo = evaluation_repo
        self._user_repo = user_repo

    async def _to_appeal_read(self, appeal: GradeAppeal) -> GradeAppealRead:
        """Enrichit un GradeAppeal avec student_full_name/resolved_by_professor_name et convertit en GradeAppealRead."""
        student = await self._user_repo.get_by_id(appeal.student_id)
        appeal.student_full_name = (
            f"{student.first_name} {student.last_name}" if student else "Unknown"
        )
        if appeal.resolved_by_professor_id:
            professor = await self._user_repo.get_by_id(appeal.resolved_by_professor_id)
            appeal.resolved_by_professor_name = (
                f"{professor.first_name} {professor.last_name}" if professor else "Unknown"
            )
        else:
            appeal.resolved_by_professor_name = None
        return GradeAppealRead.model_validate(appeal)

    async def file_appeal(
        self,
        submission_id: uuid.UUID,
        student_id: uuid.UUID,
        reason: str,
        evaluation_id: uuid.UUID | None = None,
        extraction_correction_id: uuid.UUID | None = None,
    ) -> GradeAppealRead:
        appeal = await self._appeal_repo.create(
            submission_id=submission_id,
            student_id=student_id,
            reason=reason,
            evaluation_id=evaluation_id,
            extraction_correction_id=extraction_correction_id,
        )
        return await self._to_appeal_read(appeal)

    async def record_ai_reevaluation(
        self,
        appeal_id: uuid.UUID,
        score: Decimal,
        justification: str,
        criteria: list[dict],
    ) -> GradeAppealRead:
        appeal = await self._appeal_repo.record_ai_reevaluation(
            appeal_id=appeal_id,
            score=score,
            justification=justification,
            criteria=criteria,
        )
        if not appeal:
            raise AppealNotFoundError(appeal_id)
        return await self._to_appeal_read(appeal)

    async def resolve_appeal(
        self,
        appeal_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolution: AppealResolution,
        review_comment: str | None,
        revised_score: Decimal | None = None,
    ) -> GradeAppealRead:
        appeal = await self._appeal_repo.resolve(
            appeal_id=appeal_id,
            requesting_professor_id=requesting_professor_id,
            resolution=resolution,
            review_comment=review_comment,
            revised_score=revised_score,
        )
        if not appeal:
            raise AppealNotFoundError(appeal_id)
        return await self._to_appeal_read(appeal)

    async def escalate_to_admin(
        self, appeal_id: uuid.UUID, admin_id: uuid.UUID
    ) -> GradeAppealRead:
        appeal = await self._appeal_repo.escalate(
            appeal_id=appeal_id,
            admin_id=admin_id,
        )
        if not appeal:
            raise AppealNotFoundError(appeal_id)
        return await self._to_appeal_read(appeal)

    async def list_pending_for_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[GradeAppealRead]:
        page = await self._appeal_repo.list_pending_for_professor(professor_id, cursor=cursor, limit=limit)

        # Une requête par étudiant DISTINCT sur la page — même pattern que
        # AuditService.list_logs / CourseService (dénormalisation groupée).
        unique_student_ids = {appeal.student_id for appeal in page.items}
        names_by_student_id: dict[uuid.UUID, str] = {}
        for student_id in unique_student_ids:
            student = await self._user_repo.get_by_id(student_id)
            names_by_student_id[student_id] = (
                f"{student.first_name} {student.last_name}" if student else "Unknown"
            )

        items: list[GradeAppealRead] = []
        for appeal in page.items:
            appeal.student_full_name = names_by_student_id[appeal.student_id]
            # Toujours en attente ici (list_pending_for_professor) : jamais
            # encore résolu, donc pas de professeur à résoudre le nom — mais
            # l'attribut doit être posé pour satisfaire GradeAppealRead
            # (champ requis, potentiellement None).
            appeal.resolved_by_professor_name = None
            items.append(GradeAppealRead.model_validate(appeal))
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def list_by_submission_for_student(
        self, submission_id: uuid.UUID, requesting_student_id: uuid.UUID,
    ) -> list[GradeAppealRead]:
        """
        Gap fermé (espace étudiant) : un étudiant pouvait déposer une
        contestation (POST /appeals) mais n'avait ensuite AUCUN moyen de
        revoir son statut/sa résolution — aucun endpoint de lecture
        n'existait côté étudiant. Filtre en mémoire sur student_id plutôt
        qu'une requête dédiée : GradeAppealRepository.list_by_submission
        existe déjà (utilisé ailleurs), et le volume par soumission est
        toujours trivial (quelques lignes au plus) — jamais un souci de
        performance contrairement à une pagination pleine table. Filtrer
        par student_id ici (plutôt que de vérifier la propriété de la
        Submission elle-même) suffit à garantir qu'aucune contestation
        d'un AUTRE étudiant ne fuite jamais, quel que soit le submission_id
        fourni.
        """
        appeals = await self._appeal_repo.list_by_submission(submission_id)
        own_appeals = [a for a in appeals if a.student_id == requesting_student_id]
        return [await self._to_appeal_read(a) for a in own_appeals]

