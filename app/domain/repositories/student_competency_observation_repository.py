"""
Repository StudentCompetencyObservation — historique atomique Niveau 2,
un fait immuable par (student, module, competency, submission). Écrit une
seule fois par CompetencyAssessmentService.assess_submission (jamais
modifié ensuite), lu par ordre de récence pour calculer Niveau 3
(décroissance exponentielle) et assembler les champs enrichis.
"""
import uuid
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_observation import (
    StudentCompetencyObservation,
)


class StudentCompetencyObservationRepositoryProtocol(Protocol):
    async def create(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        competency_code: C2PCTSkillCode,
        submission_id: uuid.UUID,
        performance_copie: Decimal,
        subquestions_covered_count: int,
        subquestions_succeeded_count: int,
        question_ids: list[str],
        subquestion_outcomes: list[dict],
        decision_reasons: list[dict],
    ) -> StudentCompetencyObservation: ...

    async def list_recent(
        self, student_id: uuid.UUID, module_id: uuid.UUID, competency_code: C2PCTSkillCode,
    ) -> list[StudentCompetencyObservation]: ...

    async def list_all_by_student_and_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[StudentCompetencyObservation]: ...

    async def list_recent_all_competencies(
        self, student_id: uuid.UUID, module_id: uuid.UUID, limit: int,
    ) -> list[StudentCompetencyObservation]: ...


class SQLAlchemyStudentCompetencyObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        student_id: uuid.UUID,
        module_id: uuid.UUID,
        competency_code: C2PCTSkillCode,
        submission_id: uuid.UUID,
        performance_copie: Decimal,
        subquestions_covered_count: int,
        subquestions_succeeded_count: int,
        question_ids: list[str],
        subquestion_outcomes: list[dict],
        decision_reasons: list[dict],
    ) -> StudentCompetencyObservation:
        observation = StudentCompetencyObservation(
            student_id=student_id,
            module_id=module_id,
            competency_code=competency_code,
            submission_id=submission_id,
            performance_copie=performance_copie,
            subquestions_covered_count=subquestions_covered_count,
            subquestions_succeeded_count=subquestions_succeeded_count,
            question_ids=question_ids,
            subquestion_outcomes=subquestion_outcomes,
            decision_reasons=decision_reasons,
        )
        self._session.add(observation)
        await self._session.flush()
        return observation

    async def list_recent(
        self, student_id: uuid.UUID, module_id: uuid.UUID, competency_code: C2PCTSkillCode,
    ) -> list[StudentCompetencyObservation]:
        """
        Triées par récence décroissante (la plus récente en premier) —
        ordre attendu par Competency_Assessment_Agent.build_competency_line
        pour la pondération de décroissance (rang 0 = poids le plus fort).
        """
        result = await self._session.execute(
            select(StudentCompetencyObservation)
            .where(
                StudentCompetencyObservation.student_id == student_id,
                StudentCompetencyObservation.module_id == module_id,
                StudentCompetencyObservation.competency_code == competency_code,
            )
            .order_by(StudentCompetencyObservation.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_all_by_student_and_module(
        self, student_id: uuid.UUID, module_id: uuid.UUID,
    ) -> list[StudentCompetencyObservation]:
        """Toutes compétences confondues, triées par récence — le service groupe ensuite par competency_code."""
        result = await self._session.execute(
            select(StudentCompetencyObservation)
            .where(
                StudentCompetencyObservation.student_id == student_id,
                StudentCompetencyObservation.module_id == module_id,
            )
            .order_by(StudentCompetencyObservation.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_recent_all_competencies(
        self, student_id: uuid.UUID, module_id: uuid.UUID, limit: int,
    ) -> list[StudentCompetencyObservation]:
        """
        Câblage écran "Profil de compétence" (graphique d'évolution dans le
        temps) — DISTINCT de list_all_by_student_and_module (illimité,
        nécessaire à Niveau 3 pour un calcul de décroissance exact sur TOUT
        l'historique) : ici volontairement borné par `limit`, un étudiant
        réel accumulant potentiellement des dizaines d'observations sur
        plusieurs années ne doit jamais faire grossir cette réponse sans
        fin — seul un historique récent a un intérêt pour un graphique.
        Résultat renvoyé en ordre chronologique CROISSANT (le plus ancien
        en premier, inverse de list_recent/list_all_by_student_and_module)
        — c'est l'ordre attendu par un tracé de courbe, jamais l'ordre de
        pondération de décroissance dont ces deux autres méthodes ont besoin.
        """
        result = await self._session.execute(
            select(StudentCompetencyObservation)
            .where(
                StudentCompetencyObservation.student_id == student_id,
                StudentCompetencyObservation.module_id == module_id,
            )
            .order_by(StudentCompetencyObservation.created_at.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        rows.reverse()
        return rows
