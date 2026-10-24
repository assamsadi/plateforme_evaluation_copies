"""
Migration — corrige la casse des 2 valeurs ajoutées par c0d1e2f3a4b5.

Bug réel trouvé en vérifiant la migration précédente sur la vraie base :
DataPrivacyRequest.resolution_detail (data_privacy_request.py) est déclaré
via PgEnum(PrivacyResolutionDetail, name="privacy_resolution_detail") SANS
values_callable — contrairement à la plupart des autres enums de ce
codebase (ex. ExtractionEvidenceLevel, qui utilise values_callable=lambda
x: [e.value for e in x]). Sans ce paramètre, SQLAlchemy stocke le NOM du
membre Python (ex. "FULL_DELETION"), jamais sa valeur assignée ("full_
deletion") — confirmé par la migration de création originale
(4cfa9127769c), qui liste bien les 6 valeurs historiques en MAJUSCULES.

c0d1e2f3a4b5 a ajouté 'processing_restricted'/'objection_upheld' en
minuscules (erreur, en suivant par réflexe la convention lowercase
utilisée ailleurs) — jamais utilisables : un flush réel avec
PrivacyResolutionDetail.PROCESSING_RESTRICTED tente d'insérer la chaîne
"PROCESSING_RESTRICTED" (le nom du membre), qui n'existe pas dans le
type, provoquant un InvalidTextRepresentationError vérifié en conditions
réelles avant cette migration.

Les 2 valeurs minuscules ajoutées par erreur restent dans le type (aucun
DROP VALUE possible sur un enum Postgres, cf. migrations précédentes) —
orphelines, inoffensives, jamais utilisées par aucun code.

Révision : 2026_08_22_1830-d1e2f3a4b5c6_fix_privacy_resolution_casing
Révision précédente : c0d1e2f3a4b5
"""
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE privacy_resolution_detail ADD VALUE IF NOT EXISTS 'PROCESSING_RESTRICTED'")
        op.execute("ALTER TYPE privacy_resolution_detail ADD VALUE IF NOT EXISTS 'OBJECTION_UPHELD'")


def downgrade() -> None:
    # PostgreSQL ne supporte pas DROP VALUE sur un type ENUM — même
    # décision actée que les migrations précédentes de ce type.
    pass
