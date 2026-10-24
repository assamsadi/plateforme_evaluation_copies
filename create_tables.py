import asyncio
import importlib
import pkgutil
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.database import Base
import app.domain.models
def _import_all_models():
    package = app.domain.models
    for _, name, is_pkg in pkgutil.walk_packages(package.__path__, package.__name__ + '.'):
        importlib.import_module(name)
URL = 'postgresql+asyncpg://postgres:postgres@postgres:5432/evaluation_copies'
async def main():
    _import_all_models()
    engine = create_async_engine(URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print('Tables created!')
asyncio.run(main())
