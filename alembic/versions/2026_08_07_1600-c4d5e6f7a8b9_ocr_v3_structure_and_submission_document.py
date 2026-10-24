"""
Migration OCR v3 : ajout STRUCTURE à extraction_content_type +
colonnes document_path / document_mime_type sur submissions.

Revision ID: c4d5e6f7a8b9
Revises: b2c3d4e5f6a1
Create Date: 2026-08-07 16:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b2c3d4e5f6a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE extraction_content_type ADD VALUE IF NOT EXISTS 'STRUCTURE'")

    op.add_column(
        "submissions",
        sa.Column("document_path", sa.Text(), nullable=True),
    )
    op.add_column(
        "submissions",
        sa.Column("document_mime_type", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("submissions", "document_mime_type")
    op.drop_column("submissions", "document_path")
    # PostgreSQL ne permet pas de retirer une valeur d'un enum sans recréer le type.
