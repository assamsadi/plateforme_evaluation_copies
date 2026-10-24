"""
Migration — Table reasoning_clarification_requests, colonne criterion_id
(câblage HITL indexation RAG, Priorité 1).

Corrélation logique vers Bareme.criteria[].id (JSON) — pas une FK SQL, même
principe que EvaluationCriteria.criterion_id / ValidatedAlternativeAnswer.
criterion_id. Renseignée uniquement pour les clarifications MULTIPLE_
DISTINCT_ANSWERS de Comparative_Evaluation_Agent (related_entity_type=
"Question") — None pour toute ligne Reasoning_Graph_Agent/Extraction_
Verification_Agent, comme avant ce câblage.

Révision : 2026_08_13_0900-e5f6a7b8c9d0_reasoning_clarification_criterion_id
Révision précédente : d4e5f6a7b8c9
"""
import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column("criterion_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reasoning_clarification_requests", "criterion_id")
