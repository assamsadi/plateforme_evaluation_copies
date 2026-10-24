"""
Migration — Table evaluations, colonne copy_report_detail (câblage
copy_report, ticket §0 Comparative_Evaluation_Agent).

QuestionReport sérialisé (Pedagogical_Evaluation_Agent.QuestionReport.
to_dict()), PAR QUESTION (même granularité que la table evaluations,
UniqueConstraint(submission_id, question_id)) — jamais un CopyReport
complet dupliqué sur chaque ligne. Le CopyReport agrégé (avec overview)
est assemblé à la lecture par EvaluationService.get_copy_report, jamais
persisté séparément.

Révision : 2026_08_12_1000-d4e5f6a7b8c9_evaluation_copy_report_detail
Révision précédente : c3d4e5f6a7b8
"""
import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluations",
        sa.Column("copy_report_detail", sa.dialects.postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluations", "copy_report_detail")
