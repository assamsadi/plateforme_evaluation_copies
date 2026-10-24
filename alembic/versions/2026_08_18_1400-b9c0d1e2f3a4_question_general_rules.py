"""
Migration : règles générales du barème du professeur — questions.general_rules.

Colonne JSONB NOT NULL, défaut liste vide (même principe que
covered_subquestions, PAS subquestion_points ci-dessus qui reste nullable) :
une question sans règle générale a une liste vide, jamais None ambigu (cf.
docstring modèle Question / Extraction_Verification_Agent.
QuestionVerificationResult.general_rules).

Révision : 2026_08_18_1400-b9c0d1e2f3a4_question_general_rules
Révision précédente : a9b0c1d2e3f4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b9c0d1e2f3a4"
down_revision = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column(
            "general_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("questions", "general_rules")
