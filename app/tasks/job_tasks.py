"""
Reprise d'un thread LangGraph en pause (mécanisme générique, pas spécifique
à Contestation_Verification_Agent, même s'il en est le premier appelant,
cf. contestation_tasks.py).

Stub d'origine (job_id, thread_id, current_node) jamais câblé — signature
revue ici : resume_value explicite plutôt qu'implicite depuis current_node
(aucun contrat d'événement job-resumed.v1 n'existait, cf. docs/event-schema/
job-resumed.v1.json vide constaté au diagnostic — rien à respecter, à
concevoir).

IMPORTANT (cf. await_student_verification_node.py pour le détail) :
resume_value ne doit JAMAIS être un dict — Command.resume interprète tout
dict comme "mapping id_interrupt -> valeur", jamais comme "une valeur qui
se trouve être un dict", donc un dict (même non vide) ne résout rien : le
thread se re-interrompt à l'identique, silencieusement, sans erreur.

resume_thread() est une fonction async NUE (pas le corps d'un asyncio.run()) —
séparée de la tâche Celery process_job_resumed pour une raison concrète,
pas stylistique : constaté en écrivant contestation_tasks.py, appeler
process_job_resumed(...) directement depuis LÀ (déjà dans un asyncio.run()
propre à process_contestation_verification) lève "asyncio.run() cannot be
called from a running event loop" — deux asyncio.run() ne s'imbriquent
jamais, même via deux tâches Celery différentes. Un appelant déjà async
(contestation_tasks.py) doit `await resume_thread(...)` directement ; un
appelant sync (déclenchement Celery indépendant, ex. futur endpoint "je
confirme ma copie") passe par process_job_resumed.delay(...) / l'appel
direct de la tâche, qui fait l'asyncio.run() lui-même.
"""
import asyncio
import logging
import uuid

from langgraph.types import Command

from app.core.broker import celery_app, CeleryQueue, DEFAULT_RETRY_POLICY
from app.core.database import engine, get_db_context
from app.infra_services.storage_service import storage_service
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.graph.checkpointer import get_checkpointer
from app.graph.job_sync import mark_job_failed, sync_job_after_graph_run
from app.graph.pipeline_graph import compile_pipeline_graph
from app.observability.langfuse import AgentTraceSpan

logger = logging.getLogger(__name__)


class _FailureTrackingTask(celery_app.Task):
    """cf. app/tasks/exercise_tasks.py::_FailureTrackingTask — même correctif, même bug."""
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        thread_id = kwargs.get("thread_id")
        if thread_id:
            asyncio.run(mark_job_failed(uuid.UUID(thread_id), str(exc)))


async def resume_thread(thread_id: str, resume_value: str) -> None:
    """
    Reprend le thread LangGraph identifié par thread_id (exercise_id ou
    submission_id selon le flow) au point exact où il a été interrompu par
    interrupt() — jamais une relance depuis l'état initial (c'est tout
    l'intérêt du checkpointer, cf. checkpointer.py).
    """
    logger.info("Reprise du thread %s (resume_value=%s)", thread_id, resume_value)

    # cf. app/tasks/exercise_tasks.py::_run pour le détail — `engine` (pool
    # asyncpg) doit être disposé avant tout usage dans une NOUVELLE boucle
    # asyncio. Placé ICI (pas dans process_job_resumed) car resume_thread a
    # deux appelants : un asyncio.run() frais (process_job_resumed) ET un
    # `await` direct depuis une boucle déjà active et déjà disposée
    # (contestation_tasks.py) — dispose() ne casse rien dans ce second cas
    # (ne ferme que les connexions IDLE du pool, jamais une déjà en cours
    # d'usage), donc sûr dans les deux appels.
    #
    # Bug réel corrigé (2026-09-04, test réel examen C2PCT à 3 exercices) :
    # dans un worker Celery long-lived (prefork réutilisé sur des dizaines de
    # tâches), le pool peut contenir des connexions asyncpg IDLE ouvertes par
    # un `asyncio.run()` PRÉCÉDENT déjà terminé (sa boucle est fermée pour de
    # bon, contrairement au cas "déjà active" documenté ci-dessus). dispose()
    # essaie alors de fermer proprement ces connexions, ce qui nécessite de
    # parler à leur boucle d'origine — RuntimeError("Event loop is closed")
    # / "attached to a different loop". Constaté en usage réel : bloquait
    # indéfiniment toute reprise de pipeline après la PREMIÈRE tâche Celery
    # exécutée dans ce worker. Ces connexions sont de toute façon
    # définitivement inutilisables (leur boucle n'existe plus) — les ignorer
    # ici est sans risque, un nouveau checkout du pool ouvrira simplement une
    # connexion fraîche sous la boucle courante.
    try:
        await engine.dispose()
    except RuntimeError as exc:
        logger.warning(
            "engine.dispose() a échoué en tentant de fermer des connexions "
            "d'une boucle asyncio précédente déjà fermée — ignoré, sans "
            "risque (connexions de toute façon inutilisables) : %r", exc,
        )
    # cf. app/tasks/exercise_tasks.py::_run — même correctif pour le
    # deuxième singleton process-wide, storage_service (client Azure Blob).
    # Même risque de connexion orpheline qu'engine.dispose() ci-dessus, même
    # traitement défensif.
    try:
        await storage_service.close()
    except RuntimeError as exc:
        logger.warning(
            "storage_service.close() a échoué en tentant de fermer une "
            "connexion d'une boucle asyncio précédente déjà fermée — "
            "ignoré, sans risque : %r", exc,
        )

    # llm_call_count remis à 0 pour CETTE reprise (audit "garanties
    # transverses", Plan D) — entry_router_node ne se réexécute jamais sur
    # une reprise (le checkpoint reprend après lui), donc symétrique
    # nécessaire ici pour couvrir ce point d'entrée précis de
    # graph.ainvoke(). Jamais cumulatif à travers les reprises (décision
    # actée) : chaque reprise repart avec un budget plein.
    async with get_db_context() as db:
        job_repo = SQLAlchemyJobRepository(db)
        job = await job_repo.get_active_job_for_thread(uuid.UUID(thread_id))
        if job is not None:
            await job_repo.reset_llm_call_count(job.id)

    config = {"configurable": {"thread_id": thread_id}}
    # Span racine englobant cette reprise — même correctif que exercise_
    # tasks.py/submission_tasks.py (cf. mémoire de session). Une reprise
    # démarre nécessairement dans un NOUVEAU process/contexte Celery (aucun
    # span de la portion pré-pause n'est plus actif ici) : elle devient donc
    # intentionnellement sa propre trace distincte, mais au moins tous les
    # nœuds/agents exécutés DANS cette reprise s'imbriquent correctement
    # ensemble plutôt que chacun sa propre racine.
    with AgentTraceSpan(
        "pipeline_resume", trace_id=thread_id, metadata={"thread_id": thread_id},
    ) as pipeline_span:
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            result = await graph.ainvoke(Command(resume=resume_value), config=config)
            state_snapshot = await graph.aget_state(config)
        pipeline_span.record_metrics(
            interrupted="__interrupt__" in result,
            next_node=state_snapshot.next[0] if state_snapshot.next else None,
        )

    next_node = state_snapshot.next[0] if state_snapshot.next else None
    await sync_job_after_graph_run(uuid.UUID(thread_id), result, next_node)

    if "__interrupt__" in result:
        logger.info(
            "Thread %s de nouveau en pause après reprise, nœud=%s (%s)",
            thread_id, next_node, result["__interrupt__"][0].value.get("reason"),
        )
    else:
        logger.info("Thread %s repris jusqu'à la fin du graph.", thread_id)


@celery_app.task(
    bind=True,
    base=_FailureTrackingTask,
    queue=CeleryQueue.MAINTENANCE,
    autoretry_for=(Exception,),
    # cf. submission_tasks.py::process_submission_created pour le détail du
    # bug réel corrigé — une reprise peut réexécuter n'importe quel nœud en
    # aval (les deux flows confondus, jamais su à l'avance lequel), seuil
    # aligné sur le plus long des deux (exercise_setup).
    soft_time_limit=2700,
    time_limit=2760,
    **DEFAULT_RETRY_POLICY,
)
def process_job_resumed(self, thread_id: str, resume_value: str) -> None:
    """Point d'entrée Celery — réservé aux appelants SYNCHRONES (jamais depuis une coroutine déjà en cours, cf. resume_thread())."""
    asyncio.run(resume_thread(thread_id, resume_value))
