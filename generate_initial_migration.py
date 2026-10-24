# generate_initial_migration.py — one-shot, à supprimer après usage
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.database import Base
import app.domain.models
import importlib, pkgutil

def _import_all_models():
    package = app.domain.models
    for _, name, is_pkg in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        importlib.import_module(name)

TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/evaluation_copies_test"

async def main():
    _import_all_models()
    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        # PAS de create_all ici — on laisse la base vide pour qu'Alembic
        # détecte qu'il faut TOUT créer
        await conn.execute(sa.text("DROP TABLE IF EXISTS alembic_version"))
    await engine.dispose()
    print("Base vidée (y compris alembic_version) — prête pour autogenerate.")

import sqlalchemy as sa
asyncio.run(main())