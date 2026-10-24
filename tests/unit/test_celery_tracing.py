# tests/unit/test_celery_tracing.py
def test_trace_id_survives_task_dispatch():
    from app.core.logging_config import set_trace_id, get_trace_id
    from app.core.broker import celery_app

    set_trace_id("test-trace-123")
    # .apply() exécute la tâche en synchrone (pas de vrai broker requis)
    # et vérifie que le trace_id restauré côté "worker" == celui posé côté "API"

    