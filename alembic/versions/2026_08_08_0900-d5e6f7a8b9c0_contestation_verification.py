"""
Migration : Contestation_Verification_Agent — champs de contestation sur
extraction_corrections, état PENDING/RESOLVED sur correction_arbitrations,
nouveau statut submission PENDING_ARBITRATION, nouveau trigger_type
integrity_alerts SYSTEMATIC_CONTESTATION.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-08-08 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Nouveaux enums
    op.execute(
        "CREATE TYPE contestation_type AS ENUM "
        "('content', 'attachment', 'structure_element', 'fusion')"
    )
    op.execute(
        "CREATE TYPE contestation_status AS ENUM "
        "('pending_verification', 'plausible', 'implausible', 'ambigu', 'resolved')"
    )
    op.execute("CREATE TYPE arbitration_status AS ENUM ('pending', 'resolved')")

    # 2. Valeurs ajoutées à des enums existants
    op.execute("ALTER TYPE submission_status ADD VALUE IF NOT EXISTS 'pending_arbitration'")
    op.execute("ALTER TYPE integrity_trigger_type ADD VALUE IF NOT EXISTS 'systematic_contestation'")

    # 3. extraction_corrections — nouvelles colonnes
    op.add_column("extraction_corrections", sa.Column("page_number", sa.Integer(), nullable=True))
    op.add_column(
        "extraction_corrections",
        sa.Column(
            "contestation_type",
            postgresql.ENUM(
                "content", "attachment", "structure_element", "fusion",
                name="contestation_type", create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "extraction_corrections",
        sa.Column(
            "contestation_status",
            postgresql.ENUM(
                "pending_verification", "plausible", "implausible", "ambigu", "resolved",
                name="contestation_status", create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column("extraction_corrections", sa.Column("contested_element_id", sa.Text(), nullable=True))
    op.add_column(
        "extraction_corrections",
        sa.Column(
            "claimed_question_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id"), nullable=True,
        ),
    )
    op.add_column(
        "extraction_corrections",
        sa.Column(
            "claimed_section_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exercise_sections.id"), nullable=True,
        ),
    )
    op.add_column("extraction_corrections", sa.Column("verified_content", sa.Text(), nullable=True))
    op.add_column(
        "extraction_corrections",
        sa.Column("fused_extraction_correction_ids", postgresql.JSONB(), nullable=True),
    )

    # 4. correction_arbitrations — état PENDING/RESOLVED
    op.add_column(
        "correction_arbitrations",
        sa.Column(
            "status",
            postgresql.ENUM("pending", "resolved", name="arbitration_status", create_type=False),
            nullable=False,
            server_default="resolved",  # lignes existantes = déjà résolues avant cette migration
        ),
    )
    op.alter_column("correction_arbitrations", "teacher_professor_id", nullable=True)
    op.alter_column("correction_arbitrations", "verdict", nullable=True)
    op.add_column("correction_arbitrations", sa.Column("claimed_correction", sa.Text(), nullable=True))
    op.alter_column("correction_arbitrations", "status", server_default=None)


def downgrade() -> None:
    op.drop_column("correction_arbitrations", "claimed_correction")
    op.alter_column("correction_arbitrations", "verdict", nullable=False)
    op.alter_column("correction_arbitrations", "teacher_professor_id", nullable=False)
    op.drop_column("correction_arbitrations", "status")

    op.drop_column("extraction_corrections", "fused_extraction_correction_ids")
    op.drop_column("extraction_corrections", "verified_content")
    op.drop_column("extraction_corrections", "claimed_section_id")
    op.drop_column("extraction_corrections", "claimed_question_id")
    op.drop_column("extraction_corrections", "contested_element_id")
    op.drop_column("extraction_corrections", "contestation_status")
    op.drop_column("extraction_corrections", "contestation_type")
    op.drop_column("extraction_corrections", "page_number")

    # Postgres ne permet pas de retirer une valeur d'enum — downgrade des
    # types partiel, documenté : submission_status/integrity_trigger_type
    # conservent 'pending_arbitration'/'systematic_contestation' même après
    # downgrade (limitation connue de Postgres, cohérente avec le reste du
    # projet qui ne retire jamais de valeur d'enum en downgrade).
    op.execute("DROP TYPE arbitration_status")
    op.execute("DROP TYPE contestation_status")
    op.execute("DROP TYPE contestation_type")
