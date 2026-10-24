"""
Repository Course.

Méthodes clés :
- get_by_id          : chargement direct par PK
- get_by_unique_key  : accès via la contrainte composite (module, group, semester)
- list_by_module     : tous les cours d'une matière (vue admin/prof)
- list_by_professor  : tous les cours d'un professeur
- list_by_group      : tous les cours d'un groupe (vue étudiant)
- create             : création d'un nouveau cours
- update_professor   : réassignation du professeur titulaire
- is_student_in_course_group : EXISTS pur — appelé par SubmissionService pour
  vérifier qu'un étudiant appartient bien au groupe associé à un cours avant
  d'autoriser une soumission d'examen/devoir.
"""
import uuid
from typing import Protocol

from sqlalchemy import exists, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.academic.course import Course
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class CourseRepositoryProtocol(Protocol):
    async def get_by_id(self, course_id: uuid.UUID) -> Course | None: ...
    async def get_by_unique_key(
        self, module_id: uuid.UUID, group_id: uuid.UUID, semester: str
    ) -> Course | None: ...
    async def list_by_module(
        self, module_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Course]: ...
    async def list_by_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Course]: ...
    async def list_by_group(
        self, group_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Course]: ...
    async def create(
        self,
        module_id: uuid.UUID,
        professor_user_id: uuid.UUID,
        group_id: uuid.UUID,
        semester: str,
    ) -> Course: ...
    async def update_professor(
        self, course_id: uuid.UUID, new_professor_id: uuid.UUID
    ) -> Course | None: ...
    async def update_semester(
        self, course_id: uuid.UUID, semester: str
    ) -> Course | None: ...
    async def is_student_in_course_group(
        self, course_id: uuid.UUID, student_id: uuid.UUID
    ) -> bool: ...


class SQLAlchemyCourseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, course_id: uuid.UUID) -> Course | None:
        return await self._session.get(Course, course_id)

    async def get_by_unique_key(
        self, module_id: uuid.UUID, group_id: uuid.UUID, semester: str
    ) -> Course | None:
        result = await self._session.execute(
            select(Course).where(
                Course.module_id == module_id,
                Course.group_id == group_id,
                Course.semester == semester,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_module(
        self, module_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Course]:
        query = select(Course).where(Course.module_id == module_id)
        return await self._paginated_query(query, cursor, limit)

    async def list_by_professor(
        self, professor_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Course]:
        query = select(Course).where(Course.professor_user_id == professor_id)
        return await self._paginated_query(query, cursor, limit)

    async def list_by_group(
        self, group_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Course]:
        query = select(Course).where(Course.group_id == group_id)
        return await self._paginated_query(query, cursor, limit)

    async def _paginated_query(self, query, cursor: str | None, limit: int) -> CursorPage[Course]:
        query = query.order_by(Course.created_at, Course.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Course.created_at, Course.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda c: (c.created_at, c.id))

    async def create(
        self,
        module_id: uuid.UUID,
        professor_user_id: uuid.UUID,
        group_id: uuid.UUID,
        semester: str,
    ) -> Course:
        course = Course(
            module_id=module_id,
            professor_user_id=professor_user_id,
            group_id=group_id,
            semester=semester,
        )
        self._session.add(course)
        await self._session.flush()
        return course

    async def update_professor(
        self, course_id: uuid.UUID, new_professor_id: uuid.UUID
    ) -> Course | None:
        course = await self.get_by_id(course_id)
        if course is None:
            return None
        course.professor_user_id = new_professor_id
        await self._session.flush()
        return course

    async def update_semester(
        self, course_id: uuid.UUID, semester: str
    ) -> Course | None:
        course = await self.get_by_id(course_id)
        if course is None:
            return None
        course.semester = semester
        await self._session.flush()
        return course

    async def is_student_in_course_group(
        self, course_id: uuid.UUID, student_id: uuid.UUID
    ) -> bool:
        """
        EXISTS pur — vérifie qu'un étudiant (via student.group_id) appartient
        au groupe associé au cours. Appelé par SubmissionService avant toute
        soumission d'examen ou devoir. Aucun objet ORM chargé en mémoire.
        """
        from app.domain.models.identity.user import Student

        stmt = select(
            exists().where(
                Course.id == course_id,
                Student.id == student_id,
                Student.group_id == Course.group_id,
            )
        )
        result = await self._session.execute(stmt)
        return bool(result.scalar())
