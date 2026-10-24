"""
Consumer Kafka pour l'événement exercise-created.v1.
Dispatche la tâche Celery de traitement du document de référence professeur.
"""
from typing import Any

from app.core.kafka_client import BaseEventConsumer, KafkaTopic
from app.tasks.exercise_tasks import process_exercise_reference_document


class ExerciseCreatedConsumer(BaseEventConsumer):
    topic = KafkaTopic.EXERCISE_CREATED
    group_id = "exercise-created-consumer-group"

    async def handle(self, event_id: str, payload: dict[str, Any]) -> None:
        process_submission_path = payload.get("document_path")
        mime_type = payload.get("mime_type", "application/pdf")
        if process_submission_path:
            process_exercise_reference_document.delay(
                exercise_id=payload["exercise_id"],
                professor_id=payload["created_by_professor_id"],
                document_path=process_submission_path,
                mime_type=mime_type,
            )
