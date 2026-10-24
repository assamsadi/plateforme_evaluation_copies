"""
Service Course — règles métier :
1. Vérification EXPLICITE préalable de module_id/professor_id/group_id
   (3 requêtes, coût assumé pour un message d'erreur clair désignant
   PRÉCISÉMENT quelle FK est invalide — contrairement à Module où on
   laisse la DB échouer, ici 3 FK différentes rendraient un message
   d'erreur DB générique inexploitable pour l'utilisateur).
2. Interdiction de suppression si des Exercise actifs (mode examen/
   devoir) sont liés à ce Course.
"""
import uuid
from typing import Protocol

from app.core.exceptions import (
    CourseAlreadyExistsError,
    CourseHasActiveExercisesError,
    CourseInvalidReferenceError,
    CourseNotFoundError,
    NotCourseOwnerError,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.academic.course import Course
from app.domain.repositories.course_repository import CourseRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.group_repository import GroupRepositoryProtocol
from app.domain.repositories.module_repository import ModuleRepositoryProtocol
from app.domain.repositories.pagination import DEFAULT_PAGE_SIZE, CursorPage
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.academic_schemas import CourseRead
from app.domain.schemas.auth_schemas import StudentPublic


class CourseServiceProtocol(Protocol):
    async def get_by_id(self, course_id: uuid.UUID) -> CourseRead: ...
    async def create(
        self,
        module_id: uuid.UUID,
        professor_user_id: uuid.UUID,
        group_id: uuid.UUID,
        semester: str,
    ) -> CourseRead: ...
    async def delete(self, course_id: uuid.UUID, requesting_professor_id: uuid.UUID) -> None: ...
    async def update_semester(
        self, course_id: uuid.UUID, requesting_professor_id: uuid.UUID, semester: str
    ) -> CourseRead: ...
    async def list_students(
        self, course_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> list[StudentPublic]: ...
    async def list_by_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[CourseRead]: ...


class CourseService:
    def __init__(
        self,
        course_repository: CourseRepositoryProtocol,
        module_repository: ModuleRepositoryProtocol,
        user_repository: UserRepositoryProtocol,
        group_repository: GroupRepositoryProtocol,
        exercise_repository: ExerciseRepositoryProtocol,
    ) -> None:
        self._courses = course_repository
        self._modules = module_repository
        self._users = user_repository
        self._groups = group_repository
        self._exercises = exercise_repository

    async def _to_course_read(self, course: Course) -> CourseRead:
        """Enrichit et convertit un Course en CourseRead."""
        module = await self._modules.get_by_id(course.module_id)
        professor = await self._users.get_by_id(course.professor_user_id)
        group = await self._groups.get_by_id(course.group_id)
        
        course.module_name = module.name if module else "Unknown"
        course.professor_full_name = f"{professor.first_name} {professor.last_name}" if professor else "Unknown"
        course.group_label = group.label if group else "Unknown"
        
        return CourseRead.model_validate(course)

    async def get_by_id(self, course_id: uuid.UUID) -> CourseRead:
        course = await self._courses.get_by_id(course_id)
        if course is None:
            raise CourseNotFoundError(course_id)
        return await self._to_course_read(course)

    async def create(
        self,
        module_id: uuid.UUID,
        professor_user_id: uuid.UUID,
        group_id: uuid.UUID,
        semester: str,
    ) -> CourseRead:
        module = await self._modules.get_by_id(module_id)
        if module is None:
            raise CourseInvalidReferenceError("module_id", module_id)

        professor = await self._users.get_by_id(professor_user_id)
        if professor is None:
            raise CourseInvalidReferenceError("professor_user_id", professor_user_id)

        group = await self._groups.get_by_id(group_id)
        if group is None:
            raise CourseInvalidReferenceError("group_id", group_id)

        existing = await self._courses.get_by_unique_key(module_id, group_id, semester)
        if existing is not None:
            raise CourseAlreadyExistsError(module_id, group_id, semester)

        course = await self._courses.create(
            module_id=module_id,
            professor_user_id=professor_user_id,
            group_id=group_id,
            semester=semester,
        )
        
        # Enrichissement pour CourseRead
        course.module_name = module.name
        course.professor_full_name = f"{professor.first_name} {professor.last_name}"
        course.group_label = group.label
        
        return CourseRead.model_validate(course)

    async def list_by_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[CourseRead]:
        page = await self._courses.list_by_professor(professor_id, cursor=cursor, limit=limit)
        items = [await self._to_course_read(course) for course in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def delete(self, course_id: uuid.UUID, requesting_professor_id: uuid.UUID) -> None:
        raw_course = await self._courses.get_by_id(course_id)
        if raw_course is None:
            raise CourseNotFoundError(course_id)

        # Gap trouvé lors de l'audit CRUD authoring : cette vérification de
        # propriété n'existait pas du tout avant — n'importe quel professeur
        # authentifié pouvait supprimer le cours d'un autre.
        if raw_course.professor_user_id != requesting_professor_id:
            raise NotCourseOwnerError(course_id, requesting_professor_id)

        exercises_page = await self._exercises.list_by_course(course_id, limit=1)
        if exercises_page.items:
            raise CourseHasActiveExercisesError(course_id)

        await self._courses.delete(course_id)

    async def update_semester(
        self, course_id: uuid.UUID, requesting_professor_id: uuid.UUID, semester: str
    ) -> CourseRead:
        raw_course = await self._courses.get_by_id(course_id)
        if raw_course is None:
            raise CourseNotFoundError(course_id)

        if raw_course.professor_user_id != requesting_professor_id:
            raise NotCourseOwnerError(course_id, requesting_professor_id)

        if semester != raw_course.semester:
            existing = await self._courses.get_by_unique_key(
                raw_course.module_id, raw_course.group_id, semester
            )
            if existing is not None:
                raise CourseAlreadyExistsError(raw_course.module_id, raw_course.group_id, semester)

        updated = await self._courses.update_semester(course_id, semester)
        assert updated is not None  # garanti par get_by_id ci-dessus
        return await self._to_course_read(updated)

    async def list_students(
        self, course_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> list[StudentPublic]:
        """
        Gap trouvé lors de l'audit résultats étudiants : UserRepository.
        list_students_by_group existe déjà (utilisé en interne par
        exercise_deadline_service/group_service) mais n'était exposé par
        AUCUN endpoint — un professeur n'avait aucun moyen de découvrir
        QUELS étudiants suivent un de ses cours avant de consulter leur
        profil de compétences ou leurs recommandations (qui exigent déjà
        un student_id connu d'avance).
        """
        raw_course = await self._courses.get_by_id(course_id)
        if raw_course is None:
            raise CourseNotFoundError(course_id)

        if raw_course.professor_user_id != requesting_professor_id:
            raise NotCourseOwnerError(course_id, requesting_professor_id)

        page = await self._users.list_students_by_group(raw_course.group_id, limit=200)
        return [StudentPublic.model_validate(s) for s in page.items]