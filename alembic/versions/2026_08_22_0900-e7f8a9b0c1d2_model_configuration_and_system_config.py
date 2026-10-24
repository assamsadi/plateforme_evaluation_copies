"""
Migration — chantier "Configuration des modèles IA" (admin).

model_configurations : une ligne par TaskType (task_type = clé primaire),
surcharge UNIQUEMENT l'entrée primaire de la chaîne de fallback (provider/
model_name/timeout_seconds) — absence de ligne = comportement identique à
_DEFAULT_REGISTRY_CONFIG (repli jamais cassé, cf. docstring du modèle
ModelConfiguration et de ModelRegistry).

system_config_overrides : clé/valeur générique (key = clé primaire, value
en texte brut, typé à la lecture selon une allowlist codée en dur, cf.
app/services/system_config_service.py) — stockage/lecture seulement à ce
stade, jamais câblé dans les agents/services (décision actée).

Révision : 2026_08_22_0900-e7f8a9b0c1d2_model_configuration_and_system_config
Révision précédente : d6e7f8a9b0c1
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7f8a9b0c1d2"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


# SQLAlchemy Enum(SomeEnum, ...) SANS values_callable envoie le NOM du
# membre Python (majuscules), pas .value — même convention que
# exercise_status/exercise_difficulty dans ce projet (cf. leurs
# migrations). Constaté empiriquement ici : une première version de cette
# migration utilisait .value (minuscules) -> InvalidTextRepresentationError
# à l'exécution réelle (jamais détecté par un simple import/parse).
_TASK_TYPE_VALUES = (
    "OCR_VISION", "DOCUMENT_STRUCTURING", "QUESTION_ATTACHMENT",
    "SOLUTION_VARIANT_GENERATION", "REASONING_GRAPH", "COMPARATIVE_EVALUATION",
    "PEDAGOGICAL_EVALUATION", "COMPETENCY_ASSESSMENT", "FEEDBACK_GENERATION",
    "CONTESTATION_VERIFICATION", "EXTRACTION_VERIFICATION",
)
_MODEL_PROVIDER_VALUES = ("GROQ", "OPENAI", "AZURE_OPENAI")


def upgrade() -> None:
    op.execute(
        "CREATE TYPE model_configuration_task_type AS ENUM ("
        + ", ".join(f"'{v}'" for v in _TASK_TYPE_VALUES) + ")"
    )
    op.execute(
        "CREATE TYPE model_configuration_provider AS ENUM ("
        + ", ".join(f"'{v}'" for v in _MODEL_PROVIDER_VALUES) + ")"
    )

    op.create_table(
        "model_configurations",
        sa.Column(
            "task_type",
            postgresql.ENUM(*_TASK_TYPE_VALUES, name="model_configuration_task_type", create_type=False),
            primary_key=True,
        ),
        sa.Column(
            "provider",
            postgresql.ENUM(*_MODEL_PROVIDER_VALUES, name="model_configuration_provider", create_type=False),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.clock_timestamp(), nullable=False,
        ),
    )

    op.create_table(
        "system_config_overrides",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.clock_timestamp(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("system_config_overrides")
    op.drop_table("model_configurations")
    op.execute("DROP TYPE model_configuration_provider")
    op.execute("DROP TYPE model_configuration_task_type")
