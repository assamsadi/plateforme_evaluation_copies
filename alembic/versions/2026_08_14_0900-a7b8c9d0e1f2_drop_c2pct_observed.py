"""
Migration — retrait de evaluations.c2pct_observed (câblage réparation
StudentCompetencyProfile).

c2pct_observed portait l'ancienne granularité (7 compétences toujours
forcées, notées sur 100, sans lien avec les 15 sous-questions C2PCT) et
n'était jamais alimenté par le chemin actif (record_question_score()
passait systématiquement [] à record_evaluation()) — StudentCompetency
Profile ne se mettait donc plus à jour en pratique, silencieusement.
Remplacé par un branchement direct sur CompetencyScoreDetail.success_rate
(Pedagogical_Evaluation_Agent), Niveau 1 uniquement.

Aucune perte de données : confirmé vide sur evaluation_copies ET
evaluation_copies_test avant ce retrait (0 évaluation en base sur les
deux, cf. rapport du chantier).

Révision : 2026_08_14_0900-a7b8c9d0e1f2_drop_c2pct_observed
Révision précédente : f6a7b8c9d0e1
"""
import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("evaluations", "c2pct_observed")


def downgrade() -> None:
    op.add_column(
        "evaluations",
        sa.Column("c2pct_observed", sa.dialects.postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.alter_column("evaluations", "c2pct_observed", server_default=None)
