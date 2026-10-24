"""
Migration : B5 (backlog_bugs_c2pct.md) — le contenu de correction
reconstruit (`_combine_block_text`, extraction_verification_service.py)
mélangeait des réponses de phases différentes du document professeur, sans
respecter leur ordre d'origine. Cause racine : `teacher_correction_blocks`
n'avait aucune colonne de position — `list_by_exercise()` ne pouvait trier
qu'avec `created_at` (ordre d'INSERTION pendant le pipeline), jamais
garanti égal à l'ordre de LECTURE du document.

`RawExtractedBlock` (OCR_Extraction_Agent) porte déjà `page_number`/
`block_order_index` — jamais transmis jusqu'à `TeacherCorrectionBlock`
avant ce fix (cf. Document_Structuring_Agent.py, document_structuring_
service.py, teacher_correction_block_repository.py, mêmes changesets).

2 colonnes nullables (blocs déjà en base : NULL, triés en dernier via
nulls_last() — comportement inchangé pour eux, jamais une régression).

Révision : 2026_08_29_1300-1e8311cc788a_teacher_correction_block_position
Révision précédente : e9b926daabe8
"""
import sqlalchemy as sa
from alembic import op

revision = "1e8311cc788a"
down_revision = "e9b926daabe8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teacher_correction_blocks", sa.Column("page_number", sa.Integer(), nullable=True))
    op.add_column("teacher_correction_blocks", sa.Column("block_order_index", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("teacher_correction_blocks", "block_order_index")
    op.drop_column("teacher_correction_blocks", "page_number")
