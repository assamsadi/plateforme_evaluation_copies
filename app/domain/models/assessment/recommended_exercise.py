"""
RecommendedExercise = exercice de remédiation recommandé, puisé dans la
Library (ARCHIVED_IN_LIBRARY) du module de l'étudiant (§5, Fonction 8).
reason + relevance_score : explicabilité de la recommandation, cohérent
avec le critère de transparence du document CHAABI (§6.1).

Câblage Recommendation_Agent — schéma étendu depuis la version CRUD
d'origine (table confirmée vide au moment de ce changement, aucune perte
de donnée) :
- student_id/module_id directs (jamais uniquement via submission_id ->
  Submission.student_id) : même pattern que StudentCompetencyObservation
  — une recommandation dérive de l'historique agrégé de compétence
  (Niveau 3), pas du contenu d'UNE soumission précise.
- submission_id devient nullable : reste rempli quand une soumission a
  déclenché la (re)génération, mais n'est plus la clé d'accès structurelle
  (jamais "causée par son contenu", juste "générée à l'occasion de").
- competency_code : la compétence ciblée par cette recommandation — sans
  elle, aucune requête "pourquoi cet exercice" n'est possible.
- category : REMEDIATION (mastery_level bas) vs VERIFICATION (mastery_level
  élevé mais confidence_level bas — jamais traité comme acquis, cf.
  Recommendation_Agent).
- status : ACTIVE/SUPERSEDED — corrige list_active_by_student() qui, avant
  ce champ, ne filtrait RIEN malgré son nom (accumulation infinie à chaque
  nouvelle soumission notée). Une nouvelle génération pour le même
  (student, module, competency) supersède les anciennes ACTIVE plutôt que
  de les laisser s'empiler indéfiniment.
"""
import uuid
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class RecommendationCategory(StrEnum):
    """Distingue les deux cas métier de Recommendation_Agent — jamais fusionnés (sémantique différente pour l'étudiant)."""
    REMEDIATION = "remediation"
    VERIFICATION = "verification"


class RecommendationStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class RecommendedExercise(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "recommended_exercises"

    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )
    competency_code: Mapped[C2PCTSkillCode] = mapped_column(
        PgEnum(C2PCTSkillCode, name="c2pct_skill_code"), nullable=False
    )
    category: Mapped[RecommendationCategory] = mapped_column(
        PgEnum(
            RecommendationCategory, name="recommendation_category",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
    )
    status: Mapped[RecommendationStatus] = mapped_column(
        PgEnum(
            RecommendationStatus, name="recommendation_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=RecommendationStatus.ACTIVE,
    )
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("exercises.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    relevance_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    # Câblage NotebookLM (§7, Partie 2/2) — rattaché APRÈS coup par la tâche
    # Celery de création du notebook (StudentNotebook créé de façon
    # asynchrone, best-effort, après que cette ligne existe déjà — cf.
    # RecommendedExerciseRepository.link_to_notebook). Nullable : jamais
    # rattaché si l'intégration NotebookLM échoue ou n'est pas configurée,
    # jamais un prérequis à l'existence de cette recommandation.
    student_notebook_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("student_notebooks.id"), nullable=True
    )
    # Note: exercise_title est positionné dynamiquement en mémoire
    # par le service pour RecommendedExerciseRead, pas comme colonne ORM.
