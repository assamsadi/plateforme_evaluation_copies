# reset_test_db.py
import asyncio
import importlib
import pkgutil

from sqlalchemy.ext.asyncio import create_async_engine
from app.core.database import Base
import app.domain.models

TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/evaluation_copies_test"


def _import_all_models():
    package = app.domain.models
    for _, name, is_pkg in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        importlib.import_module(name)


async def main():
    _import_all_models()
    print(f"Tables enregistrées sur Base.metadata : {len(Base.metadata.tables)}")

    engine = create_async_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Schéma de test recréé avec les nouveaux defaults.")


asyncio.run(main())