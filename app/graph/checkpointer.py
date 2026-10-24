"""
Checkpointer LangGraph — Postgres, pas Redis.

Argument (détaillé en conversation lors du diagnostic pipeline_graph) :
Redis n'est utilisé nulle part ailleurs dans ce projet comme source de
vérité durable — seulement comme broker/result backend Celery, éphémère
par nature (app/core/broker.py). Un thread en pause HITL (structuration
incomplète, clarification BLOCKING, arbitrage professeur) peut rester
interrompu plusieurs jours ; le perdre à une éviction/redémarrage Redis
serait silencieux. Postgres est déjà le système de vérité unique pour
tout le reste du projet (Bareme, ReasoningStep, AgentDecisionLog,
ReasoningClarificationRequest, Job...) — réutiliser la même DB garde
cette propriété plutôt que d'introduire une deuxième source d'état
durable à sauvegarder/surveiller séparément.

AsyncPostgresSaver (langgraph-checkpoint-postgres) utilise psycopg,
jamais asyncpg comme le reste du projet (app/core/database.py) — c'est
la seule bibliothèque supportée par ce package, pas un choix technique
fait ici. settings.DATABASE_URL est au format asyncpg
("postgresql+asyncpg://...") : converti en chaîne psycopg standard
("postgresql://...") avant usage, jamais réutilisé tel quel. Deux
clients Postgres distincts cohabitent donc (SQLAlchemy/asyncpg pour
l'ORM métier, psycopg pour les checkpoints LangGraph) — pas de partage
de connexion/pool entre les deux.
"""
import asyncio
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import settings

# psycopg (mode async) refuse explicitement de tourner sur la ProactorEventLoop
# par défaut d'asyncio.run() sous Windows (psycopg.InterfaceError à la
# connexion) — sans objet en production (Linux), mais bloquant en dev/tests
# locaux sous Windows sans ce correctif. No-op sur toute autre plateforme.
# API dépréciée (retrait prévu 3.16) faute d'alternative asyncio actuelle ;
# à revisiter si psycopg lève un jour cette restriction ou si asyncio propose
# un remplacement non déprécié.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _psycopg_connection_string() -> str:
    """
    Seule la partie schéma diffère entre le DSN asyncpg de settings.DATABASE_URL
    et ce qu'attend psycopg — user/pass/host/port/db sont identiques, donc un
    simple remplacement de préfixe suffit, jamais une reconstruction du DSN.
    """
    return str(settings.DATABASE_URL).replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def get_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """
    Context manager ouvrant un pool psycopg dédié au checkpointer pour la
    durée du bloc — à utiliser autour d'un run de graph (compile puis
    invoke), jamais gardé ouvert entre deux runs indépendants.
    """
    async with AsyncPostgresSaver.from_conn_string(_psycopg_connection_string()) as checkpointer:
        yield checkpointer


async def setup_checkpointer_tables() -> None:
    """
    Crée les tables de checkpoint (checkpoints, checkpoint_blobs,
    checkpoint_writes, checkpoint_migrations) si absentes — idempotent
    (IF NOT EXISTS côté langgraph-checkpoint-postgres). À appeler une fois
    au démarrage de l'application (cf. app/main.py lifespan), jamais à
    chaque requête/tâche — équivalent applicatif d'une migration Alembic,
    mais géré par le package LangGraph lui-même, pas par nos migrations.
    """
    async with get_checkpointer() as checkpointer:
        await checkpointer.setup()
