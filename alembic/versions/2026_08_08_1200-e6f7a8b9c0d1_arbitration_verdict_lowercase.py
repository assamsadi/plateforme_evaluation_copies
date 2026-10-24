"""
Migration : arbitration_verdict — valeurs relabellisées en minuscules.

Le type était resté 'ACCEPTED'/'REJECTED' depuis la toute première migration
(créé avant l'introduction de values_callable sur les enums du projet), en
désaccord avec la convention utilisée partout ailleurs (arbitration_status,
contestation_status, contestation_type — toutes en minuscules). Le modèle
SQLAlchemy (correction_arbitration.py) est corrigé pour utiliser
values_callable=lambda x: [e.value for e in x], comme ContestationStatus ;
cette migration aligne le type Postgres en conséquence.

RENAME VALUE relabellise en place, sans réécriture de table ni perte des
lignes existantes (projet non encore en production, mais la méthode est
sûre même s'il y en avait).

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-08 12:00:00.000000
"""
from alembic import op

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE arbitration_verdict RENAME VALUE 'ACCEPTED' TO 'accepted'")
    op.execute("ALTER TYPE arbitration_verdict RENAME VALUE 'REJECTED' TO 'rejected'")


def downgrade() -> None:
    op.execute("ALTER TYPE arbitration_verdict RENAME VALUE 'accepted' TO 'ACCEPTED'")
    op.execute("ALTER TYPE arbitration_verdict RENAME VALUE 'rejected' TO 'REJECTED'")
