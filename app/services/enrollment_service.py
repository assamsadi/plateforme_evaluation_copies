"""
Service Enrollment — règles métier :
1. Un étudiant SUSPENDED (Student.academic_status) ne peut PAS être
   inscrit à un nouveau module — vérifié explicitement AVANT création
   (rappel de conception : ce contrôle avait été identifié dès le
   modèle User comme devant vivre dans un service).
2. Réinscription après désinscription : RÉACTIVE la ligne existante
   (is_active=True), ne crée jamais de nouvelle ligne — la contrainte
   unique (student_id, module_id) porte sur la paire peu importe
   is_active, donc une tentative de création échouerait de toute façon.
3. Double inscription active : refusée avec message clair.
"""
import uuid
from typing import Protocol

from app.core.exceptions import (
    AlreadyEnrolledError,
    EnrollmentNotFoundError,
    StudentNotFoundError,
    StudentSuspendedError,
)
from app.domain.models.academic.enrollment import Enrollment
from app.domain.models.identity.user import AcademicStatus
from app.domain.repositories.enrollment_repository import EnrollmentRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.module_repository import ModuleRepositoryProtocol
from app.domain.repositories.pagination import CursorPage
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.academic_schemas import EnrollmentRead


class EnrollmentServiceProtocol(Protocol):
    async def get_by_id(self, enrollment_id: uuid.UUID) -> EnrollmentRead: ...
    async def list_by_student(
        self, student_id: uuid.UUID, cursor: str | None, limit: int
    ) -> CursorPage[EnrollmentRead]: ...
    async def list_by_module(
        self, module_id: uuid.UUID, cursor: str | None, limit: int
    ) -> CursorPage[EnrollmentRead]: ...
    async def list_by_student_for_professor(
        self, student_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> list[EnrollmentRead]: ...
    async def enroll(self, student_id: uuid.UUID, module_id: uuid.UUID) -> EnrollmentRead: ...
    async def unenroll(self, enrollment_id: uuid.UUID) -> EnrollmentRead: ...


# Pas de vraie pagination nécessaire ici (cf. list_by_student_for_professor
# ci-dessous) : un étudiant réel s'inscrit à une poignée de modules, jamais
# des centaines — même borne que list_evaluated_by_student_and_exercise_ids
# (ensemble modeste par construction, pas un affichage paginé).
_MAX_ENROLLMENTS_FOR_PROFESSOR_VIEW = 200


class EnrollmentService:
    def __init__(
        self,
        enrollment_repository: EnrollmentRepositoryProtocol,
        user_repository: UserRepositoryProtocol,
        module_repository: ModuleRepositoryProtocol,
        exercise_repository: ExerciseRepositoryProtocol,
    ) -> None:
        self._enrollments = enrollment_repository
        self._users = user_repository
        self._modules = module_repository
        self._exercises = exercise_repository

    async def _to_enrollment_read(self, enrollment: Enrollment) -> EnrollmentRead:
        """Peuple student_full_name et module_name et convertit en EnrollmentRead."""
        student = await self._users.get_by_id(enrollment.student_id)
        module = await self._modules.get_by_id(enrollment.module_id)
        enrollment.student_full_name = (
            f"{student.first_name} {student.last_name}" if student else "Unknown"
        )
        enrollment.module_name = module.name if module else "Unknown"
        return EnrollmentRead.model_validate(enrollment)

    async def get_by_id(self, enrollment_id: uuid.UUID) -> EnrollmentRead:
        enrollment = await self._enrollments.get_by_id(enrollment_id)
        if enrollment is None:
            raise EnrollmentNotFoundError(enrollment_id)
        return await self._to_enrollment_read(enrollment)

    async def list_by_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[EnrollmentRead]:
        page = await self._enrollments.list_by_student(
            student_id, cursor=cursor, limit=limit
        )
        items = [await self._to_enrollment_read(e) for e in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def list_by_module(
        self, module_id: uuid.UUID, cursor: str | None = None, limit: int = 50
    ) -> CursorPage[EnrollmentRead]:
        page = await self._enrollments.list_by_module(
            module_id, cursor=cursor, limit=limit
        )
        items = [await self._to_enrollment_read(e) for e in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

    async def list_by_student_for_professor(
        self, student_id: uuid.UUID, requesting_professor_id: uuid.UUID
    ) -> list[EnrollmentRead]:
        """
        Câblage écran "Profil de compétence" (sélecteur de module, vue
        professeur) — gap trouvé : list_by_student existait déjà (self
        étudiant uniquement, GET /students/me/enrollments), aucun endpoint
        n'exposait la liste des modules d'UN étudiant à un professeur.
        Même politique d'ownership que get_report_as_professor (Competency
        AssessmentService) et get_student_dashboard_as_professor
        (RecommendationService) : un professeur ne voit que les modules où
        il a lui-même créé au moins un exercice, jamais le profil scolaire
        complet d'un étudiant hors de sa portée. Filtré en mémoire après
        coup (pas en SQL) : le nombre de modules d'un étudiant réel est
        modeste, jamais besoin d'une jointure dédiée pour ça.
        """
        page = await self._enrollments.list_by_student(
            student_id, cursor=None, limit=_MAX_ENROLLMENTS_FOR_PROFESSOR_VIEW
        )
        visible: list[EnrollmentRead] = []
        for enrollment in page.items:
            enrollment_read = await self._to_enrollment_read(enrollment)
            if await self._exercises.exists_professor_exercise_in_module(
                requesting_professor_id, enrollment_read.module_id,
            ):
                visible.append(enrollment_read)
        return visible

    async def enroll(self, student_id: uuid.UUID, module_id: uuid.UUID) -> EnrollmentRead:
        # get_by_id_with_role_details (pas get_by_id) : academic_status vit
        # sur la sous-table students (héritage par tables jointes), un
        # get_by_id simple casse en MissingGreenlet au premier accès.
        student = await self._users.get_by_id_with_role_details(student_id)
        if student is None:
            raise StudentNotFoundError(student_id)

        if getattr(student, "academic_status", None) == AcademicStatus.SUSPENDED:
            raise StudentSuspendedError(student_id)

        existing = await self._enrollments.get_by_student_and_module(student_id, module_id)
        if existing is not None:
            if existing.is_active:
                raise AlreadyEnrolledError(student_id, module_id)
            reactivated = await self._enrollments.reactivate(existing.id)
            assert reactivated is not None
            return await self._to_enrollment_read(reactivated)

        enrollment = await self._enrollments.create(
            student_id=student_id, module_id=module_id
        )
        return await self._to_enrollment_read(enrollment)

    async def unenroll(self, enrollment_id: uuid.UUID) -> EnrollmentRead:
        deactivated = await self._enrollments.deactivate(enrollment_id)
        if deactivated is None:
            raise EnrollmentNotFoundError(enrollment_id)
        return await self._to_enrollment_read(deactivated)