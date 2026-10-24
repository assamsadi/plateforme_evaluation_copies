"""
Migration — ajoute PROCESSING_RESTRICTED et OBJECTION_UPHELD à l'enum
Postgres privacy_resolution_detail (cf. PrivacyResolutionDetail,
app/domain/models/system_infrastructure/data_privacy_request.py).

Bug corrigé (audit espace admin) : PrivacyRequestType compte 5 droits
réels (ACCESS_EXPORT/ERASURE/RECTIFICATION/RESTRICTION/OBJECTION), mais
PrivacyResolutionDetail n'avait aucune valeur correspondant réellement à
RESTRICTION ou OBJECTION — un admin traitant l'une de ces deux demandes
était forcé de choisir une résolution sémantiquement fausse (ex.
"rectified" pour une opposition). Ces 2 nouvelles valeurs sont de purs
enregistrements documentaires (même statut que PARTIAL_RETENTION_LEGAL,
cf. docstring DataPrivacyService.complete_erasure) — aucune donnée
utilisateur n'est modifiée automatiquement, le DPO documente le détail
réel dans retention_or_rejection_reason.

ALTER TYPE ADD VALUE (PG >= 12) au lieu de recréer le type — même motif
que les migrations f8a9b0c1d2e3/a9b0c1d2e3f4.

Révision : 2026_08_22_1800-c0d1e2f3a4b5_privacy_resolution_details
Révision précédente : b9c0d1e2f3a4
"""
from alembic import op

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE privacy_resolution_detail ADD VALUE IF NOT EXISTS 'processing_restricted'")
        op.execute("ALTER TYPE privacy_resolution_detail ADD VALUE IF NOT EXISTS 'objection_upheld'")


def downgrade() -> None:
    # PostgreSQL ne supporte pas DROP VALUE sur un type ENUM — même
    # décision actée que les migrations précédentes de ce type
    # (a9b0c1d2e3f4, f8a9b0c1d2e3) : downgrade no-op plutôt qu'un DROP
    # TYPE destructif sur une colonne activement utilisée.
    pass
