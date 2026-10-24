"""
Migration — ajoute OLLAMA à l'enum Postgres model_configuration_provider
(réintroduction du fournisseur Ollama pour tests locaux avec des modèles
"cloud" Ollama, ex. gemma4:cloud — cf. ModelProvider.OLLAMA). ALTER TYPE
ADD VALUE (PG >= 12) au lieu de recréer le type : conserve les lignes déjà
en base pour les 3 valeurs existantes, jamais de perte de données.

Révision : 2026_08_23_0900-f8a9b0c1d2e3_add_ollama_provider
Révision précédente : e7f8a9b0c1d2
"""
from alembic import op

revision = "f8a9b0c1d2e3"
down_revision = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE ne peut pas s'exécuter dans le même bloc de
    # transaction implicite qu'un DDL/DML qui l'utiliserait ensuite (PG) —
    # sans effet ici (migration atomique, valeur ajoutée puis jamais
    # utilisée dans la même migration), mais AUTOCOMMIT évite toute
    # ambiguïté avec le mode transactionnel par défaut d'Alembic.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE model_configuration_provider ADD VALUE IF NOT EXISTS 'OLLAMA'")


def downgrade() -> None:
    # PostgreSQL ne supporte pas DROP VALUE sur un type ENUM — recréer le
    # type impliquerait de vérifier/migrer d'éventuelles lignes OLLAMA
    # existantes au préalable, hors mandat d'une downgrade automatique
    # (décision actée : downgrade no-op, cohérent avec le risque d'un DROP
    # TYPE destructif sur une colonne activement utilisée).
    pass
