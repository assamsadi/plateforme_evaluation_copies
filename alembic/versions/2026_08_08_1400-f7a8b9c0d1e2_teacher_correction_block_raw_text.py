"""
Migration : teacher_correction_blocks — colonne raw_text.

Document_Structuring_Agent ne persistait jamais le texte brut OCR d'un bloc
de correction (seul structured_content était transmis, réservé aux blocs
STRUCTURE/EQUATION) — pour un bloc TEXTE, rien ne survivait hormis
image_crop_path. Extraction_Verification_Agent (décomposition + barème) a
besoin de ce texte pour fonctionner. Corrigé à la source plutôt que contourné.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-08-08 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teacher_correction_blocks",
        sa.Column("raw_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("teacher_correction_blocks", "raw_text")
