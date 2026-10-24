"""
Migration : Pedagogical_Evaluation_Agent (Phase 4/4, chantier C2PCT) —
evaluation_criteria accepte désormais deux familles de lignes (classique /
compétence), cf. app/domain/models/assessment/evaluation_criteria.py.

Trois opérations :
  1. evaluation_criteria.criterion_id : NOT NULL -> nullable (une ligne
     compétence n'a pas de critère classique à référencer).
  2. evaluation_criteria.competency_code : nouvelle colonne nullable,
     réutilise le type Postgres c2pct_skill_code déjà créé (student_
     competency_profiles.competency_code / reasoning_steps.related_
     competency_code) — create_type=False, aucune recréation du type.
  3. evaluation_criteria.subquestion_detail : nouvelle colonne JSONB
     nullable — détail brut par sous-question (Pedagogical_Evaluation_Agent),
     lignes compétence uniquement.

Invariant criterion_id XOR competency_code : APPLICATIF (EvaluationService),
PAS une contrainte SQL — décision actée, pour rester simple.

Révision : 2026_08_12_0900-13b512700e41_evaluation_criteria_competency
Révision précédente : a9b8c7d6e5f4
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "13b512700e41"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None

_C2PCT_SKILL_CODE_VALUES = (
    "DATA_AND_PLANNING",
    "DECOMPOSITION_AND_ORGANIZATION",
    "ALGORITHMIC_STRUCTURING",
    "GENERALIZATION_AND_TRANSFER",
    "SOLUTION_COMMUNICATION",
    "SELF_EVALUATION_AND_CREATIVITY",
    "REFLECTION_AND_METACOGNITION",
)


def upgrade() -> None:
    op.alter_column("evaluation_criteria", "criterion_id", nullable=True)

    op.add_column(
        "evaluation_criteria",
        sa.Column(
            "competency_code",
            postgresql.ENUM(*_C2PCT_SKILL_CODE_VALUES, name="c2pct_skill_code", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "evaluation_criteria",
        sa.Column("subquestion_detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluation_criteria", "subquestion_detail")
    op.drop_column("evaluation_criteria", "competency_code")
    # NOT NULL restauré uniquement si aucune ligne compétence (criterion_id
    # NULL) n'existe — sinon le downgrade échoue explicitement plutôt que de
    # détruire silencieusement des lignes de notation réelles.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM evaluation_criteria WHERE criterion_id IS NULL) THEN "
        "RAISE EXCEPTION 'evaluation_criteria contient des lignes competency (criterion_id NULL) — downgrade refusé'; "
        "END IF; END $$;"
    )
    op.alter_column("evaluation_criteria", "criterion_id", nullable=False)
