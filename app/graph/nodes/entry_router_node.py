"""
Nœud LangGraph — entry_router_node.

Premier nœud exécuté pour chaque run, avant le branchement conditionnel sur
flow_type (routing.py::route_from_entry, câblé depuis ce nœud dans
pipeline_graph.py). Pas un simple aiguillage : fait le travail réel de
suivi d'exécution que le modèle Job (app/domain/models/system_infrastructure/
job.py) existait déjà pour porter, jusqu'ici jamais utilisé — aucun
appelant avant ce câblage (cf. diagnostic). Le nom du fichier ("router")
reflète son rôle dans le graph (juste avant la edge de branchement), pas le
contenu du nœud lui-même (aucune décision de routage ici — cf. séparation
déjà appliquée par les autres nœuds : un nœud calcule/persiste, une edge
route).

Réutilise un Job déjà actif pour ce thread_id (get_active_job_for_thread)
plutôt que d'en créer un nouveau à chaque retry Celery/rejeu — cohérent
avec le docstring de job_repository.py (idempotence §7).

Remet aussi llm_call_count à 0 (audit "garanties transverses", Plan D) :
ce nœud ne s'exécute JAMAIS lors d'une reprise via Command(resume=...) —
le checkpoint reprend après lui — seulement au tout premier ainvoke() d'un
thread ou à un retry Celery avant la première pause. La reprise a son
propre reset symétrique dans job_tasks.py::resume_thread — à eux deux, ils
couvrent tous les points d'entrée réels de graph.ainvoke().
"""
import uuid
from datetime import datetime, timezone

from app.core.database import get_db_context
from app.domain.models.system_infrastructure.job import JobFlowType, JobStatus
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.graph.state import PipelineState


async def entry_router_node(state: PipelineState) -> PipelineState:
    thread_id = uuid.UUID(state.thread_id)
    flow_type = JobFlowType(state.flow_type)

    async with get_db_context() as db:
        job_repo = SQLAlchemyJobRepository(db)
        job = await job_repo.get_active_job_for_thread(thread_id)
        if job is None:
            job = await job_repo.create(
                flow_type=flow_type,
                exercise_id=thread_id if flow_type == JobFlowType.EXERCISE_SETUP else None,
                submission_id=thread_id if flow_type == JobFlowType.STUDENT_EVALUATION else None,
            )
        await job_repo.update_status(job.id, JobStatus.RUNNING, current_node="entry_router_node")
        await job_repo.reset_llm_call_count(job.id)

    state.status = "RUNNING"
    state.updated_at = datetime.now(timezone.utc)
    return state
