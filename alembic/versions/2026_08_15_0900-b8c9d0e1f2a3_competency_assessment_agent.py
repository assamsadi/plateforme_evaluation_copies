"""
Migration — Competency_Assessment_Agent (Partie 1/2, chantier RAG/C2PCT).

1. CompetencyTrend : PROGRESSION/STABLE/REGRESSION -> IMPROVING/DECLINING/
   STABLE/INSUFFICIENT_DATA (mécanisme Niveau 1 retiré du ticket précédent,
   table student_competency_profiles confirmée VIDE avant ce changement —
   aucune perte de donnée. Type recréé plutôt qu'ALTER TYPE ADD/DROP VALUE
   — Postgres ne permet pas de retirer une valeur d'un enum existant).

2. student_competency_profiles : + evaluations_count, confidence_level,
   is_persistent_weakness (cache léger Niveau 3, cf. docstring modèle).

3. Nouvelle table student_competency_observations — historique atomique
   Niveau 2 par (student, module, competency, submission), lu par
   Competency_Assessment_Agent pour calculer Niveau 3 (décroissance
   exponentielle) et assembler les champs enrichis à la lecture.

Révision : 2026_08_15_0900-b8c9d0e1f2a3_competency_assessment_agent
Révision précédente : a7b8c9d0e1f2
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. CompetencyTrend — recréation du type (table vide, confirmé).
    op.execute(sa.text(
        "ALTER TABLE student_competency_profiles ALTER COLUMN trend DROP DEFAULT"
    ))
    op.execute(sa.text(
        "ALTER TABLE student_competency_profiles ALTER COLUMN trend TYPE text USING trend::text"
    ))
    op.execute(sa.text("DROP TYPE competency_trend"))
    # Noms de membres Python en MAJUSCULES (IMPROVING, pas "improving") —
    # PgEnum(CompetencyTrend, name=...) sans values_callable utilise par
    # défaut le NOM du membre, jamais sa .value (même comportement déjà en
    # place pour c2pct_skill_code, vérifié empiriquement : ALGORITHMIC_
    # STRUCTURING stocké tel quel, pas "algorithmic_structuring" — aucune
    # incohérence à corriger ici, ce câblage suit le même défaut).
    op.execute(sa.text(
        "CREATE TYPE competency_trend AS ENUM "
        "('IMPROVING', 'DECLINING', 'STABLE', 'INSUFFICIENT_DATA')"
    ))
    op.execute(sa.text(
        "ALTER TABLE student_competency_profiles ALTER COLUMN trend "
        "TYPE competency_trend USING trend::competency_trend"
    ))
    op.execute(sa.text(
        "ALTER TABLE student_competency_profiles ALTER COLUMN trend "
        "SET DEFAULT 'INSUFFICIENT_DATA'"
    ))

    # 2. StudentCompetencyProfile — cache léger Niveau 3.
    op.add_column(
        "student_competency_profiles",
        sa.Column("evaluations_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "student_competency_profiles",
        sa.Column("confidence_level", sa.Numeric(3, 2), nullable=False, server_default="0"),
    )
    op.add_column(
        "student_competency_profiles",
        sa.Column("is_persistent_weakness", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.alter_column("student_competency_profiles", "evaluations_count", server_default=None)
    op.alter_column("student_competency_profiles", "confidence_level", server_default=None)
    op.alter_column("student_competency_profiles", "is_persistent_weakness", server_default=None)

    # 3. student_competency_observations
    competency_code_enum_col = postgresql.ENUM(
        "data_and_planning", "decomposition_and_organization", "algorithmic_structuring",
        "generalization_and_transfer", "solution_communication",
        "self_evaluation_and_creativity", "reflection_and_metacognition",
        name="c2pct_skill_code", create_type=False,
    )
    op.create_table(
        "student_competency_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "student_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("students.id"), nullable=False, index=True,
        ),
        sa.Column(
            "module_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("modules.id"), nullable=False,
        ),
        sa.Column("competency_code", competency_code_enum_col, nullable=False),
        sa.Column(
            "submission_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("submissions.id"), nullable=False,
        ),
        sa.Column("performance_copie", sa.Numeric(6, 5), nullable=False),
        sa.Column("subquestions_covered_count", sa.Integer(), nullable=False),
        sa.Column("subquestions_succeeded_count", sa.Integer(), nullable=False),
        sa.Column("question_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("subquestion_outcomes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("decision_reasons", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint(
            "student_id", "module_id", "competency_code", "submission_id",
            name="uq_student_competency_observation_submission",
        ),
    )
    # Index composite pour la lecture d'historique (le chemin de lecture
    # dominant : toutes les observations d'un (student, module, competency),
    # triées par récence).
    op.create_index(
        "ix_student_competency_observations_lookup",
        "student_competency_observations",
        ["student_id", "module_id", "competency_code", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_student_competency_observations_lookup", table_name="student_competency_observations")
    op.drop_table("student_competency_observations")

    op.drop_column("student_competency_profiles", "is_persistent_weakness")
    op.drop_column("student_competency_profiles", "confidence_level")
    op.drop_column("student_competency_profiles", "evaluations_count")

    op.execute(sa.text(
        "ALTER TABLE student_competency_profiles ALTER COLUMN trend DROP DEFAULT"
    ))
    op.execute(sa.text(
        "ALTER TABLE student_competency_profiles ALTER COLUMN trend TYPE text USING trend::text"
    ))
    op.execute(sa.text("DROP TYPE competency_trend"))
    op.execute(sa.text(
        "CREATE TYPE competency_trend AS ENUM ('PROGRESSION', 'STABLE', 'REGRESSION')"
    ))
    op.execute(sa.text(
        "ALTER TABLE student_competency_profiles ALTER COLUMN trend "
        "TYPE competency_trend USING trend::competency_trend"
    ))
    op.execute(sa.text(
        "ALTER TABLE student_competency_profiles ALTER COLUMN trend SET DEFAULT 'STABLE'"
    ))
