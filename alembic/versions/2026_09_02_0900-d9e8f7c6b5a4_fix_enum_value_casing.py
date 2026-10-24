"""
Fix : deux valeurs d'enum ajoutées en minuscules par erreur dans la
migration d5e6f7a8b9c0 (submission_status.pending_arbitration,
integrity_trigger_type.systematic_contestation), alors que TOUTES les
autres valeurs de ces deux enums ont été créées en MAJUSCULES
(migration 4cfa9127769c). SubmissionStatus/IntegrityTriggerType n'utilisent
pas values_callable (cf. submission.py, integrity_alert.py) — SQLAlchemy
persiste donc le NOM du membre Python (majuscules), jamais sa valeur.

Conséquence réelle confirmée en test (2026-09-02) : toute tentative de
transition vers SubmissionStatus.PENDING_ARBITRATION ou de création d'une
IntegrityAlert avec IntegrityTriggerType.SYSTEMATIC_CONTESTATION échoue
avec asyncpg.exceptions.InvalidTextRepresentationError, la valeur
"PENDING_ARBITRATION"/"SYSTEMATIC_CONTESTATION" n'existant pas côté
Postgres (seules les variantes minuscules orphelines y figurent).

Postgres ne permet pas de renommer/retirer une valeur d'enum sans
recréer tout le type (opération plus risquée, non nécessaire ici) — on
ajoute simplement les libellés correctement casés. Les deux valeurs
minuscules restent en base, inertes (jamais produites par ce code), comme
déjà documenté dans le downgrade de d5e6f7a8b9c0 pour ce même type de
limitation.

Revision ID: d9e8f7c6b5a4
Revises: c1d2e3f4a5b6
Create Date: 2026-09-02 09:00:00.000000
"""
from alembic import op

revision = "d9e8f7c6b5a4"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE submission_status ADD VALUE IF NOT EXISTS 'PENDING_ARBITRATION'")
    op.execute("ALTER TYPE integrity_trigger_type ADD VALUE IF NOT EXISTS 'SYSTEMATIC_CONTESTATION'")


def downgrade() -> None:
    # Postgres ne permet pas de retirer une valeur d'enum — même limitation
    # documentée dans d5e6f7a8b9c0.downgrade(), rien à défaire ici.
    pass
