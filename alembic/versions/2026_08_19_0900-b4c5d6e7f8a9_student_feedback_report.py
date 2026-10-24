"""
Migration — table student_feedback_reports (chantier Feedback_Agent, §7
cahier des charges "Feedback Intelligent").

Une ligne par exécution de feedback_node (toujours liée à une soumission,
contrairement à student_notebooks/recommended_exercises où submission_id
est nullable, cf. docstring modèle). competencies_addressed en JSONB, même
convention que les autres colonnes liste de ce projet (RecommendedExercise/
Question.covered_subquestions).

Révision : 2026_08_19_0900-b4c5d6e7f8a9_student_feedback_report
Révision précédente : a3b4c5d6e7f8
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b4c5d6e7f8a9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "student_feedback_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("modules.id"), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("submissions.id"), nullable=False),
        sa.Column("feedback_text", sa.Text(), nullable=False),
        sa.Column("competencies_addressed", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
    )
    op.create_index("ix_student_feedback_reports_student_id", "student_feedback_reports", ["student_id"])
    op.create_index("ix_student_feedback_reports_submission_id", "student_feedback_reports", ["submission_id"])


def downgrade() -> None:
    op.drop_index("ix_student_feedback_reports_submission_id", table_name="student_feedback_reports")
    op.drop_index("ix_student_feedback_reports_student_id", table_name="student_feedback_reports")
    op.drop_table("student_feedback_reports")
