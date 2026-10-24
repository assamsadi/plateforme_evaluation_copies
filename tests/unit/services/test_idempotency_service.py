from unittest.mock import AsyncMock, patch
import pytest
from sqlalchemy.exc import IntegrityError

from app.services.idempotency_service import IdempotencyService


@pytest.mark.anyio
async def test_idempotency_service_first_run():
    session = AsyncMock()
    service = IdempotencyService(session)

    with patch("app.services.idempotency_service.is_event_processed", return_value=False), \
         patch("app.services.idempotency_service.mark_event_processed", return_value=None):
        result = await service.try_mark_processed("event-100")

    assert result is True


@pytest.mark.anyio
async def test_idempotency_service_already_processed():
    session = AsyncMock()
    service = IdempotencyService(session)

    with patch("app.services.idempotency_service.is_event_processed", return_value=True):
        result = await service.try_mark_processed("event-100")

    assert result is False


@pytest.mark.anyio
async def test_idempotency_service_race_condition_integrity_error():
    session = AsyncMock()
    service = IdempotencyService(session)

    with patch("app.services.idempotency_service.is_event_processed", return_value=False), \
         patch("app.services.idempotency_service.mark_event_processed", side_effect=IntegrityError("stmt", {}, orig=Exception())):
        result = await service.try_mark_processed("event-race")

    assert result is False
    session.rollback.assert_called_once()
