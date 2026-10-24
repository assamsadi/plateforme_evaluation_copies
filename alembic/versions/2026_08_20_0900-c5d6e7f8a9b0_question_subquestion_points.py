"""
Migration : chantier barème C2PCT natif (Cas 0) — questions.subquestion_points.

Colonne JSONB nullable (contrairement à covered_subquestions, NOT NULL
défaut liste vide) : None = aucun barème détaillé par sous-question C2PCT
trouvé pour cette question, jamais un dict vide ambigu (cf. docstring
modèle Question / Extraction_Verification_Agent._extract_subquestion_points).

Révision : 2026_08_20_0900-c5d6e7f8a9b0_question_subquestion_points
Révision précédente : b4c5d6e7f8a9
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column(
            "subquestion_points",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("questions", "subquestion_points")
