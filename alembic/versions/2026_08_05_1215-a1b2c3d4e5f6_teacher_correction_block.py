"""
Migration : Nouvelle table teacher_correction_blocks + enum block_evidence_level.

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-08-05 12:15:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a1b2c3d4e5f6"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Créer l'enum block_evidence_level
    op.execute(
        "CREATE TYPE block_evidence_level AS ENUM "
        "('label_explicite', 'unresolved_no_label')"
    )

    # 2. Créer la table
    op.create_table(
        "teacher_correction_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "exercise_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("image_crop_path", sa.Text(), nullable=True),
        sa.Column(
            "content_type",
            postgresql.ENUM(
                "text", "equation", "diagram",
                name="extraction_content_type",
                create_type=False,  # déjà créé par extraction_corrections
            ),
            nullable=False,
        ),
        sa.Column("structured_content", postgresql.JSONB(), nullable=True),
        sa.Column(
            "evidence_level",
            postgresql.ENUM(
                "label_explicite", "unresolved_no_label",
                name="block_evidence_level",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("professor_resolution", sa.Text(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_teacher_correction_blocks_exercise_id",
        "teacher_correction_blocks",
        ["exercise_id"],
    )
    op.create_index(
        "ix_teacher_correction_blocks_question_id",
        "teacher_correction_blocks",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_teacher_correction_blocks_question_id", "teacher_correction_blocks")
    op.drop_index("ix_teacher_correction_blocks_exercise_id", "teacher_correction_blocks")
    op.drop_table("teacher_correction_blocks")
    op.execute("DROP TYPE block_evidence_level")
