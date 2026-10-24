"""
Service de supervision admin des Job (lecture/agrégation seule — aucune
logique d'exécution du pipeline ici, jamais de création/relance de Job,
cf. job_tasks.py/graph pour ça).
"""
import uuid
from typing import Any, Protocol

from app.core.exceptions import JobNotFoundError
from app.domain.models.system_infrastructure.job import Job, JobStatus
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.job_repository import JobRepositoryProtocol
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol

# États qui méritent l'attention d'un admin — RUNNING/PENDING sont des
# états normaux en cours, COMPLETED/CANCELLED sont terminaux non
# problématiques (décision actée, cf. docstring JobsOverview).
_PROBLEMATIC_STATUSES = (JobStatus.INTERRUPTED, JobStatus.FAILED, JobStatus.RETRYING)

_DEFAULT_RECENT_LIMIT = 20
_DEFAULT_PROBLEMATIC_LIMIT_PER_STATUS = 20


class JobSupervisionServiceProtocol(Protocol):
    async def get_overview(self) -> dict[str, Any]: ...
    async def get_job_detail(self, job_id: uuid.UUID) -> Job: ...
    async def get_latest_for_exercise(self, exercise_id: uuid.UUID) -> Job | None: ...


class JobSupervisionService:
    def __init__(
        self,
        job_repo: JobRepositoryProtocol,
        exercise_repo: ExerciseRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
    ) -> None:
        self._job_repo = job_repo
        self._exercise_repo = exercise_repo
        self._submission_repo = submission_repo
        self._user_repo = user_repo

    async def get_overview(
        self,
        recent_limit: int = _DEFAULT_RECENT_LIMIT,
        problematic_limit_per_status: int = _DEFAULT_PROBLEMATIC_LIMIT_PER_STATUS,
    ) -> dict[str, Any]:
        counts = await self._job_repo.count_by_status()
        counts_by_status = {status.value: counts.get(status.value, 0) for status in JobStatus}

        recent_jobs = await self._job_repo.list_recent(limit=recent_limit)

        problematic_jobs: list[Job] = []
        for status in _PROBLEMATIC_STATUSES:
            page = await self._job_repo.list_by_status(status, limit=problematic_limit_per_status)
            problematic_jobs.extend(page.items)

        await self._attach_display_names(recent_jobs + problematic_jobs)

        return {
            "counts_by_status": counts_by_status,
            "recent_jobs": recent_jobs,
            "problematic_jobs": problematic_jobs,
        }

    async def _attach_display_names(self, jobs: list[Job]) -> None:
        """
        Positionne exercise_title/student_full_name en mémoire sur chaque Job
        (jamais des colonnes ORM, cf. JobRead) — pas de relationship() Job ->
        Submission/Exercise/Student dans ce projet, donc lookups manuels, mais
        mis en cache par id le temps de cet appel pour éviter les doublons
        (plusieurs Job pointent souvent vers le même exercice/étudiant).
        """
        exercise_cache: dict[uuid.UUID, Any] = {}
        submission_cache: dict[uuid.UUID, Any] = {}
        user_cache: dict[uuid.UUID, Any] = {}

        async def get_exercise(exercise_id: uuid.UUID) -> Any:
            if exercise_id not in exercise_cache:
                exercise_cache[exercise_id] = await self._exercise_repo.get_by_id(exercise_id)
            return exercise_cache[exercise_id]

        async def get_user(user_id: uuid.UUID) -> Any:
            if user_id not in user_cache:
                user_cache[user_id] = await self._user_repo.get_by_id(user_id)
            return user_cache[user_id]

        for job in jobs:
            if job.submission_id is not None:
                if job.submission_id not in submission_cache:
                    submission_cache[job.submission_id] = await self._submission_repo.get_by_id(job.submission_id)
                submission = submission_cache[job.submission_id]
                if submission is not None:
                    exercise = await get_exercise(submission.exercise_id)
                    student = await get_user(submission.student_id)
                    job.exercise_title = exercise.title if exercise else None
                    job.student_full_name = f"{student.first_name} {student.last_name}" if student else None
                    continue
            if job.exercise_id is not None:
                exercise = await get_exercise(job.exercise_id)
                job.exercise_title = exercise.title if exercise else None

    async def get_job_detail(self, job_id: uuid.UUID) -> Job:
        job = await self._job_repo.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    async def get_latest_for_exercise(self, exercise_id: uuid.UUID) -> Job | None:
        """
        Gap trouvé lors de l'audit authoring : admin dispose de /admin/jobs/
        overview, mais un professeur n'avait aucun moyen de savoir si le
        pipeline OCR déclenché par upload_reference_document a terminé,
        échoué, ou tourne encore — sinon un simple polling de GET /exercises/
        {id} en scrutant l'apparition de baremes. None si aucun Job n'a
        jamais été créé pour cet exercice (ex. professeur 100% manuel).
        """
        return await self._job_repo.get_latest_for_thread(exercise_id)
