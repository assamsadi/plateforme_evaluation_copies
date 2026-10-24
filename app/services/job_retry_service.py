"""
Relance manuelle d'un Job FAILED — gap trouvé en test réel (2026-08-30) :
Celery retente déjà automatiquement 5 fois avec backoff exponentiel
(DEFAULT_RETRY_POLICY, cf. broker.py) avant de marquer un Job FAILED, mais
une fois ces retries épuisés, RIEN ne relance jamais la soumission —
jusqu'ici seul un développeur rappelant process_submission_created.delay(...)
à la main pouvait la débloquer. En prod, sans intervention manuelle, la
copie de l'étudiant reste bloquée indéfiniment en PENDING_OCR.

Volontairement séparé de JobSupervisionService (cf. son docstring :
"aucune logique d'exécution du pipeline ici, jamais de création/relance de
Job") — ce service EST cette logique de relance, jamais de la simple
lecture/agrégation.

Portée volontairement limitée à STUDENT_EVALUATION pour l'instant :
process_exercise_reference_document nécessite mime_type, jamais persisté
sur Exercise (seul document_path est reconstructible de façon déterministe
via exercise_reference_document_path) — relancer EXERCISE_SETUP à l'identique
demanderait de deviner le mime_type d'origine, jamais une vraie
reconstruction fiable. Lève NotImplementedError explicite plutôt qu'un
mime_type inventé qui échouerait silencieusement ou pire, réussirait sur le
mauvais type de fichier.
"""
import uuid

from app.core.exceptions import ConflictError, JobNotFoundError, SubmissionNotFoundError
from app.domain.models.system_infrastructure.job import Job, JobFlowType, JobStatus
from app.domain.repositories.job_repository import JobRepositoryProtocol
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.tasks.submission_tasks import process_submission_created


class JobRetryService:
    def __init__(
        self,
        job_repo: JobRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
    ) -> None:
        self._job_repo = job_repo
        self._submissions = submission_repo

    async def retry_job(self, job_id: uuid.UUID) -> Job:
        job = await self._job_repo.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(job_id)

        if job.status != JobStatus.FAILED:
            raise ConflictError(
                f"Job {job_id} n'est pas en échec (statut actuel : "
                f"{job.status.value}) — seule une relance d'un Job FAILED "
                "est supportée."
            )

        if job.flow_type != JobFlowType.STUDENT_EVALUATION or job.submission_id is None:
            # ConflictError (409), pas NotImplementedError (builtin, aucun
            # exception_handler enregistré dans main.py -> 500 nu sinon).
            raise ConflictError(
                "Relance manuelle non encore supportée pour le flow "
                f"{job.flow_type.value} — seul STUDENT_EVALUATION l'est "
                "aujourd'hui (cf. docstring de ce service)."
            )

        submission = await self._submissions.get_by_id(job.submission_id)
        if submission is None:
            raise SubmissionNotFoundError(job.submission_id)

        process_submission_created.delay(
            submission_id=str(submission.id),
            exercise_id=str(submission.exercise_id),
            student_id=str(submission.student_id),
            attempt_number=submission.attempt_number,
            document_path=submission.document_path,
            mime_type=submission.document_mime_type,
        )

        return job
