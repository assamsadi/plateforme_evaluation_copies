"""
Synchronisation Job <-> résultat d'un run/reprise de graph — factorisé ici
pour éviter de tripler la même logique dans exercise_tasks.py,
submission_tasks.py et job_tasks.py::process_job_resumed (constaté en les
écrivant : les trois ont exactement le même besoin après un ainvoke()).

Job reste la ligne légère et requêtable pour l'observabilité (cf. diagnostic
pipeline_graph : "l'écran d'opération, pas l'état résumable" — le
checkpointer, lui, persiste l'état complet, jamais dupliqué ici) : ce module
ne fait que refléter dans Job ce que le graph vient de faire, jamais de
logique métier propre.
"""
import logging
import uuid

from app.core.database import engine, get_db_context
from app.domain.models.system_infrastructure.job import JobStatus
from app.domain.repositories.job_repository import SQLAlchemyJobRepository

logger = logging.getLogger(__name__)


async def sync_job_after_graph_run(thread_id: uuid.UUID, result: dict, next_node: str | None) -> None:
    """
    À appeler juste après tout ainvoke()/reprise sur pipeline_graph — result
    est le dict renvoyé par ainvoke(), next_node vient de
    graph.aget_state(config).next[0] (None si le run est allé jusqu'à END).
    """
    async with get_db_context() as db:
        job_repo = SQLAlchemyJobRepository(db)
        job = await job_repo.get_active_job_for_thread(thread_id)
        if job is None:
            # Bug réel corrigé (2026-09-06, test réel — reprise réussie après
            # un FAILED antérieur) : get_active_job_for_thread filtre aux
            # statuts actifs (cf. son docstring) — une fois qu'un Job est
            # passé FAILED (ex. bug depuis corrigé côté agent, reprise
            # relancée manuellement), il n'était plus JAMAIS retrouvé ici,
            # même quand cette reprise vient RÉELLEMENT de réussir (on
            # n'atteint ce point qu'après un ainvoke() qui a produit un
            # résultat, jamais après une exception). Le tableau de bord
            # affichait FAILED indéfiniment malgré une soumission notée avec
            # succès juste après. get_latest_for_thread (tout statut
            # confondu) reflète la réalité du graph, source de vérité — Job
            # n'est qu'un écran d'observabilité, jamais lui-même autoritaire.
            job = await job_repo.get_latest_for_thread(thread_id)
            if job is None:
                logger.warning(
                    "Aucun Job (même terminal) trouvé pour thread_id=%s — rien à synchroniser",
                    thread_id,
                )
                return

        if "__interrupt__" in result:
            await job_repo.update_status(job.id, JobStatus.INTERRUPTED, current_node=next_node)
        else:
            await job_repo.update_status(job.id, JobStatus.COMPLETED, current_node=next_node)


async def mark_job_failed(thread_id: uuid.UUID, error_message: str) -> None:
    """
    Seul point d'écriture de JobStatus.FAILED — jusqu'ici inexistant (bug
    constaté en session : un Job resté bloqué à RUNNING indéfiniment après
    qu'un run ait épuisé tous les retries Celery sur un 429 provider, aucun
    code n'écrivant jamais FAILED malgré le statut prévu dans l'énumération).
    Deux appelants : les branches "except ... return" de exercise_tasks.py/
    submission_tasks.py (erreur connue, terminale, jamais retentée) et le
    on_failure() Celery de chaque tâche (erreur inconnue, après épuisement
    réel des retries — jamais à chaque tentative individuelle, qui resterait
    RUNNING le temps du backoff, ce qui est correct).

    dispose() par précaution : appelé depuis on_failure(), un contexte hors
    de la boucle asyncio de _run() (déjà fermée à ce stade) — même piège que
    documenté dans exercise_tasks.py::_run (connexion pool liée à une boucle
    fermée). Sans effet si le pool est déjà vide.
    """
    await engine.dispose()
    async with get_db_context() as db:
        job_repo = SQLAlchemyJobRepository(db)
        job = await job_repo.get_active_job_for_thread(thread_id)
        if job is None:
            logger.warning("Aucun Job actif trouvé pour thread_id=%s — rien à marquer FAILED", thread_id)
            return
        await job_repo.update_status(job.id, JobStatus.FAILED, error_message=error_message)
