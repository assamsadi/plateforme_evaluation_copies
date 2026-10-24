"""
Migration : plafond d'appels LLM par thread (audit "garanties transverses",
Plan D).

jobs.llm_call_count — aucun compteur d'appels LLM n'existait jusqu'ici sur
Job ; rien n'interrompait un traitement anormalement bavard. Remis à zéro à
CHAQUE run (démarrage frais ou reprise, cf. entry_router_node/job_tasks.py::
resume_thread) — jamais cumulatif à travers les reprises (décision actée) :
protège contre une boucle incontrôlée AU SEIN d'une exécution, sans pénaliser
un workflow HITL légitime étalé sur plusieurs jours de pauses/reprises.

Revision ID: 5db7055178a7
Revises: f94f0a5c2a30
Create Date: 2026-08-10 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "5db7055178a7"
down_revision = "f94f0a5c2a30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("llm_call_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("jobs", "llm_call_count", server_default=None)


def downgrade() -> None:
    op.drop_column("jobs", "llm_call_count")
