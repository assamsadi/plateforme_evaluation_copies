"""
Root conftest.py — shared fixtures and database setup for integration & unit tests.

Uses the real PostgreSQL test database URL:
postgresql+asyncpg://postgres:postgres@localhost:5432/evaluation_copies_test

The test database is pre-created with all 36 tables / migrations applied.
Runs each integration test inside a transaction that rolls back at teardown for isolation.
"""
import sys
import types

# Neutralise Langfuse pour toute la session de test en remplaçant le module
# AVANT son premier import réel (singleton Langfuse(...) construit à l'import
# de app.core.langfuse_client, jamais recréé ensuite). Tenté d'abord via
# public_key/secret_key=None (Langfuse.__init__ retourne tôt en NoOpTracer) :
# insuffisant en pratique — un PromptCacheTaskManager (thread + atexit
# séparé du LangfuseResourceManager principal, cf. langfuse/_utils/
# prompt_cache.py) se construit quand même par un chemin interne au SDK non
# identifié avec certitude. Un stub de module via sys.modules est watertight
# : le fichier réel app/core/langfuse_client.py n'est alors JAMAIS exécuté,
# donc aucun objet Langfuse (thread, httpx.AsyncClient, atexit) n'existe.
# Corrige à la racine le httpx.AsyncClient jamais fermé de langfuse.async_api
# (audit fuite httpx.AsyncClient) et le "ValueError: I/O operation on closed
# file" au shutdown de l'interpréteur. Aucun test de ce projet ne dépend d'un
# Langfuse réel (vérifié : zéro test référence LANGFUSE_PUBLIC_KEY/SECRET_KEY) ;
# les tests qui veulent vérifier l'appel à AgentTraceSpan continuent de
# patcher app.observability.langfuse.langfuse explicitement, ce qui reste
# fonctionnel (patch() cible l'attribut du module appelant, indépendant de
# la façon dont il a été initialisé au départ).
_fake_langfuse_client_module = types.ModuleType("app.core.langfuse_client")
_fake_langfuse_client_module.langfuse = None
sys.modules["app.core.langfuse_client"] = _fake_langfuse_client_module

import uuid
import pytest
from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

# 1. Overwrite settings database url before importing database module
from app.core.config import settings
settings.DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/evaluation_copies_test"

# 2. Overwrite the database module attributes
import app.core.database
import app.domain.models  # noqa: F401
from app.domain.models.identity.user import Student, Professor, Admin, UserRole

# 3. Create the test engine with NullPool to prevent asyncpg connection contention
test_engine = create_async_engine(
    str(settings.DATABASE_URL),
    poolclass=NullPool,
    echo=False,
)
test_session_maker = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

app.core.database.engine = test_engine
app.core.database.async_session_maker = test_session_maker


# ── Database Session (Function Scope) ────────────────────────

@pytest.fixture
async def db_session():
    """
    Function-scoped session wrapping the test in a rollback transaction.
    This guarantees that database modifications do not persist across tests.
    """
    async with test_session_maker() as session:
        yield session
        await session.rollback()


# ── AnyIO Backend Fix ────────────────────────────────────────

@pytest.fixture
def anyio_backend():
    return "asyncio"


# ── Stable IDs ───────────────────────────────────────────────

@pytest.fixture
def student_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-4000-a000-000000000001")


@pytest.fixture
def professor_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-4000-a000-000000000002")


@pytest.fixture
def admin_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-4000-a000-000000000003")


# ── User Model Factories ────────────────────────────────────

@pytest.fixture
def fake_student(student_id) -> Student:
    """A realistic Student mock usable as auth dependency override."""
    student = MagicMock(spec=Student)
    student.id = student_id
    student.email = "alice.student@test.edu"
    student.role = UserRole.STUDENT
    student.first_name = "Alice"
    student.last_name = "Dupont"
    student.hashed_password = "hashed_pw"
    student.totp_enabled = False
    student.student_number = "STU20240001"
    student.group_id = None
    return student


@pytest.fixture
def fake_professor(professor_id) -> Professor:
    """A realistic Professor mock usable as auth dependency override."""
    prof = MagicMock(spec=Professor)
    prof.id = professor_id
    prof.email = "bob.prof@test.edu"
    prof.role = UserRole.PROFESSOR
    prof.first_name = "Bob"
    prof.last_name = "Martin"
    prof.hashed_password = "hashed_pw"
    prof.totp_enabled = False
    prof.department = "Informatique"
    prof.title = "Dr"
    prof.employee_number = "EMP001"
    return prof


@pytest.fixture
def fake_admin(admin_id) -> Admin:
    """A realistic Admin mock usable as auth dependency override."""
    admin = MagicMock(spec=Admin)
    admin.id = admin_id
    admin.email = "charlie.admin@test.edu"
    admin.role = UserRole.ADMIN
    admin.first_name = "Charlie"
    admin.last_name = "Bernard"
    admin.hashed_password = "hashed_pw"
    admin.totp_enabled = False
    return admin
