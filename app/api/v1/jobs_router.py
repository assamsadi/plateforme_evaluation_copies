import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_current_user,
    get_submission_service,
)
from app.domain.models.identity.user import User
from app.domain.schemas.submission_schemas import SubmissionRead
from app.services.submission_service import SubmissionService

router = APIRouter(tags=["jobs"])


@router.get("/jobs/submission/{submission_id}", response_model=SubmissionRead)
async def get_submission_job_status(
    submission_id: uuid.UUID,
    submission_service: Annotated[SubmissionService, Depends(get_submission_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await submission_service.get_submission(submission_id)
