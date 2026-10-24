import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.repositories.processed_event_repository import (
    is_event_processed,
    mark_event_processed,
)


@pytest.mark.anyio
async def test_processed_event_idempotency_workflow(db_session):
    # event_id column is VARCHAR(36) — use a bare UUID (exactly 36 chars)
    event_id = str(uuid.uuid4())

    # Initially event should not be processed
    assert not await is_event_processed(db_session, event_id)

    # Mark as processed
    processed_evt = await mark_event_processed(db_session, event_id)
    assert processed_evt.event_id == event_id

    # Now it should report as processed
    assert await is_event_processed(db_session, event_id)


@pytest.mark.anyio
async def test_duplicate_event_raises_integrity_error(db_session):
    # event_id column is VARCHAR(36) — use a bare UUID (exactly 36 chars)
    event_id = str(uuid.uuid4())

    await mark_event_processed(db_session, event_id)

    # Calling mark_event_processed again with same event_id in same transaction must raise IntegrityError
    async with db_session.begin_nested():
        with pytest.raises(IntegrityError):
            await mark_event_processed(db_session, event_id)
