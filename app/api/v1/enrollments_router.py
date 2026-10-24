import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_current_admin,
    get_current_student,
    get_current_user,
    get_enrollment_service,
)
from app.core.exceptions import ForbiddenError
from app.domain.models.identity.user import User, UserRole, Student
from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.academic_schemas import EnrollmentCreate, EnrollmentRead
from app.services.enrollment_service import EnrollmentService

router = APIRouter(tags=["enrollments"])


@router.get("/enrollments/{enrollment_id}", response_model=EnrollmentRead)
async def get_enrollment(
    enrollment_id: uuid.UUID,
    enrollment_service: Annotated[EnrollmentService, Depends(get_enrollment_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await enrollment_service.get_by_id(enrollment_id)


@router.get("/students/me/enrollments", response_model=CursorPage[EnrollmentRead])
async def list_my_enrollments(
    current_student: Annotated[Student, Depends(get_current_student)],
    enrollment_service: Annotated[EnrollmentService, Depends(get_enrollment_service)],
    cursor: str | None = None,
    limit: int = 50,
):
    return await enrollment_service.list_by_student(student_id=current_student.id, cursor=cursor, limit=limit)


@router.get("/modules/{module_id}/enrollments", response_model=CursorPage[EnrollmentRead])
async def list_enrollments_by_module(
    module_id: uuid.UUID,
    enrollment_service: Annotated[EnrollmentService, Depends(get_enrollment_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: str | None = None,
    limit: int = 50,
):
    return await enrollment_service.list_by_module(module_id=module_id, cursor=cursor, limit=limit)


@router.get("/students/{student_id}/enrollments", response_model=list[EnrollmentRead])
async def list_student_enrollments(
    student_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    enrollment_service: Annotated[EnrollmentService, Depends(get_enrollment_service)],
):
    """
    Écran "Profil de compétence" (sélecteur de module, vue professeur) —
    gap fermé : GET /students/me/enrollments existait déjà (self étudiant
    uniquement), aucun endpoint n'exposait les modules d'UN étudiant à un
    professeur. Même garde d'accès dual rôle que GET /students/{id}/
    competency-profile (results_router.py) — jamais une variante réécrite
    à la main.
    """
    current_user_id = uuid.UUID(str(current_user.id))

    if current_user.role == UserRole.STUDENT:
        if current_user_id != student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que ses propres inscriptions.")
        page = await enrollment_service.list_by_student(student_id, cursor=None, limit=50)
        return page.items

    if current_user.role == UserRole.PROFESSOR:
        return await enrollment_service.list_by_student_for_professor(
            student_id=student_id, requesting_professor_id=current_user_id,
        )

    raise ForbiddenError("Accès aux inscriptions réservé à l'étudiant concerné ou à ses professeurs.")


@router.post("/enrollments", response_model=EnrollmentRead, status_code=status.HTTP_201_CREATED)
async def enroll_student(
    schema: EnrollmentCreate,
    enrollment_service: Annotated[EnrollmentService, Depends(get_enrollment_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await enrollment_service.enroll(
        student_id=schema.student_id,
        module_id=schema.module_id,
    )


@router.post("/enrollments/{enrollment_id}/deactivate", response_model=EnrollmentRead)
async def deactivate_enrollment(
    enrollment_id: uuid.UUID,
    enrollment_service: Annotated[EnrollmentService, Depends(get_enrollment_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await enrollment_service.unenroll(enrollment_id)
