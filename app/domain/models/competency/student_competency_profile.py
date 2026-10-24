"""
StudentCompetencyProfile = CACHE léger du profil de compétence, par
(étudiant, compétence, module) — évite de recalculer l'historique complet
à chaque fois qu'un futur agent de recommandation/feedback a besoin du
"niveau" d'un étudiant. Écrit UNIQUEMENT par Competency_Assessment_Agent/
CompetencyAssessmentService (câblage Niveau 2/3, cf. son docstring) — plus
jamais par EvaluationService (Niveau 1 retiré, cf. son docstring, deux
mécanismes concurrents auraient été deux sources de vérité contradictoires).

competency_code (enum C2PCTSkillCode) remplace l'ancienne FK UUID vers
C2PCTCompetency (table supprimée — le fichier .md est désormais l'unique
source de vérité du contenu des compétences, cette table ne servait plus
qu'à typer les 7 codes fixes).

Les champs enrichis (subquestions_concerned, evidence_questions,
strengths, weaknesses, identified_difficulties) ne sont PAS mis en cache
ici — assemblés à la LECTURE par CompetencyAssessmentService.get_report
depuis l'historique student_competency_observations (même principe que
get_copy_report/get_total_score_for_submission : agrégat calculé, jamais
un document dupliqué stocké séparément).
"""
import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum as PgEnum, ForeignKey, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class CompetencyTrend(StrEnum):
    """
    Câblage Competency_Assessment_Agent — 4 états (jamais un trend deviné
    ou forcé à STABLE par défaut) : remplace PROGRESSION/STABLE/REGRESSION
    (mécanisme Niveau 1 retiré, table vide au moment du changement, aucune
    perte de donnée — cf. migration dédiée).
    """
    IMPROVING = "improving"
    DECLINING = "declining"
    STABLE = "stable"
    # Moins de 2 observations disponibles pour cette compétence dans ce
    # module — impossible de comparer deux fenêtres, jamais deviné.
    INSUFFICIENT_DATA = "insufficient_data"


class StudentCompetencyProfile(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "student_competency_profiles"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "competency_code", "module_id",
            name="uq_student_competency_module",
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False
    )
    competency_code: Mapped[C2PCTSkillCode] = mapped_column(
        PgEnum(C2PCTSkillCode, name="c2pct_skill_code"), nullable=False
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )

    # Niveau 3 — décroissance exponentielle sur l'historique complet des
    # student_competency_observations (jamais une moyenne mobile simple).
    mastery_level: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    trend: Mapped[CompetencyTrend] = mapped_column(
        PgEnum(CompetencyTrend, name="competency_trend"),
        nullable=False,
        default=CompetencyTrend.INSUFFICIENT_DATA,
    )
    # Nombre d'observations (soumissions) ayant contribué au calcul actuel.
    evaluations_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Fiabilité déterministe du calcul — min(1.0, evaluations_count / 5).
    confidence_level: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False, default=0)
    # Détection de pattern répété — cf. docstring Competency_Assessment_Agent.
    is_persistent_weakness: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    last_computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )