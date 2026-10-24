"""
Migration — Exercise.difficulty_level pour Recommendation_Agent (clôture).

Nouveau type Postgres exercise_difficulty, DISTINCT de variant_difficulty
(cf. docstring modèle ExerciseDifficulty — concepts différents, vocabulaire
coïncident). Valeurs en MAJUSCULES (noms de membres Python), même
convention que exercise_status dans cette même table (PgEnum sans
values_callable) — pas la convention values_callable/minuscules utilisée
ailleurs (ex. recommendation_category).

Colonne nullable : DRAFT/EXAM/HOMEWORK n'en ont jamais besoin, seule
ARCHIVED_IN_LIBRARY l'exige désormais (verrou applicatif dans
ExerciseService.publish, pas une contrainte NOT NULL en base — des
exercices non-Library existants doivent rester valides sans elle).

Révision : 2026_08_16_0900-e1f2a3b4c5d6_exercise_difficulty_level
Révision précédente : d0e1f2a3b4c5
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE exercise_difficulty AS ENUM ('FACILE', 'INTERMEDIAIRE', 'AVANCE')")
    op.add_column(
        "exercises",
        sa.Column(
            "difficulty_level",
            postgresql.ENUM("FACILE", "INTERMEDIAIRE", "AVANCE", name="exercise_difficulty", create_type=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("exercises", "difficulty_level")
    op.execute("DROP TYPE exercise_difficulty")
