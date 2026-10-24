"""
Migration — table student_notebooks (intégration NotebookLM, Partie 1/2,
§7 cahier des charges "Feedback Intelligent").

Une ligne par événement de génération de recommandations (pas par
RecommendedExercise individuelle, cf. docstring modèle). notebook_id
opaque (identifiant externe NotebookLM), jamais un FK vers une table
NotebookLM que nous ne possédons pas.

Révision : 2026_08_17_0900-f2a3b4c5d6e7_student_notebook
Révision précédente : e1f2a3b4c5d6
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f2a3b4c5d6e7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "student_notebooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("modules.id"), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("submissions.id"), nullable=True),
        sa.Column("notebook_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_student_notebooks_student_id", "student_notebooks", ["student_id"])


def downgrade() -> None:
    op.drop_index("ix_student_notebooks_student_id", table_name="student_notebooks")
    op.drop_table("student_notebooks")
