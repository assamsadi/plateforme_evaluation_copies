import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import (
    get_current_student,
    get_current_user,
    get_extraction_service,
    get_submission_service,
)
from app.domain.models.identity.user import User, Student
from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.contestation_schemas import ContestExtractionRequest
from app.domain.schemas.submission_schemas import (
    ExtractionCorrectionRead,
    SubmissionConfirmationRead,
    SubmissionRead,
)
from app.services.extraction_service import ExtractionService
from app.services.submission_service import SubmissionService

router = APIRouter(tags=["submissions"])

ALLOWED_SUBMISSION_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/tiff",
}


@router.get("/submissions/{submission_id}", response_model=SubmissionRead)
async def get_submission(
    submission_id: uuid.UUID,
    submission_service: Annotated[SubmissionService, Depends(get_submission_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await submission_service.get_submission(submission_id)


@router.get("/students/me/submissions", response_model=CursorPage[SubmissionRead])
async def list_my_submissions(
    current_student: Annotated[Student, Depends(get_current_student)],
    submission_service: Annotated[SubmissionService, Depends(get_submission_service)],
    cursor: str | None = None,
    limit: int = 50,
):
    """
    Bug corrigé (espace étudiant) : appelait submission_service.
    _submission_repo.list_by_student(...) directement (attribut privé, ORM
    brute jamais enrichie) — plantait la validation response_model à chaque
    appel réel (exercise_title/student_full_name absents). Passe désormais
    par SubmissionService.list_by_student, qui enrichit correctement.
    """
    return await submission_service.list_by_student(
        student_id=current_student.id, cursor=cursor, limit=limit
    )


@router.post("/submissions", response_model=SubmissionRead, status_code=status.HTTP_201_CREATED)
async def create_submission(
    exercise_id: Annotated[uuid.UUID, Form()],
    document: Annotated[UploadFile, File(description="Copie scannée (PDF ou image)")],
    current_student: Annotated[Student, Depends(get_current_student)],
    submission_service: Annotated[SubmissionService, Depends(get_submission_service)],
):
    mime_type = (document.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if mime_type not in ALLOWED_SUBMISSION_MIME_TYPES:
        from app.core.exceptions import ValidationError
        raise ValidationError(
            f"Type de fichier non supporté : {mime_type}. "
            f"Formats acceptés : PDF, PNG, JPEG, WEBP, TIFF."
        )

    document_bytes = await document.read()
    if not document_bytes:
        from app.core.exceptions import ValidationError
        raise ValidationError("Le fichier soumis est vide.")

    return await submission_service.create_submission(
        exercise_id=exercise_id,
        student_id=current_student.id,
        document_bytes=document_bytes,
        mime_type=mime_type,
    )


@router.get(
    "/submissions/{submission_id}/corrections",
    response_model=list[ExtractionCorrectionRead],
)
async def list_submission_corrections(
    submission_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    extraction_service: Annotated[ExtractionService, Depends(get_extraction_service)],
):
    """
    Gap fermé (espace étudiant) : l'étudiant n'avait aucun moyen de voir ce
    qui a été extrait de sa copie (OCR_Extraction_Agent) avant de confirmer
    ou de contester — record_extraction() persistait déjà tout, mais rien
    n'exposait cette lecture. Cf. docstring ExtractionService.
    list_corrections_for_submission pour le détail (dont le bug image_url
    corrigé dans le même passage).
    """
    return await extraction_service.list_corrections_for_submission(
        submission_id=submission_id, student_id=current_student.id,
    )


@router.post(
    "/submissions/{submission_id}/confirm",
    response_model=SubmissionConfirmationRead,
)
async def confirm_submission(
    submission_id: uuid.UUID,
    current_student: Annotated[Student, Depends(get_current_student)],
    extraction_service: Annotated[ExtractionService, Depends(get_extraction_service)],
):
    """
    Gap fermé (pipeline student_evaluation) : "je confirme ma copie", seul
    déclencheur manquant de la reprise du thread LangGraph en pause à
    await_student_verification_node quand l'étudiant n'a rien à contester —
    cf. docstring ExtractionService.confirm_submission pour le détail
    complet (anticipé mais jamais construit, cf. job_tasks.py).
    """
    return await extraction_service.confirm_submission(
        submission_id=submission_id, student_id=current_student.id,
    )


@router.post(
    "/submissions/{submission_id}/corrections/{correction_id}/contest",
    response_model=ExtractionCorrectionRead,
)
async def contest_extraction_correction(
    submission_id: uuid.UUID,
    correction_id: uuid.UUID,
    request: ContestExtractionRequest,
    current_student: Annotated[Student, Depends(get_current_student)],
    extraction_service: Annotated[ExtractionService, Depends(get_extraction_service)],
):
    return await extraction_service.contest_extraction(
        submission_id=submission_id,
        correction_id=correction_id,
        student_id=current_student.id,
        request=request,
    )
