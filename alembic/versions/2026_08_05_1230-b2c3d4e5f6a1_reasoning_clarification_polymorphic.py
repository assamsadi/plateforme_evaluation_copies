"""
Migration : ReasoningClarificationRequest — variant_id nullable +
colonnes related_entity_type et related_entity_id (référence polymorphe).

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-08-05 12:30:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2c3d4e5f6a1"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. variant_id : NOT NULL -> nullable
    op.alter_column(
        "reasoning_clarification_requests",
        "variant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    # 2. Ajouter related_entity_type (VARCHAR)
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column("related_entity_type", sa.Text(), nullable=True),
    )

    # 3. Ajouter related_entity_id (UUID)
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column(
            "related_entity_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("reasoning_clarification_requests", "related_entity_id")
    op.drop_column("reasoning_clarification_requests", "related_entity_type")
    op.alter_column(
        "reasoning_clarification_requests",
        "variant_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
