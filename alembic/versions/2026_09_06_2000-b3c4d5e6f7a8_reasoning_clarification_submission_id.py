"""
Bug réel corrigé (2026-09-06, test réel — écran "Mes résultats" ne pouvait
pas afficher LA justification de l'agent pour une question bloquée) :
ReasoningClarificationRequest.related_entity_id="Question" est partagé par
TOUTE soumission heurtant le même critère de la même question — aucun moyen
fiable de savoir à quelle copie précise une ligne se rapporte. Ajoute
submission_id (nullable — seul Comparative_Evaluation_Agent, flow
student_evaluation, en connaît un ; Reasoning_Graph_Agent et Extraction_
Verification_Agent restent toujours None, cf. docstring modèle).

Corrige au passage un bug de déduplication cross-soumissions dans
comparative_evaluation_node.py (clé désormais (submission_id, question_id,
criterion_id) au lieu de (question_id, criterion_id) seul) — la clarification
d'un second étudiant heurtant le même critère disparaissait silencieusement
avant ce correctif.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-06 20:00:00.000000
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b3c4d5e6f7a8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_reasoning_clarification_requests_submission_id",
        "reasoning_clarification_requests",
        "submissions",
        ["submission_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_reasoning_clarification_requests_submission_id",
        "reasoning_clarification_requests",
        type_="foreignkey",
    )
    op.drop_column("reasoning_clarification_requests", "submission_id")
