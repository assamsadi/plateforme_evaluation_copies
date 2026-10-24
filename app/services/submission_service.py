"""
Service cœur de la soumission de copies.

Règles métier appliquées :
1. Un exercice non trouvé lève ExerciseNotFoundError.
2. Un étudiant dont le statut est SUSPENDED ne peut pas soumettre (StudentSuspendedError).
3. Exercice de type ARCHIVED_IN_LIBRARY : l'étudiant doit être inscrit au module (NotEnrolledError).
   Les tentatives multiples sont autorisées.
4. Exercice de type PUBLISHED_AS_EXAM ou PUBLISHED_AS_HOMEWORK : l'étudiant doit
   faire partie du groupe associé au cours (NotInExamGroupError).
   La date limite doit être respectée (DeadlinePassedError).
   Une seule tentative est autorisée (AlreadySubmittedError).
5. Un exercice DRAFT ne peut pas recevoir de soumission (ExerciseNotPublishedError).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol

from app.core.exceptions import (
    AlreadySubmittedError,
    ConflictError,
    DeadlinePassedError,
    ExerciseNotFoundError,
    ExerciseNotPublishedError,
    ForbiddenError,
    NotEnrolledError,
    NotFoundError,
    NotInExamGroupError,
    StudentNotFoundError,
    StudentSuspendedError,
    SubmissionNotFoundError,
)
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.identity.user import AcademicStatus, Student
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.repositories.course_repository import CourseRepositoryProtocol
from app.domain.repositories.enrollment_repository import EnrollmentRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.pagination import DEFAULT_PAGE_SIZE, CursorPage
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.submission_schemas import SubmissionRead
from app.infra_services.storage_paths import mime_to_extension, submission_original_path
from app.infra_services.storage_service import StorageContainer, StorageService
from app.services.event_publisher_service import EventPublisherService
from app.tasks.submission_tasks import process_submission_created

logger = logging.getLogger(__name__)


async def _to_submission_read(
    submission: Submission,
    exercise_repo: ExerciseRepositoryProtocol,
    user_repo: UserRepositoryProtocol,
) -> SubmissionRead:
    """Enrichit et convertit une Submission en SubmissionRead."""
    exercise = await exercise_repo.get_by_id(submission.exercise_id)
    student = await user_repo.get_by_id(submission.student_id)
    submission.exercise_title = exercise.title if exercise else "Unknown"
    submission.student_full_name = (
        f"{student.first_name} {student.last_name}" if student else "Unknown"
    )
    return SubmissionRead.model_validate(submission)


class SubmissionServiceProtocol(Protocol):
    async def create_submission(
        self,
        exercise_id: uuid.UUID,
        student_id: uuid.UUID,
        document_bytes: bytes,
        mime_type: str,
    ) -> SubmissionRead: ...
    async def get_submission(self, submission_id: uuid.UUID) -> SubmissionRead: ...
    async def update_status(self, submission_id: uuid.UUID, status: SubmissionStatus) -> SubmissionRead: ...
    async def list_by_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[SubmissionRead]: ...


class SubmissionService:
    def __init__(
        self,
        submission_repo: SubmissionRepositoryProtocol,
        exercise_repo: ExerciseRepositoryProtocol,
        course_repo: CourseRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
        enrollment_repo: EnrollmentRepositoryProtocol,
        storage_service: StorageService | None = None,
        event_publisher: EventPublisherService | None = None,
    ) -> None:
        self._submission_repo = submission_repo
        self._exercise_repo = exercise_repo
        self._course_repo = course_repo
        self._user_repo = user_repo
        self._enrollment_repo = enrollment_repo
        self._storage = storage_service or StorageService()
        self._events = event_publisher or EventPublisherService()

    async def create_submission(
        self,
        exercise_id: uuid.UUID,
        student_id: uuid.UUID,
        document_bytes: bytes,
        mime_type: str,
    ) -> SubmissionRead:
        # 1. Vérifier l'exercice
        exercise = await self._exercise_repo.get_by_id(exercise_id)
        if not exercise:
            raise ExerciseNotFoundError(exercise_id)

        # 2. Vérifier le statut académique de l'étudiant
        # Bug corrigé (espace étudiant, trouvé en testant un vrai dépôt de
        # copie de bout en bout) : get_by_id() simple ne charge que la table
        # users de base — lire ensuite user.academic_status (colonne
        # spécifique à students) déclenche un lazy-load synchrone qui casse
        # en contexte async (MissingGreenlet : "greenlet_spawn has not been
        # called"), CRASH SYSTÉMATIQUE à chaque dépôt réel. Jamais détecté
        # avant : les tests unitaires mockent user_repo avec un objet où
        # academic_status est déjà un attribut Python plat, aucun vrai
        # lazy-load SQLAlchemy déclenché. get_by_id_with_role_details()
        # existe déjà précisément pour ce cas (cf. sa docstring).
        user = await self._user_repo.get_by_id_with_role_details(student_id)
        if not user or not isinstance(user, Student):
            raise StudentNotFoundError(student_id)
            
        if user.academic_status == AcademicStatus.SUSPENDED:
            raise StudentSuspendedError(student_id)

        # 3. Exercice en librairie
        if exercise.status == ExerciseStatus.ARCHIVED_IN_LIBRARY:
            is_enrolled = await self._enrollment_repo.is_student_enrolled_and_active(
                student_id, exercise.module_id
            )
            if not is_enrolled:
                raise NotEnrolledError(student_id, exercise.module_id)
            attempt_number = await self._submission_repo.get_next_attempt_number(
                exercise_id, student_id
            )

        # 4. Exercice d'examen / devoir
        elif exercise.status in (ExerciseStatus.PUBLISHED_AS_EXAM, ExerciseStatus.PUBLISHED_AS_HOMEWORK):
            if not exercise.course_id:
                # Ne devrait jamais arriver structurellement pour ces statuts
                raise ExerciseNotPublishedError(exercise_id)
            
            in_group = await self._course_repo.is_student_in_course_group(
                exercise.course_id, student_id
            )
            if not in_group:
                raise NotInExamGroupError(student_id, exercise.course_id)
                
            if exercise.deadline and datetime.now(timezone.utc) > exercise.deadline:
                raise DeadlinePassedError(exercise_id)

            attempts = await self._submission_repo.count_attempts(exercise_id, student_id)
            if attempts > 0:
                raise AlreadySubmittedError(exercise_id, student_id)
                
            attempt_number = 1

        # 5. Exercice brouillon
        elif exercise.status == ExerciseStatus.DRAFT:
            raise ExerciseNotPublishedError(exercise_id)
            
        else:
            raise ValueError(f"Statut d'exercice non supporté : {exercise.status}")

        # 6. Création + upload document + événement Kafka
        submission = await self._submission_repo.create(exercise_id, student_id, attempt_number)

        extension = mime_to_extension(mime_type)
        blob_path = submission_original_path(submission.id, extension)
        await self._storage.upload(
            StorageContainer.SUBMISSIONS,
            blob_path,
            document_bytes,
            content_type=mime_type,
        )
        await self._submission_repo.update_document(submission.id, blob_path, mime_type)

        # 2026-08-30 — dispatch direct de la tâche Celery, jamais plus via un
        # événement Kafka (SubmissionCreatedConsumer, supprimé de ce chemin).
        # Constaté en test réel de bout en bout : aucun broker Kafka
        # n'existe dans cet environnement (localhost:9092 refuse activement
        # la connexion) — le publish échouait systématiquement (avalé par le
        # try/except ci-dessous, jamais remonté à l'étudiant), et comme
        # AUCUN autre consumer que celui dispatchant cette même tâche
        # Celery n'existe pour ce topic (vérifié : SubmissionCreatedConsumer
        # ne fait rien d'autre), Kafka n'apportait ici aucun découplage réel
        # — juste un point de défaillance supplémentaire. Même pattern déjà
        # utilisé par exercise_service.upload_reference_document (dispatch
        # Celery direct, jamais d'événement intermédiaire).
        #
        # Garde-fou conservé (bug d'origine, espace étudiant) : cet appel ne
        # doit jamais faire échouer TOUTE la requête en 500 alors que la
        # Submission ET le document sont déjà persistés avec succès juste
        # avant — un broker Celery/Redis injoignable resterait loggé en
        # ERROR (attention opérationnelle réelle nécessaire), jamais un
        # échec silencieux de la requête elle-même.
        try:
            process_submission_created.delay(
                submission_id=str(submission.id),
                exercise_id=str(exercise_id),
                student_id=str(student_id),
                attempt_number=attempt_number,
                document_path=blob_path,
                mime_type=mime_type,
            )
        except Exception:
            logger.error(
                "Échec du dispatch Celery de process_submission_created pour "
                "submission_id=%s — la soumission est bien créée mais restera "
                "bloquée en PENDING_OCR tant que ceci n'est pas résolu manuellement.",
                submission.id, exc_info=True,
            )

        return await _to_submission_read(submission, self._exercise_repo, self._user_repo)

    async def get_submission(self, submission_id: uuid.UUID) -> SubmissionRead:
        submission = await self._submission_repo.get_by_id(submission_id)
        if not submission:
            raise SubmissionNotFoundError(submission_id)
        return await _to_submission_read(submission, self._exercise_repo, self._user_repo)

    async def update_status(self, submission_id: uuid.UUID, status: SubmissionStatus) -> SubmissionRead:
        submission = await self._submission_repo.update_status(submission_id, status)
        if not submission:
            raise SubmissionNotFoundError(submission_id)
        return await _to_submission_read(submission, self._exercise_repo, self._user_repo)

    async def list_by_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[SubmissionRead]:
        """
        Bug corrigé (espace étudiant) : GET /students/me/submissions
        appelait submission_service._submission_repo.list_by_student(...)
        directement depuis le routeur (attribut privé, jamais passé par ce
        service) — renvoyait des Submission ORM brutes, jamais enrichies
        via _to_submission_read (exercise_title/student_full_name
        manquants). response_model=CursorPage[SubmissionRead] exige ces
        deux champs -> échec de validation à chaque appel réel.
        """
        page = await self._submission_repo.list_by_student(student_id, cursor=cursor, limit=limit)
        items = [await _to_submission_read(s, self._exercise_repo, self._user_repo) for s in page.items]
        return CursorPage(items=items, next_cursor=page.next_cursor, has_more=page.has_more)

