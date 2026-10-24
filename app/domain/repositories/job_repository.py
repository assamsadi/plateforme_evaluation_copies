"""
Repository Job — suit l'exécution du pipeline LangGraph (§2, §7).

create() valide la règle XOR (exercise_id rempli SI flow_type ==
EXERCISE_SETUP, submission_id rempli SI flow_type == STUDENT_EVALUATION,
jamais les deux ni aucun) — garde-fou en plus de la validation service,
défense en profondeur cohérente avec les autres repositories renforcés.

get_active_job_for_thread() : cohérent avec l'idempotence §7 — avant de
dispatcher une nouvelle tâche Celery pour un thread_id, on vérifie qu'un
Job actif (PENDING/RUNNING/RETRYING/INTERRUPTED) n'existe pas déjà,
évitant de relancer un pipeline en cours suite à un événement rejoué.
"""
import uuid
from typing import Any, Protocol

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.job import Job, JobFlowType, JobStatus

# Bug réel corrigé (2026-09-03, cas zainabsebhi) : update_status(current_node=
# None) était interprété comme "current_node non fourni, ne pas toucher" —
# indiscernable d'un appelant qui veut explicitement l'EFFACER (cf.
# job_sync.py::sync_job_after_graph_run, next_node=None quand le graph
# atteint END). Résultat : un Job entièrement terminé gardait pour toujours
# le nom du DERNIER nœud de pause traversé (ex. "await_student_verification_
# node"), jamais mis à jour pour refléter la fin réelle — trompeur sur les
# écrans de supervision admin (JobSupervisionService.get_overview). Sentinel
# dédié pour distinguer "non fourni" (mark_job_failed, qui doit préserver le
# current_node existant) de "explicitement None" (fin de graph réelle).
_UNSET: Any = object()
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)

_ACTIVE_STATUSES = (
    JobStatus.PENDING,
    JobStatus.RUNNING,
    JobStatus.RETRYING,
    JobStatus.INTERRUPTED,
)


class JobRepositoryProtocol(Protocol):
    async def get_by_id(self, job_id: uuid.UUID) -> Job | None: ...
    async def get_active_job_for_thread(self, thread_id: uuid.UUID) -> Job | None: ...
    async def get_latest_for_thread(self, thread_id: uuid.UUID) -> Job | None: ...
    async def create(
        self,
        flow_type: JobFlowType,
        exercise_id: uuid.UUID | None = None,
        submission_id: uuid.UUID | None = None,
    ) -> Job: ...
    async def update_status(
        self,
        job_id: uuid.UUID,
        status: JobStatus,
        current_node: str | None = _UNSET,
        error_message: str | None = None,
    ) -> Job | None: ...
    async def increment_llm_call_count(self, thread_id: uuid.UUID) -> Job | None: ...
    async def reset_llm_call_count(self, job_id: uuid.UUID) -> None: ...
    async def count_by_status(self) -> dict[str, int]: ...
    async def list_by_status(
        self, status: JobStatus, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[Job]: ...
    async def list_recent(self, limit: int = DEFAULT_PAGE_SIZE) -> list[Job]: ...


class SQLAlchemyJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, job_id: uuid.UUID) -> Job | None:
        return await self._session.get(Job, job_id)

    async def get_active_job_for_thread(self, thread_id: uuid.UUID) -> Job | None:
        """
        Bug pré-existant corrigé ici (découvert au câblage réel du graph,
        conversation) : Job n'a pas de colonne thread_id — le docstring du
        modèle (job.py) documente explicitement que exercise_id/submission_id
        EN TIENNENT LIEU, sans colonne séparée. Cette méthode interrogeait
        Job.thread_id, un attribut qui n'existe pas sur le modèle mappé :
        elle levait une AttributeError/InvalidRequestError à l'exécution,
        jamais exercée jusqu'ici faute d'appelant. Corrigé pour interroger
        exercise_id OU submission_id, cohérent avec create() ci-dessous.
        """
        result = await self._session.execute(
            select(Job).where(
                or_(Job.exercise_id == thread_id, Job.submission_id == thread_id),
                Job.status.in_(_ACTIVE_STATUSES),
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_for_thread(self, thread_id: uuid.UUID) -> Job | None:
        """
        Dernier Job pour ce thread, tout statut confondu (contrairement à
        get_active_job_for_thread, filtré aux statuts actifs) — nécessaire
        pour qu'un professeur voie l'issue d'un pipeline déjà terminé
        (COMPLETED/FAILED/CANCELLED), pas seulement un pipeline en cours.
        """
        result = await self._session.execute(
            select(Job)
            .where(or_(Job.exercise_id == thread_id, Job.submission_id == thread_id))
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        flow_type: JobFlowType,
        exercise_id: uuid.UUID | None = None,
        submission_id: uuid.UUID | None = None,
    ) -> Job:
        """
        Pas de paramètre thread_id séparé (retiré ici, cf. get_active_job_for_
        thread ci-dessus pour le même constat) : exercise_id/submission_id EN
        TIENNENT LIEU (docstring de Job) et suffisent à la validation XOR —
        un paramètre thread_id distinct n'aurait jamais pu être vérifié
        cohérent avec eux, et n'était de toute façon jamais transmis au
        constructeur ORM (Job n'a pas cette colonne).
        """
        has_exercise = exercise_id is not None
        has_submission = submission_id is not None

        if flow_type == JobFlowType.EXERCISE_SETUP:
            if not has_exercise or has_submission:
                raise ValueError(
                    "flow_type=EXERCISE_SETUP exige exercise_id seul (submission_id doit être None)"
                )
        elif flow_type == JobFlowType.STUDENT_EVALUATION:
            if not has_submission or has_exercise:
                raise ValueError(
                    "flow_type=STUDENT_EVALUATION exige submission_id seul (exercise_id doit être None)"
                )

        job = Job(
            flow_type=flow_type,
            exercise_id=exercise_id,
            submission_id=submission_id,
            status=JobStatus.PENDING,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def update_status(
        self,
        job_id: uuid.UUID,
        status: JobStatus,
        current_node: str | None = _UNSET,
        error_message: str | None = None,
    ) -> Job | None:
        job = await self.get_by_id(job_id)
        if job is None:
            return None
        job.status = status
        if current_node is not _UNSET:
            job.current_node = current_node
        if error_message is not None:
            job.error_message = error_message
        await self._session.flush()
        return job

    async def increment_llm_call_count(self, thread_id: uuid.UUID) -> Job | None:
        """
        Incrémenté par invoke_llm_with_fallback à CHAQUE tentative (succès
        ou échec, fallback inclus) — chaque tentative consomme réellement un
        appel fournisseur, qu'elle réussisse ou non.
        """
        job = await self.get_active_job_for_thread(thread_id)
        if job is None:
            return None
        job.llm_call_count += 1
        await self._session.flush()
        return job

    async def reset_llm_call_count(self, job_id: uuid.UUID) -> None:
        """
        Remis à zéro à CHAQUE run (démarrage frais : entry_router_node ;
        reprise : job_tasks.py::resume_thread) — jamais cumulatif à travers
        les reprises (décision actée).
        """
        job = await self.get_by_id(job_id)
        if job is None:
            return
        job.llm_call_count = 0
        await self._session.flush()

    async def count_by_status(self) -> dict[str, int]:
        """Câblage JobSupervisionService.get_overview — cf. UserRepository.count_by_role (même contrat, statuts absents complétés côté service)."""
        stmt = select(Job.status, func.count()).group_by(Job.status)
        result = await self._session.execute(stmt)
        return {status.value: count for status, count in result.all()}

    async def list_by_status(
        self, status: JobStatus, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE,
    ) -> CursorPage[Job]:
        """Jobs dans un état donné (ex. tous les INTERRUPTED) — supervision admin."""
        query = select(Job).where(Job.status == status)
        query = query.order_by(Job.created_at, Job.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Job.created_at, Job.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda j: (j.created_at, j.id))

    async def list_recent(self, limit: int = DEFAULT_PAGE_SIZE) -> list[Job]:
        """
        Activité récente toutes soumissions/exercices confondus — les plus
        RÉCEMMENT MIS À JOUR en premier (updated_at, pas created_at) : un job
        ancien mais qui vient de changer de statut est plus pertinent pour
        un admin qu'un job ancien resté immobile. Pas de pagination curseur
        (signature volontairement simple, ticket) — vue d'ensemble, pas un
        listing exhaustif.
        """
        query = select(Job).order_by(Job.updated_at.desc()).limit(limit)
        result = await self._session.execute(query)
        return list(result.scalars().all())