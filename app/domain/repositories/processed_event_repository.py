"""
Repository ProcessedEvent — garantit l'idempotence des événements Kafka
(§7). Interface fonctionnelle (pas de classe Protocol/impl comme les
autres) car c'est EXACTEMENT ce que kafka_client.py::BaseEventConsumer.run()
attend déjà (import direct de is_event_processed/mark_event_processed,
pas d'injection de dépendance ici — le consumer Kafka n'a pas accès au
système DI de FastAPI).

Exception à la convention Protocol+Classe du reste de domain/repositories/,
assumée car ce module est appelé depuis un contexte structurellement
différent (consumer Kafka, pas une route FastAPI ni un service classique).
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.processed_event import ProcessedEvent


async def is_event_processed(session: AsyncSession, event_id: str) -> bool:
    from sqlalchemy import exists

    stmt = select(exists().where(ProcessedEvent.event_id == event_id))
    result = await session.execute(stmt)
    return bool(result.scalar())


async def mark_event_processed(session: AsyncSession, event_id: str) -> ProcessedEvent:
    """
    Peut lever une erreur d'intégrité (contrainte unique sur event_id) si
    appelée deux fois pour le même event_id en concurrence — c'est
    VOULU : le consumer doit alors traiter ça comme "déjà traité par un
    autre worker", pas comme une vraie erreur (cf. gestion attendue côté
    kafka_client.py : le except Exception catch large actuel devrait
    idéalement distinguer ce cas précis, à affiner au moment du service).
    """
    event = ProcessedEvent(event_id=event_id)
    session.add(event)
    await session.flush()
    return event