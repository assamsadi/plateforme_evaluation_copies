"""
Repository Evaluation — racine d'agrégat couvrant Evaluation +
EvaluationCriteria.

get_total_score_for_submission() utilise SUM() natif PostgreSQL — évite
de charger toutes les Evaluation d'une soumission juste pour les
additionner en Python (potentiellement consulté des centaines de
fois/jour pour l'affichage des bulletins). Agnostique de la méthode de
calcul du score par question — Phase 4/4 (Pedagogical_Evaluation_Agent)
n'a nécessité AUCUNE modification ici.

create_with_criteria() est transactionnelle stricte : soit l'Evaluation
ET tous ses EvaluationCriteria sont créés ensemble, soit rien n'est créé
(pas d'état partiellement noté en base si une erreur survient au milieu).

classic_criteria_observed (exactitude/cohérence/complétude/justification)
reste un paramètre, mais DÉPASSÉ par Phase 4/4 : les 4 critères classiques
n'influencent PLUS le score (méta-donnée informative, héritage) — c'est
désormais la répartition du barème entre compétences C2PCT réellement
mobilisées (criteria_data avec competency_code/subquestion_detail) qui le
détermine.

c2pct_observed RETIRÉ (câblage réparation StudentCompetencyProfile) —
portait l'ancienne granularité, jamais alimenté par le chemin actif.

criteria_data accepte désormais deux familles de dicts (Phase 4/4, cf.
docstring EvaluationCriteria) : classique (criterion_id renseigné,
competency_code absent) ou compétence (competency_code + subquestion_detail
renseignés, criterion_id absent/None) — jamais les deux à la fois sur un
même dict, invariant APPLICATIF vérifié ici (pas une contrainte SQL).

list_criteria_for_submission() (câblage Competency_Assessment_Agent,
Partie 1/2) : lit les lignes EvaluationCriteria "compétence" (competency_
code non NULL) de toutes les Evaluation d'une soumission — source de
CompetencyAssessmentService.assess_submission pour le Niveau 2
(subquestion_detail.subquestions[] porte les succès triviaux, absents de
DecisionEntry, nécessaires pour dériver `strengths`). Aucune relation
SQLAlchemy Evaluation.criteria n'existe (vérifié) — jointure directe.
"""
import uuid
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.evaluation_criteria import EvaluationCriteria
from app.domain.models.assessment.submission import Submission


class EvaluationRepositoryProtocol(Protocol):
    async def get_by_id(self, evaluation_id: uuid.UUID) -> Evaluation | None: ...
    async def get_by_submission_and_question(
        self, submission_id: uuid.UUID, question_id: uuid.UUID
    ) -> Evaluation | None: ...
    async def list_by_submission(self, submission_id: uuid.UUID) -> list[Evaluation]: ...
    async def list_by_exercise(self, exercise_id: uuid.UUID) -> list[Evaluation]: ...
    async def list_by_student(self, student_id: uuid.UUID) -> list[Evaluation]: ...
    async def list_criteria_for_submission(self, submission_id: uuid.UUID) -> list[EvaluationCriteria]: ...
    async def list_criteria_by_evaluation_ids(
        self, evaluation_ids: list[uuid.UUID]
    ) -> list[EvaluationCriteria]: ...
    async def get_total_score_for_submission(self, submission_id: uuid.UUID) -> Decimal: ...
    async def get_average_score_platform(self) -> Decimal | None: ...
    async def create_with_criteria(
        self,
        submission_id: uuid.UUID,
        question_id: uuid.UUID,
        score: Decimal,
        classic_criteria_observed: list[dict],
        criteria_data: list[dict],
        copy_report_detail: dict | None = None,
    ) -> Evaluation: ...


class SQLAlchemyEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, evaluation_id: uuid.UUID) -> Evaluation | None:
        return await self._session.get(Evaluation, evaluation_id)

    async def get_by_submission_and_question(
        self, submission_id: uuid.UUID, question_id: uuid.UUID
    ) -> Evaluation | None:
        result = await self._session.execute(
            select(Evaluation).where(
                Evaluation.submission_id == submission_id,
                Evaluation.question_id == question_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_submission(self, submission_id: uuid.UUID) -> list[Evaluation]:
        result = await self._session.execute(
            select(Evaluation)
            .where(Evaluation.submission_id == submission_id)
            .order_by(Evaluation.question_id)
        )
        return list(result.scalars().all())

    async def list_by_exercise(self, exercise_id: uuid.UUID) -> list[Evaluation]:
        """
        Câblage StatisticsService.get_exercise_stats — Evaluation ne porte
        pas exercise_id directement (seulement submission_id/question_id,
        cf. docstring module), jointure via Submission nécessaire.
        """
        result = await self._session.execute(
            select(Evaluation)
            .join(Submission, Evaluation.submission_id == Submission.id)
            .where(Submission.exercise_id == exercise_id)
        )
        return list(result.scalars().all())

    async def list_by_student(self, student_id: uuid.UUID) -> list[Evaluation]:
        """Câblage StatisticsService.get_student_stats — même raisonnement que list_by_exercise ci-dessus."""
        result = await self._session.execute(
            select(Evaluation)
            .join(Submission, Evaluation.submission_id == Submission.id)
            .where(Submission.student_id == student_id)
        )
        return list(result.scalars().all())

    async def get_average_score_platform(self) -> Decimal | None:
        """
        Moyenne des notes TOTALES par copie (somme des Evaluation.score de
        chaque soumission, puis AVG SQL natif — jamais chargé en Python).
        None si aucune Evaluation n'existe (distinct de 0 — jamais un taux
        de réussite nul deviné sur une absence totale de données).
        """
        totals = (
            select(func.sum(Evaluation.score).label("total"))
            .group_by(Evaluation.submission_id)
            .subquery()
        )
        stmt = select(func.avg(totals.c.total))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_criteria_for_submission(self, submission_id: uuid.UUID) -> list[EvaluationCriteria]:
        """
        Lignes "compétence" uniquement (competency_code non NULL) — jamais
        les lignes classiques (criterion_id), non pertinentes pour
        Competency_Assessment_Agent.
        """
        result = await self._session.execute(
            select(EvaluationCriteria)
            .join(Evaluation, EvaluationCriteria.evaluation_id == Evaluation.id)
            .where(
                Evaluation.submission_id == submission_id,
                EvaluationCriteria.competency_code.is_not(None),
            )
        )
        return list(result.scalars().all())

    async def list_criteria_by_evaluation_ids(
        self, evaluation_ids: list[uuid.UUID]
    ) -> list[EvaluationCriteria]:
        """
        Gap fermé (espace étudiant, trouvé en testant un vrai relevé de
        notes de bout en bout) : contrairement à list_criteria_for_submission
        (lignes "compétence" uniquement, réservée à CompetencyAssessment
        Service), cette méthode renvoie TOUTES les lignes (classiques ET
        compétence) — nécessaire pour EvaluationService.list_evaluations,
        qui doit afficher le détail complet d'une évaluation, jamais un
        sous-ensemble filtré par famille.
        """
        if not evaluation_ids:
            return []
        result = await self._session.execute(
            select(EvaluationCriteria).where(EvaluationCriteria.evaluation_id.in_(evaluation_ids))
        )
        return list(result.scalars().all())

    async def get_total_score_for_submission(self, submission_id: uuid.UUID) -> Decimal:
        stmt = select(func.coalesce(func.sum(Evaluation.score), 0)).where(
            Evaluation.submission_id == submission_id
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def create_with_criteria(
        self,
        submission_id: uuid.UUID,
        question_id: uuid.UUID,
        score: Decimal,
        classic_criteria_observed: list[dict],
        criteria_data: list[dict],
        copy_report_detail: dict | None = None,
    ) -> Evaluation:
        """
        `criteria_data` : liste de dicts déjà validés côté service — deux
        familles possibles (Phase 4/4, cf. docstring module), ex. :
            classique : {"bareme_id": ..., "criterion_id": "...",
                "points_awarded": 2.0, "comment": None}
            compétence : {"bareme_id": ..., "competency_code": "data_and_
                planning", "points_awarded": 8.57, "subquestion_detail": {...}}
        `classic_criteria_observed` : ex. [{"criterion": "exactitude",
            "score": 80, "justification": "..."}, ...] — DÉPASSÉ par Phase
        4/4, méta-donnée informative, n'influence plus score.
        `copy_report_detail` : câblage copy_report — QuestionReport.to_dict()
        (Pedagogical_Evaluation_Agent), None si non fourni (appelants
        antérieurs à ce câblage, ou pas de rapport disponible).
        """
        evaluation = Evaluation(
            submission_id=submission_id,
            question_id=question_id,
            score=score,
            classic_criteria_observed=classic_criteria_observed,
            copy_report_detail=copy_report_detail,
        )
        self._session.add(evaluation)
        await self._session.flush()  # attribue evaluation.id pour les FK enfants

        for criterion in criteria_data:
            self._session.add(
                EvaluationCriteria(
                    evaluation_id=evaluation.id,
                    bareme_id=criterion["bareme_id"],
                    criterion_id=criterion.get("criterion_id"),
                    points_awarded=criterion["points_awarded"],
                    comment=criterion.get("comment"),
                    competency_code=criterion.get("competency_code"),
                    subquestion_detail=criterion.get("subquestion_detail"),
                )
            )

        await self._session.flush()
        return evaluation