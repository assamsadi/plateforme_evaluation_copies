"""
Service orchestrant les actions automatiques liées aux deadlines d'exercices.

Règles métier appliquées :
1. Les exercices (devoirs/examens) ayant dépassé leur deadline sont archivés automatiquement
   (status=ARCHIVED_IN_LIBRARY, plus de cours/deadline associés).
2. À la deadline d'un exercice, tout étudiant du groupe attendu n'ayant pas soumis
   reçoit automatiquement une soumission avec status=ABSENT et attempt_number=0.
3. Ces processus batchs doivent continuer même si une erreur survient sur un élément,
   en loggant l'erreur (pas de crash complet du job).
"""
import logging
from typing import Protocol

from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.submission import Submission
from app.domain.repositories.course_repository import CourseRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol

logger = logging.getLogger(__name__)


class ExerciseDeadlineServiceProtocol(Protocol):
    async def process_expired_exercises(self) -> tuple[list[Exercise], list[Submission]]: ...


class ExerciseDeadlineService:
    def __init__(
        self,
        exercise_repo: ExerciseRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        course_repo: CourseRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
    ) -> None:
        self._exercise_repo = exercise_repo
        self._submission_repo = submission_repo
        self._course_repo = course_repo
        self._user_repo = user_repo

    async def process_expired_exercises(self) -> tuple[list[Exercise], list[Submission]]:
        """
        Traite les exercices expirés en deux étapes séquentielles pour chaque exercice :
        1. Marque les étudiants absents (crée des soumissions ABSENT)
        2. Archive l'exercice dans la librairie (ARCHIVED_IN_LIBRARY)
        
        Cette approche garantit que le marquage des absences est toujours fait avant
        l'archivage, évitant ainsi tout problème de concurrence entre les deux opérations.
        
        Returns:
            Tuple contenant (liste des exercices archivés, liste des soumissions absentes créées)
        """
        archived_exercises = []
        absent_submissions = []
        cursor = None
        
        while True:
            page = await self._exercise_repo.list_with_expired_deadline(cursor=cursor, limit=100)
            
            for exercise in page.items:
                # Étape 1 : Marquer les étudiants absents (si l'exercice a un course_id)
                if exercise.course_id:
                    try:
                        course = await self._course_repo.get_by_id(exercise.course_id)
                        if course:
                            # Récupère tous les étudiants du groupe
                            students_page = await self._user_repo.list_students_by_group(
                                course.group_id, limit=1000
                            )
                            expected_student_ids = {s.id for s in students_page.items}

                            # S'il y a plus de 1000 étudiants, il faudrait paginer ici aussi.
                            # Pour la simplicité du cas typique, on s'arrête à la première page.
                            while students_page.next_cursor:
                                students_page = await self._user_repo.list_students_by_group(
                                    course.group_id, cursor=students_page.next_cursor, limit=1000
                                )
                                expected_student_ids.update(s.id for s in students_page.items)

                            # Récupère tous les étudiants ayant soumis
                            submitted_student_ids = set()
                            sub_cursor = None
                            while True:
                                subs_page = await self._submission_repo.list_by_exercise(
                                    exercise.id, cursor=sub_cursor, limit=1000
                                )
                                submitted_student_ids.update(s.student_id for s in subs_page.items)
                                if not subs_page.next_cursor:
                                    break
                                sub_cursor = subs_page.next_cursor

                            # Les manquants sont ceux attendus qui n'ont pas soumis
                            missing_student_ids = expected_student_ids - submitted_student_ids

                            for student_id in missing_student_ids:
                                try:
                                    absent_sub = await self._submission_repo.create_absent(
                                        exercise_id=exercise.id, student_id=student_id
                                    )
                                    absent_submissions.append(absent_sub)
                                except Exception as inner_e:
                                    logger.error(
                                        f"Erreur de marquage absent pour l'étudiant {student_id} sur l'exercice {exercise.id}: {inner_e}",
                                        exc_info=True,
                                    )
                    except Exception as e:
                        # Un échec sur un exercice ne doit pas interrompre le traitement des autres
                        logger.error(
                            f"Erreur lors du traitement des absences pour l'exercice {exercise.id}: {e}",
                            exc_info=True,
                        )
                
                # Étape 2 : Archiver l'exercice (toujours après l'étape 1)
                try:
                    archived = await self._exercise_repo.publish(
                        exercise_id=exercise.id,
                        status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
                        course_id=None,
                        deadline=None,
                    )
                    if archived:
                        archived_exercises.append(archived)
                except Exception as e:
                    logger.error(
                        f"Erreur lors de l'archivage de l'exercice {exercise.id}: {e}",
                        exc_info=True,
                    )
            
            if not page.next_cursor:
                break
            cursor = page.next_cursor

        return archived_exercises, absent_submissions
