"""b0_add_exercise_sections

Revision ID: e8a9b2c3d4f5
Revises: 4cfa9127769c
Create Date: 2026-08-05 10:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e8a9b2c3d4f5'
down_revision: Union[str, Sequence[str], None] = '4cfa9127769c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'exercise_sections',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('exercise_id', sa.UUID(), sa.ForeignKey('exercises.id', ondelete='CASCADE'), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('exercise_id', 'order', name='uq_exercise_section_exercise_order')
    )
    op.add_column(
        'questions',
        sa.Column('section_id', sa.UUID(), sa.ForeignKey('exercise_sections.id', ondelete='SET NULL'), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('questions', 'section_id')
    op.drop_table('exercise_sections')
