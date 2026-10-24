"""
Repository GradeAppeal.

Sécurité appliquée dès la conception (cohérent avec les renforcements de
submission_incident_repository.py) :
- requesting_professor_id exigé sur resolve() : vérifie que la Submission
  contestée appartient bien à un Exercise du professeur demandeur, avant
  toute modification.
- original_score n'est JAMAIS un paramètre de create() modifiable par
  l'appelant service à sa guise : il est calculé ICI, dans le repository,
  depuis l'Evaluation actuelle en base au moment de la création — jamais
  transmis depuis une couche externe qui pourrait le falsifier (cf.
  arbitration_schemas.GradeAppealCreate, qui ne l'expose pas non plus).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError
from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.grade_appeal import AppealResolution, AppealStatus, GradeAppeal
from app.domain.models.assessment.submission import Submission
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class UnauthorizedAppealAccessError(ForbiddenError):
    def __init__(self, appeal_id: uuid.UUID, professor_id: uuid.UUID) -> None:
        super().__init__(
            f"Le professeur {professor_id} n'est pas autorisé à statuer sur "
            f"la contestation {appeal_id} (exercice hors périmètre)"
        )


class GradeAppealRepositoryProtocol(Protocol):
    async def get_by_id(self, appeal_id: uuid.UUID) -> GradeAppeal | None: ...
    async def list_by_submission(self, submission_id: uuid.UUID) -> list[GradeAppeal]: ...
    async def list_pending_for_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[GradeAppeal]: ...
    async def create(
        self,
        submission_id: uuid.UUID,
        student_id: uuid.UUID,
        reason: str,
        evaluation_id: uuid.UUID | None = None,
        extraction_correction_id: uuid.UUID | None = None,
    ) -> GradeAppeal: ...
    async def resolve(
        self,
        appeal_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolution: AppealResolution,
        review_comment: str | None,
        revised_score: Decimal | None = None,
    ) -> GradeAppeal | None: ...
    async def record_ai_reevaluation(
        self,
        appeal_id: uuid.UUID,
        score: Decimal,
        justification: str,
        criteria: list[dict],
    ) -> GradeAppeal | None: ...
    async def escalate(
        self, appeal_id: uuid.UUID, admin_id: uuid.UUID
    ) -> GradeAppeal | None: ...


class SQLAlchemyGradeAppealRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, appeal_id: uuid.UUID) -> GradeAppeal | None:
        return await self._session.get(GradeAppeal, appeal_id)

    async def list_by_submission(self, submission_id: uuid.UUID) -> list[GradeAppeal]:
        result = await self._session.execute(
            select(GradeAppeal).where(GradeAppeal.submission_id == submission_id)
        )
        return list(result.scalars().all())

    async def list_pending_for_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[GradeAppeal]:
        """
        Contestations PENDING ou UNDER_REVIEW rattachées à un Exercise créé
        par ce professeur — sans ceci, aucune file de découverte n'existe :
        un professeur ne peut agir que sur un appeal dont il connaît déjà
        l'ID (cf. list_by_professor sur CourseRepository, même lacune).
        """
        from app.domain.models.assessment.exercise import Exercise

        query = (
            select(GradeAppeal)
            .join(Submission, GradeAppeal.submission_id == Submission.id)
            .join(Exercise, Submission.exercise_id == Exercise.id)
            .where(
                Exercise.created_by_professor_id == professor_id,
                GradeAppeal.status.in_([AppealStatus.PENDING, AppealStatus.UNDER_REVIEW]),
            )
            .order_by(GradeAppeal.created_at, GradeAppeal.id)
        )
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(GradeAppeal.created_at, GradeAppeal.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda a: (a.created_at, a.id))

    async def create(
        self,
        submission_id: uuid.UUID,
        student_id: uuid.UUID,
        reason: str,
        evaluation_id: uuid.UUID | None = None,
        extraction_correction_id: uuid.UUID | None = None,
    ) -> GradeAppeal:
        """
        original_score dérivé ICI depuis l'Evaluation actuelle (jamais
        fourni par l'appelant) — voir docstring module.

        Gap fermé (trouvé en construisant la lecture étudiante des
        contestations) : le docstring annonçait déjà "si evaluation_id
        n'est pas fourni, le service devra utiliser le score total de la
        Submission" — jamais implémenté, original_score restait à 0 pour
        toute contestation portant sur la copie entière (jamais une
        question précise), affichant à tort au professeur une note de
        départ nulle. Calculé ICI (jamais transmis par le service, cf.
        docstring module — l'invariant "original_score non falsifiable
        depuis l'extérieur" reste intact) via la même agrégation SQL que
        EvaluationRepository.get_total_score_for_submission (COALESCE
        SUM, jamais None sur une soumission sans Evaluation).
        """
        original_score = Decimal(0)
        if evaluation_id is not None:
            evaluation = await self._session.get(Evaluation, evaluation_id)
            if evaluation is not None:
                original_score = evaluation.score
        else:
            result = await self._session.execute(
                select(func.coalesce(func.sum(Evaluation.score), 0))
                .where(Evaluation.submission_id == submission_id)
            )
            original_score = result.scalar_one()

        appeal = GradeAppeal(
            submission_id=submission_id,
            student_id=student_id,
            evaluation_id=evaluation_id,
            extraction_correction_id=extraction_correction_id,
            reason=reason,
            original_score=original_score,
        )
        self._session.add(appeal)
        await self._session.flush()
        return appeal

    async def resolve(
        self,
        appeal_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolution: AppealResolution,
        review_comment: str | None,
        revised_score: Decimal | None = None,
    ) -> GradeAppeal | None:
        from app.domain.models.assessment.exercise import Exercise

        appeal = await self.get_by_id(appeal_id)
        if appeal is None:
            return None

        submission = await self._session.get(Submission, appeal.submission_id)
        if submission is None:
            return None
        exercise = await self._session.get(Exercise, submission.exercise_id)
        if exercise is None or exercise.created_by_professor_id != requesting_professor_id:
            raise UnauthorizedAppealAccessError(appeal_id, requesting_professor_id)

        appeal.status = "resolved"
        appeal.resolution = resolution
        appeal.review_comment = review_comment
        appeal.resolved_by_professor_id = requesting_professor_id
        appeal.resolved_at = datetime.now(timezone.utc)
        if revised_score is not None:
            appeal.revised_score = revised_score

            # Si la note est révisée et liée à une Evaluation précise,
            # applique le changement directement (même logique de
            # transaction cross-agrégat assumée que dans
            # correction_arbitration_repository.py, pour l'atomicité).
            if appeal.evaluation_id is not None:
                evaluation = await self._session.get(Evaluation, appeal.evaluation_id)
                if evaluation is not None:
                    evaluation.score = revised_score

        await self._session.flush()
        return appeal

    async def record_ai_reevaluation(
        self,
        appeal_id: uuid.UUID,
        score: Decimal,
        justification: str,
        criteria: list[dict],
    ) -> GradeAppeal | None:
        """
        Enregistre le résultat du second agent indépendant (§4.2 CHAABI)
        AVANT que le prof ne tranche — purement informatif, ne modifie
        jamais la note réelle (seul resolve() le fait, sur décision
        humaine explicite).

        `criteria` : même structure que Evaluation.classic_criteria_observed
        (ex. [{"criterion": "exactitude", "score": 80, "justification":
        "..."}]) — reproduit la même granularité que la notation
        initiale, pour rester comparable critère par critère. Porte
        UNIQUEMENT sur les 4 critères classiques, jamais sur le C2PCT
        (qui n'affecte pas la note, aucune raison de le réévaluer ici).
        """
        appeal = await self.get_by_id(appeal_id)
        if appeal is None:
            return None
        appeal.ai_reevaluation_score = score
        appeal.ai_reevaluation_justification = justification
        appeal.ai_reevaluation_criteria = criteria
        await self._session.flush()
        return appeal

    async def escalate(
        self, appeal_id: uuid.UUID, admin_id: uuid.UUID
    ) -> GradeAppeal | None:
        appeal = await self.get_by_id(appeal_id)
        if appeal is None:
            return None
        appeal.escalated_to_admin_id = admin_id
        await self._session.flush()
        return appeal
