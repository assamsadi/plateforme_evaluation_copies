"""
Tests unitaires pour SubmissionCreatedConsumer.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.consumers.submission_created_consumer import SubmissionCreatedConsumer


@pytest.mark.anyio
async def test_submission_created_consumer_dispatches_celery_task():
    consumer = SubmissionCreatedConsumer()
    payload = {
        "submission_id": str(uuid.uuid4()),
        "exercise_id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "attempt_number": 1,
        "document_path": "submissions/x/original.pdf",
        "mime_type": "application/pdf",
    }

    with patch("app.consumers.submission_created_consumer.process_submission_created") as mock_task:
        mock_task.delay = MagicMock()
        await consumer.handle(event_id=str(uuid.uuid4()), payload=payload)

        mock_task.delay.assert_called_once_with(
            submission_id=payload["submission_id"],
            exercise_id=payload["exercise_id"],
            student_id=payload["student_id"],
            attempt_number=payload["attempt_number"],
            document_path=payload["document_path"],
            mime_type=payload["mime_type"],
        )
