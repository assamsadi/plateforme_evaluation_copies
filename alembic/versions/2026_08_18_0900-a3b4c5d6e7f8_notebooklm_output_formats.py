"""
Migration — formats de sortie NotebookLM (§7, Partie 2/2) : colonnes
audio/flashcards/vidéo sur student_notebooks (best-effort, nullable),
+ rattachement recommended_exercises -> student_notebooks (nullable,
rattaché après coup par la tâche Celery).

Table student_notebooks confirmée avec un usage réel mais peu volumineux
(chantier en cours) — updated_at ajouté ici (TimestampMixin, la ligne
n'est plus immuable en Partie 2 : audio/flashcards/vidéo la modifient
après création, cf. docstring modèle).

Révision : 2026_08_18_0900-a3b4c5d6e7f8_notebooklm_output_formats
Révision précédente : f2a3b4c5d6e7
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a3b4c5d6e7f8"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE video_overview_status AS ENUM ('not_requested', 'pending', 'ready')")

    op.add_column("student_notebooks", sa.Column("audio_overview_path", sa.String(512), nullable=True))
    op.add_column("student_notebooks", sa.Column("flashcards_path", sa.String(512), nullable=True))
    op.add_column("student_notebooks", sa.Column("video_overview_path", sa.String(512), nullable=True))
    op.add_column(
        "student_notebooks",
        sa.Column(
            "video_overview_status",
            postgresql.ENUM(
                "not_requested", "pending", "ready", name="video_overview_status", create_type=False,
            ),
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column(
        "student_notebooks",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
    )

    op.add_column(
        "recommended_exercises",
        sa.Column("student_notebook_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("student_notebooks.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recommended_exercises", "student_notebook_id")
    op.drop_column("student_notebooks", "updated_at")
    op.drop_column("student_notebooks", "video_overview_status")
    op.drop_column("student_notebooks", "video_overview_path")
    op.drop_column("student_notebooks", "flashcards_path")
    op.drop_column("student_notebooks", "audio_overview_path")
    op.execute("DROP TYPE video_overview_status")
