"""
Migration — mécanisme de résolution AMBIGUOUS_COHERENCE (correctif
découvertes annexes, suite au ticket pause HITL).

1. comparative_clarification_kind : discriminant entre les deux sous-types
   de clarification MULTIPLE_DISTINCT_ANSWERS (alternative_answer/
   coherence_ambiguity) — aucun champ existant ne les distinguait (cf.
   docstring ComparativeClarificationKind, modèle). Backfillée pour les
   lignes alternative_answer déjà existantes (criterion_id renseigné +
   proposed_answer renseigné — signal fiable, cf. _eval_multiple_distinct_
   answers : seule cette sous-branche renseigne proposed_answer).
2. resolved_as_coherent : décision du professeur (coherent/incoherent) sur
   une ligne coherence_ambiguity une fois résolue — colonne typée dédiée,
   jamais un parsing de professor_answer (texte libre).

Révision : 2026_08_13_0900-c9d0e1f2a3b4_comparative_clarification_kind
Révision précédente : b8c9d0e1f2a3
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE comparative_clarification_kind AS ENUM "
        "('alternative_answer', 'coherence_ambiguity')"
    )
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column(
            "comparative_clarification_kind",
            postgresql.ENUM(
                "alternative_answer", "coherence_ambiguity",
                name="comparative_clarification_kind", create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column("resolved_as_coherent", sa.Boolean(), nullable=True),
    )

    # Backfill — lignes alternative_answer déjà existantes.
    op.execute(
        "UPDATE reasoning_clarification_requests "
        "SET comparative_clarification_kind = 'alternative_answer' "
        "WHERE criterion_id IS NOT NULL "
        "AND related_entity_type = 'Question' "
        "AND proposed_answer IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("reasoning_clarification_requests", "resolved_as_coherent")
    op.drop_column("reasoning_clarification_requests", "comparative_clarification_kind")
    op.execute("DROP TYPE comparative_clarification_kind")
