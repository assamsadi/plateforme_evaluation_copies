"""
Migration : Extraction_Verification_Agent (Phase 6/6) — service de
persistance, colonnes manquantes identifiées en confirmant les hypothèses
de mapping vers le schéma existant.

1. baremes.validation_status — Bareme n'avait aucun champ de statut. Cas 2
   (répartition proposée, jamais confirmée automatiquement) doit rester
   distinguable d'un barème détaillé fourni par le prof (Cas 1) — sans ça,
   rien ne permettrait de savoir qu'un Bareme persisté est encore "à
   valider". Toutes les lignes existantes (créées via create_with_questions,
   toujours un barème détaillé fourni par le prof) sont rétroactivement
   CONFIRMED.

2. questions.mandated_method — Phase 5A : méthode/algorithme/outil imposé
   par l'énoncé/la correction, propriété de la question entière (stable
   avant même qu'une SolutionVariant existe), pas d'une étape.

3. reasoning_steps.extraction_signals — Phases 3a/3b produisent des signaux
   par étape (anomaly_detected/justification, case_group_id, recurrence_role,
   canonical_form, dimensional_check_result, numeric_tolerance, criticality,
   source_span) sans colonne dédiée. Une seule colonne JSONB catch-all,
   cohérente avec concept_tags/tools_used déjà en JSONB sur cette même table
   — évite 9 colonnes typées pour des champs qui restent avant tout
   informatifs/traçables, pas interrogés individuellement à ce stade.

4. reasoning_clarification_requests.severity / .proposed_answer — le
   mécanisme (Reasoning_Graph_Agent) n'avait ni l'un ni l'autre : toute
   demande PENDING bloquait implicitement publish(). Extraction_Verification_
   Agent introduit 3 niveaux (Phase 4) ; les lignes existantes (toutes
   implicitement bloquantes jusqu'ici) sont rétroactivement 'blocking' pour
   ne pas changer leur comportement de blocage de publish().

5. reasoning_clarification_requests.unclear_content devient nullable —
   concept propre au Reasoning Graph Agent (texte source encore sans étape
   créée), sans objet pour Extraction_Verification_Agent qui pose une
   question directement, sans "contenu flou" à isoler séparément.

Revision ID: f6644dc544d9
Revises: d3a6373788c9
Create Date: 2026-08-09 14:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f6644dc544d9"
down_revision = "d3a6373788c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. baremes.validation_status
    op.execute("CREATE TYPE bareme_validation_status AS ENUM ('confirmed', 'pending_review')")
    op.add_column(
        "baremes",
        sa.Column(
            "validation_status",
            postgresql.ENUM(
                "confirmed", "pending_review",
                name="bareme_validation_status", create_type=False,
            ),
            nullable=False,
            server_default="confirmed",
        ),
    )
    op.alter_column("baremes", "validation_status", server_default=None)

    # 2. questions.mandated_method
    op.add_column("questions", sa.Column("mandated_method", sa.Text(), nullable=True))

    # 3. reasoning_steps.extraction_signals
    op.add_column(
        "reasoning_steps",
        sa.Column("extraction_signals", postgresql.JSONB(), nullable=True),
    )

    # 4. reasoning_clarification_requests.severity / .proposed_answer
    op.execute("CREATE TYPE clarification_severity AS ENUM ('blocking', 'warning', 'informational')")
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column(
            "severity",
            postgresql.ENUM(
                "blocking", "warning", "informational",
                name="clarification_severity", create_type=False,
            ),
            nullable=False,
            server_default="blocking",
        ),
    )
    op.alter_column("reasoning_clarification_requests", "severity", server_default=None)
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column("proposed_answer", sa.Text(), nullable=True),
    )
    # unclear_content — concept propre au Reasoning Graph Agent (texte
    # source encore sans étape créée), sans objet pour les
    # ClarificationRequest d'Extraction_Verification_Agent (question posée
    # directement, pas de "contenu flou" à isoler).
    op.alter_column("reasoning_clarification_requests", "unclear_content", nullable=True)


def downgrade() -> None:
    op.alter_column("reasoning_clarification_requests", "unclear_content", nullable=False)
    op.drop_column("reasoning_clarification_requests", "proposed_answer")
    op.drop_column("reasoning_clarification_requests", "severity")
    op.execute("DROP TYPE clarification_severity")

    op.drop_column("reasoning_steps", "extraction_signals")

    op.drop_column("questions", "mandated_method")

    op.drop_column("baremes", "validation_status")
    op.execute("DROP TYPE bareme_validation_status")
