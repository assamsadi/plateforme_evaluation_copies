"""
Repository RecommendedExercise — puise dans la Library du module de
l'étudiant (§5, Fonction 8).

Câblage Recommendation_Agent — student_id est désormais une colonne
directe (plus de JOIN via Submission, cf. docstring modèle) :
list_active_by_student() filtre RÉELLEMENT status=ACTIVE désormais (avant
ce chantier, le nom mentait — aucun filtre n'existait, accumulation
infinie). list_active_by_student_module_competency()/supersede() portent
le dédoublonnage : RecommendationService doit superséder les anciennes
ACTIVE d'un (student, module, competency) avant d'en créer de nouvelles,
jamais les laisser s'empiler.
"""
import uuid
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.recommended_exercise import (
    RecommendationCategory,
    RecommendationStatus,
    RecommendedExercise,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode


class RecommendedExerciseRepositoryProtocol(Protocol):
    async def get_by_id(self, recommendation_id: uuid.UUID) -> RecommendedExercise | None: ...
    async def list_by_submission(
        self, submission_id: uuid.UUID
    ) -> list[RecommendedExercise]: ...
    async def list_active_by_student(
        self, student_id: uuid.UUID
    ) -> list[RecommendedExercise]: ...
    async def list_active_by_student_and_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[RecommendedExercise]: ...
    async def list_active_by_student_module_competency(
        self, student_id: uuid.UUID, module_id: uuid.UUID, competency_code: C2PCTSkillCode,
    ) -> list[RecommendedExercise]: ...
    async def supersede(self, recommendation_ids: list[uuid.UUID]) -> None: ...
    async def create(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        competency_code: C2PCTSkillCode,
        category: RecommendationCategory,
        exercise_id: uuid.UUID,
        reason: str,
        relevance_score: Decimal,
        submission_id: uuid.UUID | None = None,
    ) -> RecommendedExercise: ...
    async def link_to_notebook(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        submission_id: uuid.UUID | None,
        student_notebook_id: uuid.UUID,
    ) -> None: ...


class SQLAlchemyRecommendedExerciseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, recommendation_id: uuid.UUID) -> RecommendedExercise | None:
        return await self._session.get(RecommendedExercise, recommendation_id)

    async def list_by_submission(
        self, submission_id: uuid.UUID
    ) -> list[RecommendedExercise]:
        result = await self._session.execute(
            select(RecommendedExercise)
            .where(RecommendedExercise.submission_id == submission_id)
            .order_by(RecommendedExercise.relevance_score.desc())
        )
        return list(result.scalars().all())

    async def list_active_by_student(
        self, student_id: uuid.UUID
    ) -> list[RecommendedExercise]:
        """
        Tableau de bord étudiant — UNIQUEMENT les recommandations ACTIVE
        (les SUPERSEDED restent en base pour l'historique/l'audit CHAABI
        §6.1, mais ne sont plus affichées). student_id direct, plus de JOIN
        via Submission (cf. docstring modèle).
        """
        result = await self._session.execute(
            select(RecommendedExercise)
            .where(
                RecommendedExercise.student_id == student_id,
                RecommendedExercise.status == RecommendationStatus.ACTIVE,
            )
            .order_by(RecommendedExercise.relevance_score.desc())
        )
        return list(result.scalars().all())

    async def list_active_by_student_and_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[RecommendedExercise]:
        """
        Vue professeur (câblage Recommendation_Agent, clôture — traçabilité
        professeur) — scoping par module OBLIGATOIRE : contrairement à
        list_active_by_student (vue self étudiant, tous modules confondus,
        aucun contrôle d'accès module par module n'a de sens pour son propre
        profil), l'autorisation professeur (exists_professor_exercise_in_
        module) n'a de sens que pour UN module précis, jamais "tous les
        modules d'un étudiant" (même principe que get_report_as_professor).
        """
        result = await self._session.execute(
            select(RecommendedExercise)
            .where(
                RecommendedExercise.student_id == student_id,
                RecommendedExercise.module_id == module_id,
                RecommendedExercise.status == RecommendationStatus.ACTIVE,
            )
            .order_by(RecommendedExercise.relevance_score.desc())
        )
        return list(result.scalars().all())

    async def list_active_by_student_module_competency(
        self, student_id: uuid.UUID, module_id: uuid.UUID, competency_code: C2PCTSkillCode,
    ) -> list[RecommendedExercise]:
        """Lu par RecommendationService AVANT de créer de nouvelles lignes — dédoublonnage (cf. docstring module)."""
        result = await self._session.execute(
            select(RecommendedExercise).where(
                RecommendedExercise.student_id == student_id,
                RecommendedExercise.module_id == module_id,
                RecommendedExercise.competency_code == competency_code,
                RecommendedExercise.status == RecommendationStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    async def supersede(self, recommendation_ids: list[uuid.UUID]) -> None:
        """No-op sur liste vide — jamais un UPDATE sans WHERE réel qui toucherait toute la table."""
        if not recommendation_ids:
            return
        await self._session.execute(
            update(RecommendedExercise)
            .where(RecommendedExercise.id.in_(recommendation_ids))
            .values(status=RecommendationStatus.SUPERSEDED)
        )
        await self._session.flush()

    async def create(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        competency_code: C2PCTSkillCode,
        category: RecommendationCategory,
        exercise_id: uuid.UUID,
        reason: str,
        relevance_score: Decimal,
        submission_id: uuid.UUID | None = None,
    ) -> RecommendedExercise:
        recommendation = RecommendedExercise(
            student_id=student_id,
            module_id=module_id,
            competency_code=competency_code,
            category=category,
            status=RecommendationStatus.ACTIVE,
            submission_id=submission_id,
            exercise_id=exercise_id,
            reason=reason,
            relevance_score=relevance_score,
        )
        self._session.add(recommendation)
        await self._session.flush()
        return recommendation

    async def link_to_notebook(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        submission_id: uuid.UUID | None,
        student_notebook_id: uuid.UUID,
    ) -> None:
        """
        Rattachement APRÈS COUP (câblage NotebookLM, §7 Partie 2/2) — la
        tâche Celery qui crée le StudentNotebook s'exécute APRÈS que ces
        lignes existent déjà (générées de façon synchrone dans
        recommendation_node.py, cf. son docstring). Scopé par la même
        identité que la génération (student_id/module_id/submission_id,
        jamais le statut ACTIVE/SUPERSEDED — une ligne supersédée entre
        temps reste historiquement liée au notebook généré pour CET
        événement) ; `student_notebook_id IS NULL` évite de réécraser un
        rattachement déjà posé si cette méthode était rappelée deux fois.
        """
        conditions = [
            RecommendedExercise.student_id == student_id,
            RecommendedExercise.module_id == module_id,
            RecommendedExercise.student_notebook_id.is_(None),
        ]
        if submission_id is None:
            conditions.append(RecommendedExercise.submission_id.is_(None))
        else:
            conditions.append(RecommendedExercise.submission_id == submission_id)

        # SELECT puis mutation ORM (jamais un UPDATE bulk Core ici) —
        # constaté empiriquement : même avec synchronize_session="fetch",
        # un objet déjà chargé dans l'identity map de CETTE session (ex.
        # l'objet retourné par create() juste avant, dans le même appelant)
        # restait avec son ancien student_notebook_id en mémoire après un
        # UPDATE bulk (session.get() renvoie l'objet Python caché, pas une
        # relecture). Muter directement les objets via l'ORM les tient à
        # jour dans l'identity map sans détour — portée toujours modeste
        # (quelques lignes par événement de génération), jamais un souci de
        # performance contrairement à supersede() qui reste en bulk Core.
        result = await self._session.execute(select(RecommendedExercise).where(*conditions))
        for recommendation in result.scalars().all():
            recommendation.student_notebook_id = student_notebook_id
        await self._session.flush()
