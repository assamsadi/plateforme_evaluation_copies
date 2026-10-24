"""
Bug réel corrigé (2026-09-06, test réel pipeline A-à-Z) : EvaluationCriteria.
bareme_id était NOT NULL alors qu'une question C2PCT-native (Question.
subquestion_points, jamais de ligne Bareme — cf. le correctif "subquestion_
points" de comparative_evaluation_node.py le même jour) n'a tout simplement
aucun id de Bareme à référencer. evaluation_node.py plantait sur
uuid.UUID(None) dès qu'une telle question atteignait record_question_score
— bloquant TOUTE évaluation pour un exercice sans barème classique.

bareme_id n'est jamais lu ailleurs dans le code (grep confirmé, cf.
docstring du modèle) : purement informatif pour une ligne "classique"
(Bareme.criteria), toujours NULL pour une ligne "compétence" C2PCT.

Revision ID: a2b3c4d5e6f7
Revises: e0f1a2b3c4d5
Create Date: 2026-09-06 19:00:00.000000
"""
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a2b3c4d5e6f7"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "evaluation_criteria",
        "bareme_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "evaluation_criteria",
        "bareme_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
