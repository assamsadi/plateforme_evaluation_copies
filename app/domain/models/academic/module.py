"""
Module = la matière (ex: "Analyse Numérique"). Axe qui détermine l'accès
en lecture/soumission des étudiants (§5 du résumé d'architecture) : un
étudiant inscrit (Enrollment) à un module accède à toute sa Library,
peu importe quel professeur a créé quel exercice.
"""
import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class Module(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "modules"
    __table_args__ = (
        UniqueConstraint("program_id", "name", name="uq_module_program_name"),
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("programs.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)