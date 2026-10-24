"""
Mixins réutilisés par TOUS les modèles du domaine, pour appliquer les
conventions transverses une seule fois (§ conventions validées) :
- clé primaire UUID (standard distribué, pas de collision entre services)
- timestamps created_at / updated_at automatiques

Usage :
    class Program(Base, UUIDPKMixin, TimestampMixin):
        __tablename__ = "programs"
        name: Mapped[str] = mapped_column(String(255), unique=True)
        ...
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        onupdate=func.clock_timestamp(),
        nullable=False,
    )


class CreatedAtOnlyMixin:
    """
    Pour les tables IMMUABLES par nature (journaux d'audit, événements
    traités) : uniquement created_at, pas de updated_at — une ligne qui
    ne devrait jamais être modifiée ne devrait pas prétendre pouvoir
    l'être via un champ updated_at.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    )