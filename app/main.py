import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.kafka_client import close_producer
from app.core.logging_config import configure_logging
configure_logging(service="api")

from app.core.database import get_db_context
from app.core.langfuse_client import rebuild_langfuse_client
from app.domain.repositories.provider_credential_repository import SQLAlchemyProviderCredentialRepository
from app.observability.middleware import TraceIDMiddleware
from app.auth.router import router as auth_router
from app.api.v1.admin_router import router as admin_router
from app.api.v1.arbitration_router import router as arbitration_router
from app.api.v1.bareme_router import router as bareme_router
from app.api.v1.courses_router import router as courses_router
from app.api.v1.enrollments_router import router as enrollments_router
from app.api.v1.exercises_router import router as exercises_router
from app.api.v1.jobs_router import router as jobs_router
from app.api.v1.library_router import router as library_router
from app.api.v1.modules_router import router as modules_router
from app.api.v1.results_router import router as results_router
from app.api.v1.submissions_router import router as submissions_router
from app.api.v1.teacher_validation_router import router as teacher_validation_router
from app.api.v1.verification_router import router as verification_router

from app.consumers.submission_created_consumer import SubmissionCreatedConsumer


async def _rebuild_langfuse_from_effective_config() -> None:
    """
    Chantier "Configuration des modèles IA" (admin) — Langfuse n'est PAS
    câblé à chaud (contrairement aux clés API LLM, cf.
    app/model_registry/providers.py) : les valeurs effectives (surcharge
    DB si présente, sinon .env) ne sont lues qu'ICI, une seule fois au
    démarrage, décision actée. Best-effort : un échec DB ne doit jamais
    empêcher le serveur de démarrer — repli sur le client déjà construit
    à l'import (.env) en cas d'erreur.
    """
    import os

    from app.core.config import settings

    try:
        async with get_db_context() as db:
            rows = {r.key: r.value for r in await SQLAlchemyProviderCredentialRepository(db).get_all()}
    except Exception:
        return  # client .env déjà construit à l'import, aucune interruption du démarrage

    def effective(key: str, default_attr: str | None = None) -> str | None:
        if key in rows:
            return rows[key]
        return (getattr(settings, default_attr or key, None) or os.getenv(key))

    rebuild_langfuse_client(
        secret_key=effective("LANGFUSE_SECRET_KEY"),
        public_key=effective("LANGFUSE_PUBLIC_KEY"),
        base_url=effective("LANGFUSE_BASE_URL"),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _rebuild_langfuse_from_effective_config()

    # Démarrage des consumers Kafka en arrière-plan
    consumers = [
        SubmissionCreatedConsumer(),
    ]
    tasks = [asyncio.create_task(c.run()) for c in consumers]

    yield

    # Arrêt propre : annuler toutes les tâches de consumer
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await close_producer()


app = FastAPI(
    title="Plateforme Evaluation Copies API",
    description="API for the AI-powered educational assessment platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(TraceIDMiddleware)

# CORS (To be configured properly for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API v1 Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(arbitration_router, prefix="/api/v1")
app.include_router(bareme_router, prefix="/api/v1")
app.include_router(courses_router, prefix="/api/v1")
app.include_router(enrollments_router, prefix="/api/v1")
app.include_router(exercises_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(library_router, prefix="/api/v1")
app.include_router(modules_router, prefix="/api/v1")
app.include_router(results_router, prefix="/api/v1")
app.include_router(submissions_router, prefix="/api/v1")
app.include_router(teacher_validation_router, prefix="/api/v1")
app.include_router(verification_router, prefix="/api/v1")


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ForbiddenError)
async def forbidden_handler(request: Request, exc: ForbiddenError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_handler(request: Request, exc: ValidationError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ExternalServiceError)
async def external_service_handler(request: Request, exc: ExternalServiceError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
async def health_check():
    return {"status": "ok"}
