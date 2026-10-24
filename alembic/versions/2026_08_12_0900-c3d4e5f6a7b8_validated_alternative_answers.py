"""
Migration — Table validated_alternative_answers (câblage Priorité 3).

Comparative_Evaluation_Agent._eval_multiple_distinct_answers interrogeait à
tort reasoning_clarification_requests (mécanisme few-shot §10ter de
Reasoning_Graph_Agent, embedding calculé sur la QUESTION posée par l'agent,
pas une réponse d'étudiant) pour retrouver des réponses alternatives déjà
validées par un professeur. ComparativeEvaluationPattern (déjà existante)
n'est pas non plus adaptée (pattern_signature structurel, pas de texte
libre — cf. son docstring). Nouvelle table dédiée, même infrastructure RAG
(embedding Text/JSON, fallback NumPy, cf. rag_repository.py) que les deux
tables ci-dessus.

Révision : 2026_08_12_0900-c3d4e5f6a7b8_validated_alternative_answers
Révision précédente : 6f2a9d1c4b7e
"""
import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "6f2a9d1c4b7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "validated_alternative_answers",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("criterion_id", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column(
            "validated_by_professor_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("professors.id"),
            nullable=False,
        ),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("validated_alternative_answers")
