"""
ProcessedEvent = garde une trace de chaque event_id Kafka déjà traité
(§7 du résumé : idempotence, un événement rejoué ne doit jamais dupliquer
un traitement déjà fait). Utilisé par BaseEventConsumer.run() dans
app/core/kafka_client.py, via is_event_processed()/mark_event_processed()
(à écrire dans domain/repositories/processed_event_repository.py).

created_at (hérité de CreatedAtOnlyMixin) sert directement de "processed_at" —
pas de colonne séparée nécessaire. Table immuable : pas de updated_at,
une ligne "événement traité" ne devrait jamais changer après coup.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import CreatedAtOnlyMixin, UUIDPKMixin


class ProcessedEvent(Base, UUIDPKMixin, CreatedAtOnlyMixin):
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)