"""add_evaluated_variant_candidates

Revision ID: a1c3e7f92b41
Revises: 44f86b253936
Create Date: 2026-08-11 00:33:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1c3e7f92b41'
down_revision: Union[str, Sequence[str], None] = '44f86b253936'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'candidate_decision') THEN
                CREATE TYPE candidate_decision AS ENUM ('accepted', 'rejected');
            END IF;
        END
        $$;
    """)
    candidate_decision_enum_col = postgresql.ENUM('accepted', 'rejected', name='candidate_decision', create_type=False)

    op.create_table(
        'evaluated_variant_candidates',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('question_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('structural_signature', sa.String(length=64), nullable=False),
        sa.Column('decision', candidate_decision_enum_col, nullable=False),
        sa.Column('resulting_variant_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['questions.id']),
        sa.ForeignKeyConstraint(['resulting_variant_id'], ['solution_variants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id', 'structural_signature', name='uq_evaluated_candidate_question_signature'),
    )


def downgrade() -> None:
    op.drop_table('evaluated_variant_candidates')
    postgresql.ENUM(name='candidate_decision').drop(op.get_bind(), checkfirst=True)
