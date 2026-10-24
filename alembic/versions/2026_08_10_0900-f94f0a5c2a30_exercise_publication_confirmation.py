"""
Migration : confirmation professeur explicite avant publication (audit
"garanties transverses", Plan B).

exercises.publication_confirmed_at / .publication_confirmed_hash — la
vérification technique de complétude (_check_completeness, déjà en place)
ne suffit pas : rien n'exigeait jusqu'ici une confirmation humaine explicite
du résumé (barème par question, variante de référence) avant publish().

Le hash (pas une simple date) capture le contenu réellement confirmé —
barème + variante de référence par question — pour que toute modification
de cet état après confirmation invalide automatiquement la confirmation
(publish() recalcule et compare, cf. exercise_service.py). Aucune valeur
par défaut rétroactive : toutes les lignes existantes démarrent
NULL/non-confirmées, cohérent avec "rien ne le faisait avant" — un exercice
déjà publié avant cette migration devra être reconfirmé au prochain
changement de statut EXAM/HOMEWORK (aucun exercice déjà publié n'est
re-bloqué rétroactivement, publish() ne revérifie qu'au moment d'un nouveau
changement de statut vers EXAM/HOMEWORK).

Revision ID: f94f0a5c2a30
Revises: f6644dc544d9
Create Date: 2026-08-10 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "f94f0a5c2a30"
down_revision = "f6644dc544d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exercises",
        sa.Column("publication_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "exercises",
        sa.Column("publication_confirmed_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("exercises", "publication_confirmed_hash")
    op.drop_column("exercises", "publication_confirmed_at")
