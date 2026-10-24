"""
StudentFeedbackReport = feedback pédagogique socratique généré par
Feedback_Agent pour UNE soumission (§7 cahier des charges, "Feedback
Intelligent" — Feedback_Agent).

Distinct du couple FeedbackVersion/feedbacks (app/domain/models/assessment/
feedback_version.py) : ce dernier porte un feedback PAR QUESTION,
versionné, éditable par un professeur (author_type=AI|TEACHER, historique
CHAABI §2.6) — jamais appelé en pratique dans ce pipeline à ce jour.
StudentFeedbackReport porte à l'inverse UN texte PAR SOUMISSION couvrant
plusieurs compétences à la fois (relit identified_difficulties/weaknesses/
strengths de PLUSIEURS lignes de StudentCompetencyReport en une seule
génération), jamais édité manuellement, jamais versionné — une ligne par
exécution de feedback_node. Nommage volontairement différent (Feedback
Report vs Feedback/FeedbackVersion) pour ne jamais confondre les deux
mécanismes.

feedback_text : texte socratique complet prêt à être affiché tel quel à
l'étudiant (jamais de JSON/balises, cf. Feedback_Agent).
competencies_addressed : JSONB (liste de C2PCTSkillCode.value) — même
convention que RecommendedExercise/Question.covered_subquestions pour les
colonnes liste dans ce codebase, jamais une table de jointure séparée pour
une liste aussi courte et jamais interrogée individuellement.
"""
import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class StudentFeedbackReport(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "student_feedback_reports"

    student_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("students.id"), nullable=False, index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("modules.id"), nullable=False
    )
    # Jamais nullable, contrairement à RecommendedExercise.submission_id/
    # StudentNotebook.submission_id : Feedback_Agent ne se déclenche QUE
    # dans la branche student_evaluation, toujours pour UNE soumission
    # précise (cf. docstring feedback_node.py) — pas d'équivalent au cas
    # "génération manuelle hors soumission" de ces deux autres modèles.
    submission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=False, index=True
    )
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    competencies_addressed: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
