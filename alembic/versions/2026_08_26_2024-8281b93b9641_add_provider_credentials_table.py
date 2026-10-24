"""add provider_credentials table

Revision ID: 8281b93b9641
Revises: d1e2f3a4b5c6
Create Date: 2026-08-26 20:24:26.413568

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8281b93b9641'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: l'autogenerate a aussi détecté des tables/index "supprimés"
    # (checkpoint_*, student_feedback_reports, comparative_evaluation_patterns,
    # quelques index HNSW) — ce sont des tables existantes mais non
    # enregistrées sur Base.metadata (absentes de app/domain/models/__init__.py),
    # donc Alembic les croit à tort supprimées du modèle. Retiré manuellement :
    # cette migration ne doit toucher QUE provider_credentials.
    op.create_table('provider_credentials',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', sa.String(length=1000), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('provider_credentials')
