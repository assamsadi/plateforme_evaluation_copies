"""
Service Idempotency — wrapper autour de ProcessedEvent (§7).

Distinct de processed_event_repository.py : le repository expose deux
primitives DB brutes (is_event_processed / mark_event_processed) pensées
pour être importées DIRECTEMENT par kafka_client.py::BaseEventConsumer
(pas d'injection de dépendance possible dans un consumer Kafka).

Ce service, lui, encapsule la RÈGLE métier attendue par tout appelant
qui a accès au système DI (services classiques, tâches Celery
idempotentes par idempotency_key applicative plutôt que par event_id
Kafka) : "traiter deux fois le même identifiant ne doit jamais lever
d'erreur ni dupliquer le traitement — la deuxième tentative doit
simplement être un no-op silencieux".

mark_event_processed() peut lever IntegrityError en cas de concurrence
(deux workers traitent le même event_id en parallèle) — comme prévu
dans le docstring de processed_event_repository.py::mark_event_processed.
C'est ce cas précis qui est affiné ici : une IntegrityError sur cette
contrainte unique n'est PAS une vraie erreur, c'est le signal que
l'autre worker a gagné la course. On rollback et on traite ça comme un
succès (déjà traité), pas comme un échec à propager.
"""
import logging
from typing import Protocol

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.repositories.processed_event_repository import (
    is_event_processed,
    mark_event_processed,
)

logger = logging.getLogger(__name__)


class IdempotencyServiceProtocol(Protocol):
    async def is_already_processed(self, event_id: str) -> bool: ...
    async def try_mark_processed(self, event_id: str) -> bool: ...


class IdempotencyService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def is_already_processed(self, event_id: str) -> bool:
        return await is_event_processed(self._session, event_id)

    async def try_mark_processed(self, event_id: str) -> bool:
        """
        Tente de marquer `event_id` comme traité.

        Retourne True si CET appel est celui qui a effectivement marqué
        l'événement (premier traitement) ; False si l'événement était
        déjà marqué — que ce soit parce qu'il avait été traité avant cet
        appel, ou parce qu'un autre worker vient de gagner la course en
        concurrence (IntegrityError absorbée ici).

        L'appelant type :
            if not await idempotency.try_mark_processed(event_id):
                return  # déjà traité, no-op
            ... effectuer le traitement métier ...

        Note : ceci suppose le pattern "réserver puis exécuter". Si
        l'appelant a besoin du pattern inverse (exécuter puis marquer
        seulement en cas de succès, comme BaseEventConsumer), il doit
        utiliser is_already_processed() + mark_event_processed()
        séparément — c'est exactement ce que fait déjà kafka_client.py,
        qui n'a d'ailleurs pas besoin de ce service.
        """
        if await self.is_already_processed(event_id):
            return False

        try:
            await mark_event_processed(self._session, event_id)
            await self._session.flush()
        except IntegrityError:
            logger.info(
                "Événement déjà marqué traité par un autre worker (course gagnée ailleurs)",
                extra={"event_id": event_id},
            )
            await self._session.rollback()
            return False

        return True