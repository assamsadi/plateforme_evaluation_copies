"""
StudentCompetencyObservation — un FAIT ATOMIQUE par (étudiant, module,
compétence, soumission) : la contribution Niveau 2 (agrégée sur toute la
copie, pondérée par le nombre réel de sous-questions) d'UNE soumission à
UNE compétence. Écrite par CompetencyAssessmentService.assess_submission,
jamais par un agent directement (l'agent calcule, le service persiste).

C'est le SEUL historique persisté — StudentCompetencyProfile reste un
cache léger (mastery_level/trend/evaluations_count/confidence_level/
is_persistent_weakness), jamais les champs enrichis. Competency_Assessment_
Agent.build_competency_line lit N lignes de cette table (les plus
récentes, triées par created_at) pour calculer Niveau 3 (décroissance
exponentielle) ET assembler les champs enrichis (subquestions_concerned/
evidence_questions/strengths/weaknesses/identified_difficulties) — jamais
un document dupliqué stocké séparément (même principe que get_copy_report/
get_total_score_for_submission : agrégat calculé à la lecture).

subquestion_outcomes/decision_reasons sont des INSTANTANÉS pris au moment
de l'observation (jamais recalculés depuis Evaluation.copy_report_detail à
la lecture — la ligne source pourrait changer ou disparaître) :
  - subquestion_outcomes : [{"subquestion_id","addressed","is_correct"}]
    pour TOUTES les sous-questions de cette compétence sur cette
    soumission (y compris les succès triviaux, absents de DecisionEntry —
    nécessaire pour dériver `strengths`, cf. docstring agent).
  - decision_reasons : [{"subquestion_id","decision","reason"}] — UNIQUEMENT
    les DecisionEntry non triviales (NOT_ADDRESSED/INCORRECT/REUSED_FROM_
    STEP_JUDGMENT) déjà produites par Comparative_Evaluation_Agent, jamais
    un nouveau texte généré.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum as PgEnum, ForeignKey, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.shared.mixins import UUIDPKMixin


class StudentCompetencyObservation(Base, UUIDPKMixin):
    __tablename__ = "student_competency_observations"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "module_id", "competency_code", "submission_id",
            name="uq_student_competency_observation_submission",
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )
    competency_code: Mapped[C2PCTSkillCode] = mapped_column(
        PgEnum(C2PCTSkillCode, name="c2pct_skill_code"), nullable=False
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )

    # Niveau 2 — (Σ sous-questions réussies) / (Σ sous-questions couvertes),
    # toutes questions de CETTE soumission pour CETTE compétence.
    performance_copie: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    subquestions_covered_count: Mapped[int] = mapped_column(Integer, nullable=False)
    subquestions_succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False)

    # Quelles Question exactes de cette soumission ont mobilisé cette
    # compétence — pour evidence_questions (Niveau 3).
    question_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    subquestion_outcomes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    decision_reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Pas de TimestampMixin (pas de updated_at : une observation est
    # immuable une fois écrite, jamais modifiée) — created_at sert
    # d'ordonnancement/âge pour la décroissance exponentielle (Niveau 3).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
