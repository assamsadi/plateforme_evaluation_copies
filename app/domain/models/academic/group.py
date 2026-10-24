"""
Group = la promo/classe (ex: "TD1", pour la filière Génie Civil, année 2025-2026).
Le label est unique PAR filière (deux filières différentes peuvent chacune
avoir un groupe "TD1"), d'où la contrainte d'unicité composite ci-dessous.
"""
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class Group(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("program_id", "label", name="uq_group_program_label"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("programs.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    academic_year: Mapped[str] = mapped_column(String(20), nullable=False)