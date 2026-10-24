"""
Migration : câblage workflow (Priorité 1) — questions.covered_subquestions.

Bloqueur découvert en câblant comparative_evaluation_node : Extraction_
Verification_Agent produit covered_subquestions (Phase 2/4) depuis
plusieurs tickets, mais rien ne le persistait — même trou que
mandated_method avant sa propre migration (f6644dc544d9), même correctif
exact : une colonne JSONB, NOT NULL, défaut liste vide (jamais un total
théorique substitué à une couverture absente).

Révision : 2026_08_13_0900-6f2a9d1c4b7e_question_covered_subquestions
Révision précédente : 13b512700e41
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6f2a9d1c4b7e"
down_revision = "13b512700e41"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column(
            "covered_subquestions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    # server_default retiré après coup (même pattern que baremes.validation_status,
    # cf. f6644dc544d9) : la valeur par défaut applicative reste `default=list`
    # côté ORM, pas une dépendance permanente au défaut serveur.
    op.alter_column("questions", "covered_subquestions", server_default=None)


def downgrade() -> None:
    op.drop_column("questions", "covered_subquestions")
