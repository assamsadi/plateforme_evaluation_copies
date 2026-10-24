"""
Tests de SQLAlchemySystemConfigOverrideRepository — get_all/get_by_key/
upsert. Stockage/lecture générique (key/value), l'allowlist et le
typage/cast vivent côté service (app/services/system_config_service.py),
pas ici.
"""
import uuid

import pytest

from app.domain.repositories.system_config_override_repository import (
    SQLAlchemySystemConfigOverrideRepository,
)


@pytest.fixture
async def repo(db_session):
    return SQLAlchemySystemConfigOverrideRepository(db_session)


def _unique_key() -> str:
    return f"TEST_KEY_{uuid.uuid4().hex[:8]}"


@pytest.mark.anyio
class TestSystemConfigOverrideRepositoryUpsert:
    async def test_creates_new_row(self, repo):
        key = _unique_key()
        result = await repo.upsert(key=key, value="42")

        assert result.key == key
        assert result.value == "42"

    async def test_upsert_on_existing_key_updates_value(self, repo):
        key = _unique_key()
        await repo.upsert(key=key, value="42")

        updated = await repo.upsert(key=key, value="99")

        assert updated.value == "99"
        found = await repo.get_by_key(key)
        assert found.value == "99"


@pytest.mark.anyio
class TestSystemConfigOverrideRepositoryGetByKey:
    async def test_found(self, repo):
        key = _unique_key()
        await repo.upsert(key=key, value="0.5")

        found = await repo.get_by_key(key)

        assert found is not None
        assert found.value == "0.5"

    async def test_not_found_returns_none(self, repo):
        found = await repo.get_by_key(_unique_key())
        assert found is None


@pytest.mark.anyio
class TestSystemConfigOverrideRepositoryGetAll:
    async def test_reflects_upserted_rows_via_delta(self, repo):
        before = await repo.get_all()
        before_keys = {r.key for r in before}

        key = _unique_key()
        await repo.upsert(key=key, value="10")

        after = await repo.get_all()
        after_keys = {r.key for r in after}

        assert key in after_keys
        assert key not in before_keys
