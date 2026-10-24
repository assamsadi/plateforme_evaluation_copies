"""
Client Kafka (aiokafka) : bus d'événements entre l'API et le worker.

Rôle, pour ne pas le confondre avec broker.py (Celery) :
- Kafka  = TRANSPORT de l'événement, durable, rejouable (API -> consumers)
- Celery = EXÉCUTION du travail une fois l'événement reçu (queues, retry)

Flux type : l'API publie sur un topic (ex: submission-created.v1) ->
un consumer dédié (app/consumers/submission_created_consumer.py) le reçoit
-> il dispatche une tâche Celery sur la bonne queue -> commit manuel de
l'offset Kafka seulement APRÈS que la tâche a été correctement dispatchée.

Un topic par type d'événement, correspondant 1:1 aux schémas déjà définis
dans docs/event-schema/ (ex: submission-created.v1.json -> topic
"submission-created.v1").
"""
import json
import logging
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from app.core.config import settings
from app.core.database import get_db_context
from app.domain.repositories.processed_event_repository import (
    is_event_processed,
    mark_event_processed,
)

logger = logging.getLogger(__name__)


class KafkaTopic(StrEnum):
    """
    Un topic par événement métier, aligné sur docs/event-schema/.
    Centralisé ici pour éviter les strings en dur ailleurs dans le code.
    """
    EXERCISE_CREATED = "exercise-created.v1"
    EXERCISE_PUBLISHED = "exercise-published.v1"
    EXERCISE_ARCHIVED_TO_LIBRARY = "exercise-archived-to-library.v1"
    SUBMISSION_CREATED = "submission-created.v1"
    EXTRACTION_READY = "extraction-ready.v1"
    VARIANTS_READY = "variants-ready.v1"
    CORRECTION_TRIAGED = "correction-triaged.v1"
    ARBITRATION_REQUIRED = "arbitration-required.v1"
    EVALUATION_COMPLETED = "evaluation-completed.v1"
    FEEDBACK_RECORDED = "feedback-recorded.v1"
    RECOMMENDATION_GENERATED = "recommendation-generated.v1"
    NOTEBOOKLM_ENRICHMENT_COMPLETED = "notebooklm-enrichment-completed.v1"
    JOB_FAILED = "job-failed.v1"
    JOB_RESUMED = "job-resumed.v1"


def _json_serializer(value: dict[str, Any]) -> bytes:
    return json.dumps(value, default=str).encode("utf-8")


def _json_deserializer(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


# --- Producteur ---
# Une seule instance partagée par l'API (services qui publient des
# événements, ex: submission_service.py après création d'une soumission).

_producer: AIOKafkaProducer | None = None


async def get_producer() -> AIOKafkaProducer:
    """
    Correctif (chantier Recommendation_Agent, notification Kafka) —
    `_producer` ne doit JAMAIS être assigné avant qu'un `.start()` réussi
    ne le confirme : l'ancien code assignait `_producer = AIOKafkaProducer(...)`
    PUIS appelait `.start()` — si `.start()` échouait (broker indisponible),
    `_producer` restait posé sur une instance jamais démarrée, et tout appel
    SUIVANT dans le même process réutilisait cette instance cassée SANS
    retenter `.start()` (`_producer is None` devenait faux). send_and_wait()
    sur une instance jamais démarrée ne lève PAS d'exception — elle reste
    bloquée indéfiniment (reproduit empiriquement : le 2e appel de
    publish_event() dans un même process, broker down, ne se termine
    jamais). Fatal pour publish_notification_best_effort — dont toute la
    garantie ("Kafka ne bloque jamais le pipeline") dépend d'un échec
    RAPIDE, jamais d'un blocage. Correctif : `_producer` n'est assigné
    qu'APRÈS un `.start()` réussi ; un échec retente une instance fraîche
    au prochain appel, jamais la même instance cassée.
    """
    global _producer
    if _producer is None:
        producer = AIOKafkaProducer(
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=_json_serializer,
        )
        await producer.start()
        _producer = producer
    return _producer


async def publish_event(topic: KafkaTopic, event_id: str, payload: dict[str, Any]) -> None:
    """
    `event_id` doit être un UUID unique généré par l'appelant, réutilisé
    ensuite pour l'idempotence côté consumer (table ProcessedEvent).
    """
    producer = await get_producer()
    envelope = {"event_id": event_id, "payload": payload}
    await producer.send_and_wait(str(topic), envelope)
    logger.info("Événement publié", extra={"topic": str(topic), "event_id": event_id})


async def close_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


# --- Consumer de base ---
# Chaque consumer concret (app/consumers/*.py) hérite de cette classe et
# implémente seulement `handle()` : le boilerplate (idempotence, commit
# manuel, gestion d'erreur) est géré une seule fois, ici.

class BaseEventConsumer(ABC):
    topic: KafkaTopic
    group_id: str

    def __init__(self) -> None:
        self._consumer = AIOKafkaConsumer(
            str(self.topic),
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=self.group_id,
            value_deserializer=_json_deserializer,
            enable_auto_commit=False,  # commit manuel, après traitement réussi uniquement
            auto_offset_reset="earliest",
        )

    @abstractmethod
    async def handle(self, event_id: str, payload: dict[str, Any]) -> None:
        """À implémenter par chaque consumer concret : dispatch la tâche Celery adaptée."""
        raise NotImplementedError

    async def run(self) -> None:
        await self._consumer.start()
        logger.info("Consumer démarré", extra={"topic": str(self.topic), "group_id": self.group_id})
        try:
            async for message in self._consumer:
                envelope = message.value
                event_id = envelope["event_id"]
                payload = envelope["payload"]

                async with get_db_context() as db:
                    if await is_event_processed(db, event_id):
                        logger.info("Événement déjà traité, ignoré", extra={"event_id": event_id})
                        await self._consumer.commit()
                        continue

                try:
                    await self.handle(event_id, payload)
                    async with get_db_context() as db:
                        await mark_event_processed(db, event_id)
                    await self._consumer.commit()
                except Exception:
                    logger.exception(
                        "Échec de traitement, offset NON committé (sera retenté)",
                        extra={"event_id": event_id, "topic": str(self.topic)},
                    )
                    # Pas de commit : le message sera re-livré au prochain poll.
        finally:
            await self._consumer.stop()