"""
Migration — régénération à la demande des formats de sortie NotebookLM
(audio Overview / flashcards / vidéo, chantier "régénération NotebookLM").

1. Ajoute 'failed' à l'enum video_overview_status existant (ALTER TYPE ADD
   VALUE, PG >= 12 — conserve les lignes déjà en base pour les 3 valeurs
   existantes, jamais de perte de données, même pattern déjà établi par
   2026_08_23_0900-f8a9b0c1d2e3_add_ollama_provider.py).
2. Crée un nouveau type generation_status (mêmes 4 valeurs) et l'utilise
   pour deux nouvelles colonnes sur student_notebooks : audio_overview_
   status / flashcards_status — avant ce chantier, l'audio et les
   flashcards n'avaient qu'un chemin nullable (succès best-effort implicite
   à la création du notebook), sans état "pending"/"failed" distinguable
   d'un "jamais tenté". Type séparé de video_overview_status (jamais
   renommé) pour ne pas coupler audio/flashcards au nom "vidéo" de l'enum
   historique.
3. Backfill : les lignes ayant déjà un *_path renseigné (généré avec succès
   avant ce chantier) passent à 'ready' — sinon elles resteraient
   'not_requested' à tort, ce qui inverserait le libellé du bouton
   frontend ("Générer" au lieu de "Régénérer").

Révision : 2026_08_31_1000-c1d2e3f4a5b6_notebooklm_regeneration_status
Révision précédente : 974c93e224f7
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c1d2e3f4a5b6"
down_revision = "974c93e224f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE ne peut pas s'exécuter dans le même bloc de
    # transaction implicite qu'un DDL/DML qui l'utiliserait ensuite (PG) —
    # sans effet ici (valeur ajoutée puis jamais utilisée dans cette même
    # migration), mais AUTOCOMMIT évite toute ambiguïté avec le mode
    # transactionnel par défaut d'Alembic (même pattern que add_ollama_
    # provider.py).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE video_overview_status ADD VALUE IF NOT EXISTS 'failed'")

    op.execute("CREATE TYPE generation_status AS ENUM ('not_requested', 'pending', 'ready', 'failed')")

    op.add_column(
        "student_notebooks",
        sa.Column(
            "audio_overview_status",
            postgresql.ENUM(
                "not_requested", "pending", "ready", "failed", name="generation_status", create_type=False,
            ),
            nullable=False,
            server_default="not_requested",
        ),
    )
    op.add_column(
        "student_notebooks",
        sa.Column(
            "flashcards_status",
            postgresql.ENUM(
                "not_requested", "pending", "ready", "failed", name="generation_status", create_type=False,
            ),
            nullable=False,
            server_default="not_requested",
        ),
    )

    op.execute("UPDATE student_notebooks SET audio_overview_status = 'ready' WHERE audio_overview_path IS NOT NULL")
    op.execute("UPDATE student_notebooks SET flashcards_status = 'ready' WHERE flashcards_path IS NOT NULL")


def downgrade() -> None:
    op.drop_column("student_notebooks", "flashcards_status")
    op.drop_column("student_notebooks", "audio_overview_status")
    op.execute("DROP TYPE generation_status")
    # PostgreSQL ne supporte pas DROP VALUE sur un type ENUM — recréer
    # video_overview_status impliquerait de vérifier/migrer d'éventuelles
    # lignes 'failed' existantes au préalable, hors mandat d'une downgrade
    # automatique (décision actée : downgrade no-op pour cette partie,
    # même choix déjà fait par add_ollama_provider.py).
