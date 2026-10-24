"""
Migration : TeacherCorrectionBlock.ocr_confidence (B11, backlog_bugs_c2pct.md) —
confiance OCR combinée (RawExtractedBlock.confidence_score, déjà après
relecture ciblée éventuelle), jusqu'ici jamais transmise jusqu'à l'interface
professeur. Colonne nullable : blocs créés avant ce champ, ou tout bloc sans
confiance OCR à proprement parler. Flag visible non-bloquant côté lecture
(TeacherCorrectionBlockRead.is_low_ocr_confidence, calculé, jamais stocké) —
ne bloque jamais la publication, contrairement à UNRESOLVED_NO_LABEL.

Révision : 2026_08_29_1900-974c93e224f7_teacher_correction_block_ocr_confidence
Révision précédente : 736c2945052c
"""
import sqlalchemy as sa
from alembic import op

revision = "974c93e224f7"
down_revision = "736c2945052c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teacher_correction_blocks",
        sa.Column("ocr_confidence", sa.Numeric(4, 3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("teacher_correction_blocks", "ocr_confidence")
