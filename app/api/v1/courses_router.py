import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_course_service,
    get_current_admin,
    get_current_professor,
    get_current_user,
    get_group_service,
)
from app.domain.models.identity.user import User
from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.academic_schemas import (
    CourseCreate,
    CourseRead,
    CourseUpdate,
    GroupCreate,
    GroupRead,
)
from app.domain.schemas.auth_schemas import StudentPublic
from app.services.course_service import CourseService
from app.services.group_service import GroupService

router = APIRouter(tags=["courses & groups"])


# --- Course Endpoints ---

@router.get("/courses/mine", response_model=CursorPage[CourseRead])
async def list_my_courses(
    course_service: Annotated[CourseService, Depends(get_course_service)],
    current_prof: Annotated[User, Depends(get_current_professor)],
    cursor: str | None = None,
    limit: int = 50,
):
    # Doit être déclaré AVANT /courses/{course_id} : sinon FastAPI essaie de
    # parser "mine" comme un UUID pour la route suivante et renvoie 422.
    return await course_service.list_by_professor(current_prof.id, cursor=cursor, limit=limit)


@router.get("/courses/{course_id}", response_model=CourseRead)
async def get_course(
    course_id: uuid.UUID,
    course_service: Annotated[CourseService, Depends(get_course_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await course_service.get_by_id(course_id)


@router.post("/courses", response_model=CourseRead, status_code=status.HTTP_201_CREATED)
async def create_course(
    schema: CourseCreate,
    course_service: Annotated[CourseService, Depends(get_course_service)],
    current_prof: Annotated[User, Depends(get_current_professor)],
):
    return await course_service.create(
        module_id=schema.module_id,
        group_id=schema.group_id,
        professor_user_id=current_prof.id,
        semester=schema.semester,
    )


@router.delete("/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: uuid.UUID,
    course_service: Annotated[CourseService, Depends(get_course_service)],
    current_prof: Annotated[User, Depends(get_current_professor)],
):
    # Bug corrigé (audit CRUD authoring) : current_prof.id n'était jamais
    # transmis — n'importe quel professeur pouvait supprimer le cours d'un
    # autre, aucune vérification de propriété n'était possible côté service.
    await course_service.delete(course_id, current_prof.id)


@router.patch("/courses/{course_id}", response_model=CourseRead)
async def update_course(
    course_id: uuid.UUID,
    schema: CourseUpdate,
    course_service: Annotated[CourseService, Depends(get_course_service)],
    current_prof: Annotated[User, Depends(get_current_professor)],
):
    """
    Gap trouvé lors de l'audit CRUD authoring : aucun endpoint ne permettait
    de modifier un cours après création (ex. corriger le semestre saisi).
    Seul le titulaire du cours peut le modifier — même contrôle que delete().
    """
    return await course_service.update_semester(
        course_id=course_id,
        requesting_professor_id=current_prof.id,
        semester=schema.semester,
    )


@router.get("/courses/{course_id}/students", response_model=list[StudentPublic])
async def list_course_students(
    course_id: uuid.UUID,
    course_service: Annotated[CourseService, Depends(get_course_service)],
    current_prof: Annotated[User, Depends(get_current_professor)],
):
    """
    Gap trouvé lors de l'audit résultats étudiants : UserRepository.
    list_students_by_group existait déjà en interne, jamais exposé — un
    professeur n'avait aucun moyen de découvrir quels étudiants suivent un
    de ses cours avant de consulter leur profil de compétences ou leurs
    recommandations (qui exigent déjà un student_id connu d'avance).
    """
    return await course_service.list_students(course_id, current_prof.id)


# --- Group Endpoints ---

@router.get("/groups/{group_id}", response_model=GroupRead)
async def get_group(
    group_id: uuid.UUID,
    group_service: Annotated[GroupService, Depends(get_group_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await group_service.get_by_id(group_id)


@router.get("/programs/{program_id}/groups", response_model=CursorPage[GroupRead])
async def list_groups_by_program(
    program_id: uuid.UUID,
    group_service: Annotated[GroupService, Depends(get_group_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    cursor: str | None = None,
    limit: int = 50,
):
    return await group_service.list_by_program(program_id=program_id, cursor=cursor, limit=limit)


@router.post("/programs/{program_id}/groups", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(
    program_id: uuid.UUID,
    schema: GroupCreate,
    group_service: Annotated[GroupService, Depends(get_group_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await group_service.create(program_id=program_id, label=schema.label, academic_year=schema.academic_year)


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    group_service: Annotated[GroupService, Depends(get_group_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    await group_service.delete(group_id)
