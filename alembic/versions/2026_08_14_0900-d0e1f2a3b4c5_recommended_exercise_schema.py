"""
Migration — schéma RecommendedExercise pour Recommendation_Agent.

recommended_exercises confirmée VIDE avant ce changement (aucun appelant
réel du CRUD existant, cf. rapport de câblage) — colonnes ajoutées NOT NULL
directement, aucun backfill nécessaire.

1. student_id/module_id directs (jamais uniquement via submission_id).
2. competency_code (réutilise le type Postgres existant c2pct_skill_code,
   create_type=False — même type que student_competency_observations.
   competency_code/evaluation_criteria.competency_code).
3. category (recommendation_category, nouveau type).
4. status (recommendation_status, nouveau type, défaut 'active').
5. submission_id devient nullable.

Révision : 2026_08_14_0900-d0e1f2a3b4c5_recommended_exercise_schema
Révision précédente : c9d0e1f2a3b4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE recommendation_category AS ENUM ('remediation', 'verification')")
    op.execute("CREATE TYPE recommendation_status AS ENUM ('active', 'superseded')")

    op.add_column(
        "recommended_exercises",
        sa.Column("student_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("students.id"), nullable=False),
    )
    op.create_index(
        "ix_recommended_exercises_student_id", "recommended_exercises", ["student_id"],
    )
    op.add_column(
        "recommended_exercises",
        sa.Column("module_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("modules.id"), nullable=False),
    )

    competency_code_enum_col = postgresql.ENUM(
        "data_and_planning", "decomposition_and_organization", "algorithmic_structuring",
        "generalization_and_transfer", "solution_communication",
        "self_evaluation_and_creativity", "reflection_and_metacognition",
        name="c2pct_skill_code", create_type=False,
    )
    op.add_column(
        "recommended_exercises",
        sa.Column("competency_code", competency_code_enum_col, nullable=False),
    )

    category_enum_col = postgresql.ENUM(
        "remediation", "verification", name="recommendation_category", create_type=False,
    )
    op.add_column(
        "recommended_exercises",
        sa.Column("category", category_enum_col, nullable=False),
    )

    status_enum_col = postgresql.ENUM(
        "active", "superseded", name="recommendation_status", create_type=False,
    )
    op.add_column(
        "recommended_exercises",
        sa.Column("status", status_enum_col, nullable=False, server_default="active"),
    )
    op.alter_column("recommended_exercises", "status", server_default=None)

    op.alter_column("recommended_exercises", "submission_id", nullable=True)


def downgrade() -> None:
    op.alter_column("recommended_exercises", "submission_id", nullable=False)
    op.drop_column("recommended_exercises", "status")
    op.drop_column("recommended_exercises", "category")
    op.drop_column("recommended_exercises", "competency_code")
    op.drop_index("ix_recommended_exercises_student_id", table_name="recommended_exercises")
    op.drop_column("recommended_exercises", "module_id")
    op.drop_column("recommended_exercises", "student_id")
    op.execute("DROP TYPE recommendation_status")
    op.execute("DROP TYPE recommendation_category")
