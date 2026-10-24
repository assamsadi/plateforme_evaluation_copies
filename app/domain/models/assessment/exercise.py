"""
Exercise = l'exercice ou l'examen complet créé par un professeur.

Cycle de vie (status) :
- DRAFT               : en cours de création, non visible des étudiants
- PUBLISHED_AS_EXAM    : deadline stricte, TOUTE la section (Course.group_id)
                         le passe simultanément, une seule soumission valide
- PUBLISHED_AS_HOMEWORK: deadline aussi, mais pas de contrainte de simultanéité
                         (l'étudiant peut le faire chez lui avant la deadline),
                         reste restreint au groupe du Course comme l'examen
- ARCHIVED_IN_LIBRARY  : accès libre à tout le module, peu importe le groupe,
                         tentatives multiples autorisées (attempt_number)

course_id est rempli pour EXAM et HOMEWORK (restreint à un groupe précis),
NULL pour DRAFT initial et ARCHIVED_IN_LIBRARY (accès module-large).
"""
import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as PgEnum, ForeignKey, Integer, Sequence, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.domain.models.assessment.exercise_section import ExerciseSection
    from app.domain.models.assessment.question import Question


class ExerciseStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED_AS_EXAM = "published_as_exam"
    PUBLISHED_AS_HOMEWORK = "published_as_homework"
    ARCHIVED_IN_LIBRARY = "archived_in_library"


class ExerciseDifficulty(StrEnum):
    """
    Difficulté de l'exercice EN TANT QU'ITEM DE PRATIQUE pour un étudiant —
    câblage Recommendation_Agent (clôture). Vocabulaire identique à
    SolutionVariant.VariantDifficulty (même mots FACILE/INTERMEDIAIRE/AVANCE)
    mais concept DISTINCT et sans rapport : VariantDifficulty qualifie la
    complexité d'UNE méthode de correction pour UNE question (Solution_
    Variant_Generation_Agent), pas la difficulté globale d'un exercice pour
    un étudiant qui le pratique — enum séparé délibérément, jamais réutilisé
    tel quel malgré la coïncidence de vocabulaire.
    """
    FACILE = "facile"
    INTERMEDIAIRE = "intermediaire"
    AVANCE = "avance"


class Exercise(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "exercises"

    module_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("courses.id"), nullable=True
    )
    created_by_professor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Identifiant lisible séquentiel (audit "ids manquants") — cf. commentaire
    # Admin.admin_number pour le principe (séquence Postgres dédiée) — title
    # est un texte libre, pas un identifiant stable pour retrouver un exercice.
    exercise_number: Mapped[int] = mapped_column(
        Integer, Sequence("exercise_number_seq"), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ExerciseStatus] = mapped_column(
        PgEnum(ExerciseStatus, name="exercise_status"),
        nullable=False,
        default=ExerciseStatus.DRAFT,
    )
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Câblage Recommendation_Agent (clôture) — NULL tant que l'exercice n'a
    # jamais été archivé en Library (DRAFT/EXAM/HOMEWORK n'en ont pas
    # besoin) ; obligatoire à ce moment précis, jamais deviné automatiquement
    # (cf. ExerciseService.publish, même principe de verrou que le barème/
    # la variante de référence pour EXAM/HOMEWORK).
    difficulty_level: Mapped[ExerciseDifficulty | None] = mapped_column(
        PgEnum(ExerciseDifficulty, name="exercise_difficulty"), nullable=True
    )
    # Note: module_name et professor_full_name sont positionnés dynamiquement en mémoire
    # par le service pour ExerciseRead, pas comme colonnes ORM.

    # Confirmation professeur explicite avant publication (audit "garanties
    # transverses", Plan B) — au-delà de la vérification technique de
    # complétude (_check_completeness). publication_confirmed_hash capture
    # le contenu confirmé (barème + variante de référence par question) :
    # toute modification après coup invalide automatiquement la
    # confirmation (publish() recalcule et compare), jamais une simple date.
    publication_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    publication_confirmed_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    sections: Mapped[list["ExerciseSection"]] = relationship(
        back_populates="exercise", order_by="ExerciseSection.order", cascade="all, delete-orphan"
    )
    questions: Mapped[list["Question"]] = relationship(
        back_populates="exercise", order_by="Question.order", cascade="all, delete-orphan"
    )