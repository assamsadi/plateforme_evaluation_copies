from app.core.logging_config import configure_logging
configure_logging(service="worker")

import app.observability.celery_tracing  # noqa: F401 — enregistre les signal handlers, import suffit

from celery.signals import worker_process_init

from app.core.broker import celery_app


@worker_process_init.connect
def _preload_embeddings_model(**kwargs) -> None:
    """
    Charge sentence-transformers/all-MiniLM-L6-v2 au démarrage de chaque
    worker fork, jamais paresseusement pendant une soumission.

    Bug réel constaté (2026-09-05) : le chargement à froid (~90s, téléchargement
    + poids) se produisait lors du premier appel réel à embed_text() — dans
    Question_Attachment_Agent, DANS la fenêtre chronométrée par
    QUESTION_ATTACHMENT_MAX_TIMEOUT_SECONDS (300s, cf. commentaire settings).
    Pour une petite soumission (10 blocs), ce warm-up à lui seul a suffi à
    déclencher un AttachmentTimeoutError, sans aucun rapport avec le nombre
    réel de blocs à traiter.
    """
    from app.core.embeddings import is_available  # noqa: PLC0415
    is_available()