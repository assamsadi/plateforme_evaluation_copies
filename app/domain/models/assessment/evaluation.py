"""
Evaluation = le résultat du Pedagogical Evaluation Agent (note classique)
et du C2PCT Competency Assessment Agent (compétences) pour UNE question
d'UNE soumission (§3 : géré question par question, jamais globalement
sur toute la copie). Une seule Evaluation par (submission, question).

classic_criteria_observed : les 4 critères pédagogiques (exactitude,
cohérence, complétude, justification) — DÉPASSÉS par Pedagogical_
Evaluation_Agent (Phase 4/4 du chantier C2PCT) : conservés comme méta-
donnée informative (héritage), N'INFLUENCENT PLUS score. C'est désormais
la répartition du barème entre compétences C2PCT réellement mobilisées
(covered_subquestions/EvaluationCriteria.competency_code) qui détermine
score.

c2pct_observed (RETIRÉ — câblage StudentCompetencyProfile) : portait
l'ancienne granularité (7 compétences toujours forcées, notées sur 100,
sans lien avec les 15 sous-questions C2PCT) — jamais alimenté par le
chemin actif (record_question_score() passait systématiquement []),
donc StudentCompetencyProfile ne se mettait plus à jour en pratique.
Remplacé : record_question_score() alimente désormais directement
StudentCompetencyProfile depuis CompetencyScoreDetail.success_rate
(Pedagogical_Evaluation_Agent), Niveau 1 (par question) uniquement —
l'agrégation Niveau 2 (copie entière)/Niveau 3 (décroissance temporelle)
reste le rôle de Competency_Assessment_Agent (pas construit ici). Aucune
donnée réelle n'existait sur cette colonne au moment du retrait (vérifié
sur evaluation_copies ET evaluation_copies_test).
"""
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, Sequence, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class Evaluation(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint(
            "submission_id", "question_id", name="uq_evaluation_submission_question"
        ),
    )

    submission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=False
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    # Identifiant lisible séquentiel (audit "ids manquants") — cf. commentaire
    # Admin.admin_number pour le principe.
    evaluation_number: Mapped[int] = mapped_column(
        Integer, Sequence("evaluation_number_seq"), unique=True, nullable=False
    )

    # Liste de {"criterion": "exactitude"|"coherence"|"completude"|"justification",
    #           "score": Decimal, "justification": str}
    # DÉPASSÉ par Phase 4/4 (cf. docstring module) — méta-donnée
    # informative, n'influence plus le score final.
    classic_criteria_observed: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Note: question_order et criterion_label sont positionnés dynamiquement en mémoire
    # par le service pour EvaluationRead, pas comme colonnes ORM.

    # Câblage copy_report (§0 Comparative_Evaluation_Agent : "chaque
    # décision vérifiable, traçable et contestable") — QuestionReport.
    # to_dict() (Pedagogical_Evaluation_Agent), PAR QUESTION (même
    # granularité que cette table, jamais un CopyReport complet dupliqué
    # ici). Le CopyReport agrégé (avec overview) est assemblé à la LECTURE
    # par EvaluationService.get_copy_report, jamais persisté tel quel —
    # même principe que get_total_score_for_submission (SUM() natif,
    # jamais un total stocké séparément). Nullable : lignes écrites avant
    # ce câblage, ou question sans QuestionReport.
    copy_report_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

