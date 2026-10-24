"""
Migration : structuration Question.subquestions (backlog_bugs_c2pct.md,
approche validée avec l'utilisateur 2026-08-29) — nouveau champ ADDITIF,
jamais un remplacement de `statement` (texte brut complet, toujours
consommé tel quel ailleurs, ex. VerifiableElement/Comparative_Evaluation_
Agent). Colonne nullable : None si covered_subquestions était vide pour la
question, ou si l'extraction verbatim (Extraction_Verification_Agent.
_extract_subquestion_segments) a échoué (best-effort, jamais bloquant,
même discipline que subquestion_points).

Contenu : [{"id": "1.1", "content": "<extrait verbatim vérifié>"}] —
`official_title` n'est JAMAIS stocké ici, résolu à la lecture depuis
c2pct_scaffold (seule source de vérité).

Révision : 2026_08_29_1400-736c2945052c_question_subquestions
Révision précédente : 1e8311cc788a
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "736c2945052c"
down_revision = "1e8311cc788a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "questions",
        sa.Column("subquestions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("questions", "subquestions")
