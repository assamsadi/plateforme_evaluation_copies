"""
Configuration centrale du logging : sortie JSON structurée sur stdout,
consommée par un collecteur OpenTelemetry / Promtail puis visualisée dans
Grafana + Loki (cf. infra/observability/).

Appelé une seule fois, au démarrage de chaque process :
    - app/main.py (API)
    - app/worker_main.py (worker Celery)

Le reste du code n'importe jamais ce module directement : il utilise
simplement `logging.getLogger(__name__)`, qui hérite automatiquement de
la configuration posée ici.

Le trace_id/thread_id n'est PAS encore injecté ici — ce sera ajouté quand
app/observability/tracing.py sera codé (dépendance pas encore stable).
"""
import contextvars
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

_trace_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def new_trace_id() -> str:
    return str(uuid.uuid4())


def set_trace_id(trace_id: str) -> contextvars.Token:
    return _trace_id_ctx_var.set(trace_id)


def reset_trace_id(token: contextvars.Token) -> None:
    _trace_id_ctx_var.reset(token)


def get_trace_id() -> str:
    return _trace_id_ctx_var.get()


class JsonFormatter(logging.Formatter):
    """
    Formatteur minimal, sans dépendance externe : transforme chaque
    LogRecord en une ligne JSON. Un champ manquant (ex. pas d'exception)
    est simplement absent de la ligne plutôt que null, pour rester léger.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        trace_id = get_trace_id()
        if trace_id:
            log_entry["trace_id"] = trace_id

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Permet d'ajouter des champs contextuels ad hoc via `extra=`, ex. :
        #   logger.info("Soumission créée", extra={"submission_id": "..."})
        reserved_keys = logging.LogRecord(
            "", 0, "", 0, "", None, None
        ).__dict__.keys()
        for key, value in record.__dict__.items():
            if key not in reserved_keys and key not in log_entry:
                log_entry[key] = value

        return json.dumps(log_entry, default=str)


def setup_logging() -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.LOG_LEVEL)

    # Évite les handlers dupliqués si setup_logging() est appelé plusieurs
    # fois par erreur (ex. import répété dans certains contextes de test).
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root_logger.addHandler(handler)

    # Bibliothèques tierces bruyantes : on baisse leur niveau pour ne pas
    # noyer les logs applicatifs (ajustable si besoin de débugger l'une
    # d'elles précisément).
    for noisy_logger in ("azure", "azure.core.pipeline.policies.http_logging_policy", "httpx"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def configure_logging(service: str) -> None:
    setup_logging()
    logging.info(f"Logging configured for service: {service}")