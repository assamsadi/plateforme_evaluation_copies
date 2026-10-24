"""
Repository StudentCompetencyProfile — cache léger, écrit par
CompetencyAssessmentService.assess_submission (Niveau 2/3, cf. docstring
du modèle) après chaque soumission entièrement notée.

competency_code (enum C2PCTSkillCode) remplace l'ancienne FK competency_id
(table C2PCTCompetency supprimée — le fichier .md est l'unique source de
vérité du contenu des compétences).

upsert() utilise INSERT ... ON CONFLICT DO UPDATE (natif PostgreSQL) —
ATOMIQUE, contrairement à un SELECT-puis-INSERT/UPDATE manuel qui aurait
une race condition si deux évaluations du même étudiant se terminaient
en même temps (deux process concurrents pourraient tous les deux voir
"n'existe pas" et tenter un INSERT en double, violant la contrainte
unique). Une seule requête, gérée au niveau DB.
"""
import uuid
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_profile import (
    CompetencyTrend,
    StudentCompetencyProfile,
)


class StudentCompetencyProfileRepositoryProtocol(Protocol):
    async def list_by_student_and_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID
    ) -> list[StudentCompetencyProfile]: ...
    async def list_distinct_modules_by_student(
        self, student_id: uuid.UUID
    ) -> list[uuid.UUID]: ...
    async def get_profile(
        self, student_id: uuid.UUID, competency_code: C2PCTSkillCode, module_id: uuid.UUID
    ) -> StudentCompetencyProfile | None: ...
    async def upsert(
        self,
        student_id: uuid.UUID,
        competency_code: C2PCTSkillCode,
        module_id: uuid.UUID,
        mastery_level: Decimal,
        trend: CompetencyTrend,
        evaluations_count: int = 0,
        confidence_level: Decimal = Decimal("0"),
        is_persistent_weakness: bool = False,
    ) -> StudentCompetencyProfile: ...


class SQLAlchemyStudentCompetencyProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_student_and_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID
    ) -> list[StudentCompetencyProfile]:
        result = await self._session.execute(
            select(StudentCompetencyProfile).where(
                StudentCompetencyProfile.student_id == student_id,
                StudentCompetencyProfile.module_id == module_id,
            )
        )
        return list(result.scalars().all())

    async def list_distinct_modules_by_student(self, student_id: uuid.UUID) -> list[uuid.UUID]:
        """
        Câblage écran "Profil de compétence" (sélecteur de module) — bug
        évité (test réel, 2026-08-31) : le premier réflexe était de lister
        les modules via Enrollment, mais un étudiant réel s'est révélé sans
        AUCUNE ligne Enrollment (accès à l'examen via appartenance au
        groupe du cours, PUBLISHED_AS_EXAM — cf. SubmissionService.
        create_submission — jamais via une inscription module explicite,
        contrairement au flux ARCHIVED_IN_LIBRARY). Enrollment n'est donc
        PAS une source fiable de "quels modules montrer ici". Cette table-ci
        est la bonne source : une ligne n'existe QUE si assess_submission a
        déjà tourné pour ce (student, module) — exactement "un module où il
        y a un vrai profil à afficher", jamais un module vide de données.
        """
        result = await self._session.execute(
            select(StudentCompetencyProfile.module_id)
            .where(StudentCompetencyProfile.student_id == student_id)
            .distinct()
        )
        return list(result.scalars().all())

    async def get_profile(
        self, student_id: uuid.UUID, competency_code: C2PCTSkillCode, module_id: uuid.UUID
    ) -> StudentCompetencyProfile | None:
        """
        Câblage réparation StudentCompetencyProfile — méthode appelée par
        EvaluationService (avant/après ce câblage) mais jamais implémentée
        ici : bug pré-existant, jamais détecté car la boucle appelante
        (ancien c2pct_observed) ne s'exécutait jamais en pratique (cf.
        rapport du chantier). uq_student_competency_module (contrainte
        unique sur les 3 colonnes) garantit au plus une ligne.
        """
        result = await self._session.execute(
            select(StudentCompetencyProfile).where(
                StudentCompetencyProfile.student_id == student_id,
                StudentCompetencyProfile.competency_code == competency_code,
                StudentCompetencyProfile.module_id == module_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        student_id: uuid.UUID,
        competency_code: C2PCTSkillCode,
        module_id: uuid.UUID,
        mastery_level: Decimal,
        trend: CompetencyTrend,
        evaluations_count: int = 0,
        confidence_level: Decimal = Decimal("0"),
        is_persistent_weakness: bool = False,
    ) -> StudentCompetencyProfile:
        stmt = pg_insert(StudentCompetencyProfile).values(
            student_id=student_id,
            competency_code=competency_code,
            module_id=module_id,
            mastery_level=mastery_level,
            trend=trend,
            evaluations_count=evaluations_count,
            confidence_level=confidence_level,
            is_persistent_weakness=is_persistent_weakness,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_student_competency_module",
            set_={
                "mastery_level": stmt.excluded.mastery_level,
                "trend": stmt.excluded.trend,
                "evaluations_count": stmt.excluded.evaluations_count,
                "confidence_level": stmt.excluded.confidence_level,
                "is_persistent_weakness": stmt.excluded.is_persistent_weakness,
                "last_computed_at": func.now(),
            },
        ).returning(StudentCompetencyProfile)

        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.scalar_one()