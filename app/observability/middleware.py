"""
Middleware FastAPI : pose un trace_id par requête HTTP, le propage dans
le contexte de logging (contextvars), le renvoie dans la réponse, et
logue une ligne structurée par requête (méthode, path, statut, durée).

Contrat : si le client (ou un service amont) fournit déjà un
X-Trace-Id, on le réutilise (permet de chaîner plusieurs services sans
perdre la corrélation) ; sinon on en génère un nouveau.
"""
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging_config import new_trace_id, reset_trace_id, set_trace_id

logger = logging.getLogger("app.observability.http")

TRACE_ID_HEADER = "X-Trace-Id"


class TraceIDMiddleware(BaseHTTPMiddleware):
    """À enregistrer en tout premier dans `app.add_middleware(...)` côté
    main.py, pour que le trace_id soit disponible dès le début de la
    requête (y compris pour les middlewares suivants et les handlers
    d'exception)."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        trace_id = request.headers.get(TRACE_ID_HEADER) or new_trace_id()
        token = set_trace_id(trace_id)
        start = time.perf_counter()

        try:
            try:
                response = await call_next(request)
            except Exception:
                # Le trace_id est encore dans le contexte ici : cette ligne
                # apparaît bien corrélée avec les logs applicatifs de la
                # même requête, avant que le contexte ne soit nettoyé.
                logger.exception(
                    "unhandled_exception",
                    extra={"method": request.method, "path": request.url.path},
                )
                # Ne JAMAIS relancer ici : BaseHTTPMiddleware relaie la
                # réponse via un stream interne (portal/task group) — une
                # exception qui remonte à travers ce mécanisme au lieu d'un
                # objet Response casse la livraison de la réponse au client
                # (constaté : uvicorn logue "500" dans son access log, puis
                # une seconde "Exception in ASGI application" juste après —
                # la connexion est réinitialisée avant que les octets du
                # 500 n'atteignent le client, qui voit un échec réseau brut
                # ("Failed to fetch" côté navigateur) au lieu du message
                # d'erreur). Construire la réponse ICI, dans le except,
                # évite complètement cette traversée.
                response = JSONResponse(
                    status_code=500,
                    content={"detail": "Erreur interne du serveur."},
                )

            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            response.headers[TRACE_ID_HEADER] = trace_id
            logger.info(
                "http_request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            reset_trace_id(token)