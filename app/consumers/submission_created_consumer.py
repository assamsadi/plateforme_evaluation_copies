"""
Consumer Kafka pour l'événement submission-created.v1.
Dispatche la tâche Celery de traitement de soumission.
"""
from typing import Any

from app.core.kafka_client import BaseEventConsumer, KafkaTopic
from app.tasks.submission_tasks import process_submission_created


class SubmissionCreatedConsumer(BaseEventConsumer):
    topic = KafkaTopic.SUBMISSION_CREATED
    group_id = "submission-created-consumer-group"

    async def handle(self, event_id: str, payload: dict[str, Any]) -> None:
        process_submission_created.delay(
            submission_id=payload["submission_id"],
            exercise_id=payload["exercise_id"],
            student_id=payload["student_id"],
            attempt_number=payload["attempt_number"],
            document_path=payload["document_path"],
            mime_type=payload["mime_type"],
        )
