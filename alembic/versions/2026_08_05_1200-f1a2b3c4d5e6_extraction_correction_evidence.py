"""
Migration : ExtractionCorrection — question_id nullable + enum extraction_evidence_level + colonne evidence_level.

Revision ID: f1a2b3c4d5e6
Revises: e8a9b2c3d4f5
Create Date: 2026-08-05 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f1a2b3c4d5e6"
down_revision = "e8a9b2c3d4f5"
branch_labels = None
depends_on = None


extraction_evidence_level = postgresql.ENUM(
    "label_explicite",
    "contenu_vs_reference",
    "ambigu",
    "orphelin",
    name="extraction_evidence_level",
    create_type=False,
)


def upgrade() -> None:
    # 1. Créer le type enum
    op.execute(
        "CREATE TYPE extraction_evidence_level AS ENUM "
        "('label_explicite', 'contenu_vs_reference', 'ambigu', 'orphelin')"
    )

    # 2. question_id : NOT NULL -> NULL
    op.alter_column(
        "extraction_corrections",
        "question_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # 3. Ajouter evidence_level avec un défaut temporaire pour les lignes existantes,
    #    puis retirer le défaut (la valeur par défaut n'appartient pas au domaine métier).
    op.add_column(
        "extraction_corrections",
        sa.Column(
            "evidence_level",
            extraction_evidence_level,
            nullable=True,  # temporairement nullable pour les lignes existantes
        ),
    )
    # Remplir les lignes existantes avec la valeur par défaut métier la plus prudente
    op.execute(
        "UPDATE extraction_corrections SET evidence_level = 'ambigu' WHERE evidence_level IS NULL"
    )
    # Rendre la colonne non-nullable
    op.alter_column("extraction_corrections", "evidence_level", nullable=False)


def downgrade() -> None:
    op.drop_column("extraction_corrections", "evidence_level")
    op.alter_column(
        "extraction_corrections",
        "question_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.execute("DROP TYPE extraction_evidence_level")
