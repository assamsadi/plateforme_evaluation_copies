"""
Propagation du trace_id à travers les tâches Celery.

Principe : le trace_id est généré côté API (TraceIDMiddleware) et NE
DOIT JAMAIS être régénéré côté worker — sinon on perd la corrélation
entre la requête HTTP qui a déclenché le traitement et les logs du
pipeline LangGraph qui s'exécute en tâche de fond.

Mécanisme :
- `before_task_publish` : au moment où une tâche est mise en file
  (`.delay()` / `.apply_async()`), on injecte le trace_id courant dans
  les headers du message Celery.
- `task_prerun` / `task_postrun` : côté worker, on restaure ce trace_id
  dans le contexte de logging avant exécution, et on le nettoie après.

À importer une seule fois au démarrage du worker (`worker_main.py`),
juste après `configure_logging(service="worker")` — l'import suffit,
les handlers s'enregistrent via les décorateurs `@signals.*.connect`.
"""
import logging

from celery import signals
from celery.app.task import Context

from app.core.logging_config import (
    get_trace_id,
    new_trace_id,
    reset_trace_id,
    set_trace_id,
)

logger = logging.getLogger(__name__)

_TRACE_ID_HEADER = "trace_id"

# Un token de contextvar par tâche en cours d'exécution dans ce worker
# process, indexé par task_id, pour pouvoir restaurer l'état précédent
# à la fin de la tâche (task_postrun), même en cas d'exécutions
# imbriquées ou concurrentes (worker_prefetch_multiplier=1 limite le
# risque, mais on reste défensif).
_active_tokens: dict[str, object] = {}


@signals.before_task_publish.connect
def _inject_trace_id_on_publish(headers: dict | None = None, **_kwargs) -> None:
    """Attache le trace_id courant aux headers du message Celery, au
    moment de la publication de la tâche (côté API, ou côté worker
    s'il chaîne une tâche vers une autre queue)."""
    if headers is None:
        return
    headers[_TRACE_ID_HEADER] = get_trace_id() or new_trace_id()


@signals.task_prerun.connect
def _restore_trace_id_before_run(task_id: str = "", task=None, **_kwargs) -> None:
    """Restaure le trace_id transmis dans les headers, côté worker,
    avant que le corps de la tâche ne s'exécute."""
    trace_id = None
    request: Context | None = getattr(task, "request", None) if task else None
    if request is not None:
        trace_id = request.get(_TRACE_ID_HEADER) if hasattr(request, "get") else getattr(
            request, _TRACE_ID_HEADER, None
        )

    token = set_trace_id(trace_id or new_trace_id())
    _active_tokens[task_id] = token


@signals.task_postrun.connect
def _clear_trace_id_after_run(task_id: str = "", **_kwargs) -> None:
    """Nettoie le contexte à la fin de la tâche, pour ne pas polluer la
    tâche suivante exécutée par le même worker process."""
    token = _active_tokens.pop(task_id, None)
    if token is not None:
        reset_trace_id(token)
    else:
        logger.warning(
            "trace_id_token_missing_on_postrun", extra={"task_id": task_id}
        )
