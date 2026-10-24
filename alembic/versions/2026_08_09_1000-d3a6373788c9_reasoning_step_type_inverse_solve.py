"""
Migration : reasoning_step_type — ajout de la valeur INVERSE_SOLVE.

Extraction_Verification_Agent (Phase 3b, §2ter) détecte désormais le motif
"poser une contrainte/inéquation puis isoler l'inconnue" comme un step_type
à part entière. Même situation que CASE_SPLIT (37d1dd9376be) : enum partagé
avec le flux Solution_Variant, migration purement additive.

Revision ID: d3a6373788c9
Revises: 37d1dd9376be
Create Date: 2026-08-09 10:00:00.000000
"""
from alembic import op

revision = "d3a6373788c9"
down_revision = "37d1dd9376be"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE reasoning_step_type ADD VALUE IF NOT EXISTS 'INVERSE_SOLVE'")


def downgrade() -> None:
    # Postgres ne supporte pas DROP VALUE sur un type ENUM — no-op documenté,
    # cohérent avec les autres migrations ADD VALUE de ce projet.
    pass
