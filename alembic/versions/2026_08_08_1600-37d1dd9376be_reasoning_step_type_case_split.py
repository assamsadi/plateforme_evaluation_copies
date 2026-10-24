"""
Migration : reasoning_step_type — ajout de la valeur CASE_SPLIT.

Extraction_Verification_Agent (Phase 3a, §2ter) détecte désormais un
raisonnement par cas disjoints ("si... alors / si... alors") comme un
step_type à part entière. ReasoningStepType est un enum partagé, déjà
utilisé en production par le flux Solution_Variant (reasoning_steps
alimentée via teacher_validation_router.py) — cette migration aligne le
type Postgres en conséquence.

ADD VALUE IF NOT EXISTS est purement additif : aucune valeur existante
n'est modifiée ni supprimée (contrairement au RENAME VALUE de
e6f7a8b9c0d1). Downgrade en no-op : Postgres ne permet pas de retirer une
valeur d'un enum existant (même limite déjà rencontrée dans ce projet,
cf. c4d5e6f7a8b9).

Revision ID: 37d1dd9376be
Revises: f7a8b9c0d1e2
Create Date: 2026-08-08 16:00:00.000000
"""
from alembic import op

revision = "37d1dd9376be"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE reasoning_step_type ADD VALUE IF NOT EXISTS 'CASE_SPLIT'")


def downgrade() -> None:
    # Postgres ne supporte pas DROP VALUE sur un type ENUM — no-op documenté,
    # cohérent avec les autres migrations ADD VALUE de ce projet.
    pass
