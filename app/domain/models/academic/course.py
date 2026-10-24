"""
Course = une instance d'enseignement d'un Module pour un groupe d'étudiants
sur un semestre donné, animée par un professeur spécifique.

Un Course relie :
- module_id      : la matière enseignée
- professor_user_id : le professeur responsable (FK → professors.id)
- group_id       : le groupe d'étudiants concerné
- semester       : libellé du semestre (ex: "S1-2025", "S2-2025-2026")

Contrainte métier : un seul cours par (module, group, semester) — un groupe
ne peut pas avoir deux cours de la même matière dans le même semestre.

L'objet Course est le contexte de publication des exercices de type
PUBLISHED_AS_EXAM / PUBLISHED_AS_HOMEWORK : Exercise.course_id référence ce
modèle, ce qui détermine quel groupe est attendu à soumettre.
"""
import uuid

from sqlalchemy import ForeignKey, Integer, Sequence, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class Course(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "courses"
    __table_args__ = (
        UniqueConstraint(
            "module_id", "group_id", "semester",
            name="uq_course_module_group_semester",
        ),
    )

    module_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )
    professor_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("groups.id"), nullable=False
    )
    semester: Mapped[str] = mapped_column(String(20), nullable=False)
    # Identifiant lisible séquentiel (audit "ids manquants") — cf. commentaire
    # Admin.admin_number pour le principe (séquence Postgres dédiée).
    course_number: Mapped[int] = mapped_column(
        Integer, Sequence("course_number_seq"), unique=True, nullable=False
    )
