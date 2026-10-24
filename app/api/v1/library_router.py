import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_current_professor,
    get_current_student,
    get_exercise_service,
    get_recommendation_service,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.identity.user import Professor, Student
from app.domain.schemas.evaluation_schemas import RecommendedExerciseRead
from app.domain.schemas.exercise_schemas import ExerciseRead
from app.services.exercise_service import ExerciseService
from app.services.recommendation_service import RecommendationService

router = APIRouter(tags=["library & recommendations"])


@router.get("/library/recommendations", response_model=list[RecommendedExerciseRead])
async def get_my_recommendations(
    current_student: Annotated[Student, Depends(get_current_student)],
    recommendation_service: Annotated[RecommendationService, Depends(get_recommendation_service)],
):
    return await recommendation_service.get_student_dashboard(student_id=current_student.id)


@router.post("/library/recommendations", response_model=RecommendedExerciseRead, status_code=status.HTTP_201_CREATED)
async def create_recommendation(
    submission_id: uuid.UUID,
    exercise_id: uuid.UUID,
    competency_code: C2PCTSkillCode,
    reason: str,
    relevance_score: float,
    recommendation_service: Annotated[RecommendationService, Depends(get_recommendation_service)],
    current_professor: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Point d'écriture CRUD hérité — faille d'accès fermée (chantier
    Recommendation_Agent, Phase 3) : `get_current_professor` (rôle PROFESSOR)
    ne suffit plus seul, le service vérifie en plus que ce professeur
    enseigne RÉELLEMENT le module de l'exercice ciblé (ForbiddenError ->
    403 sinon, cf. docstring RecommendationService.create_recommendation).
    competency_code requis (cf. schéma étendu, docstring RecommendedExercise)
    — student_id/module_id ne sont plus des paramètres libres, dérivés côté
    service de submission_id/exercise_id.
    """
    return await recommendation_service.create_recommendation(
        submission_id=submission_id,
        exercise_id=exercise_id,
        competency_code=competency_code,
        reason=reason,
        relevance_score=Decimal(str(relevance_score)),
        requesting_professor_id=current_professor.id,
    )
