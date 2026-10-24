import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_current_user,
    get_exercise_service,
)
from app.domain.models.identity.user import User
from app.domain.schemas.exercise_schemas import ExerciseRead
from app.services.exercise_service import ExerciseService

router = APIRouter(tags=["bareme"])


@router.get("/exercises/{exercise_id}/bareme")
async def get_exercise_bareme(
    exercise_id: uuid.UUID,
    exercise_service: Annotated[ExerciseService, Depends(get_exercise_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    exercise = await exercise_service.get_by_id(exercise_id)
    return {
        "exercise_id": str(exercise_id),
        "title": exercise.title,
        "questions": [q.model_dump() for q in exercise.questions],
    }
