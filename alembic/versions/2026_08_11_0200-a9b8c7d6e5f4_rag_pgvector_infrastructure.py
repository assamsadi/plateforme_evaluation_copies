"""
Migration RAG — Infrastructure pgvector de bout en bout.

Trois opérations :
  1. CREATE EXTENSION IF NOT EXISTS vector
     Installe l'extension pgvector. Si le paquet OS postgresql-pgvector n'est
     pas installé sur l'hôte PostgreSQL, cette instruction échoue avec
     FeatureNotSupportedError. La migration intercepte cette erreur, émet un
     WARNING explicite et continue sans bloquer — le schéma reste valide,
     seule la recherche vectorielle SQL est désactivée (fallback NumPy actif).

     ⚠ AVERTISSEMENT INFRA : L'extension DOIT être installée sur l'hôte
     PostgreSQL avant la mise en production. Sur Debian/Ubuntu :
       apt install postgresql-16-pgvector
     Sur la base managée Azure Database for PostgreSQL :
       CREATE EXTENSION vector; (disponible nativement sur PG >= 13)

  2. ALTER TABLE reasoning_clarification_requests
     ADD COLUMN embedding TEXT NULL
     Stocke l'embedding vectoriel sérialisé en JSON (tableau de floats).
     La migration vers Vector(384) natif (type pgvector) sera réalisée
     par l'équipe infra une fois l'extension activée en production.

  3. CREATE TABLE comparative_evaluation_patterns
     Table d'index des signatures de méthodes pour Comparative_Evaluation_Agent
     (Phase 2). Chaque ligne représente une méthode de résolution validée
     indexée par embedding pour la recherche de méthodes similaires.

Révision : 2026_08_11_0200-a9b8c7d6e5f4_rag_pgvector_infrastructure
Révision précédente : a1c3e7f92b41
"""
import logging

import sqlalchemy as sa
from alembic import op

revision = "a9b8c7d6e5f4"
down_revision = "a1c3e7f92b41"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Extension pgvector (installation gracieuse)
    # ------------------------------------------------------------------
    conn = op.get_bind()
    try:
        conn.execute(sa.text("SAVEPOINT vector_ext_sp;"))
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector;"))
        conn.execute(sa.text("RELEASE SAVEPOINT vector_ext_sp;"))
        logger.info("[Migration RAG] Extension pgvector installée avec succès.")
    except Exception as exc:
        conn.execute(sa.text("ROLLBACK TO SAVEPOINT vector_ext_sp;"))
        logger.warning(
            "[Migration RAG] Impossible d'installer l'extension pgvector : %s. "
            "Le mécanisme RAG de recherche vectorielle SQL est désactivé. "
            "Le système fonctionnera en mode fallback NumPy (non scalable en production).",
            exc,
        )
        # On NE fait pas de raise : la migration doit continuer et réussir
        # même sans l'extension. Le reste du schéma est indépendant de pgvector.

    # ------------------------------------------------------------------
    # 2. Colonne embedding dans reasoning_clarification_requests
    # ------------------------------------------------------------------
    op.add_column(
        "reasoning_clarification_requests",
        sa.Column("embedding", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. Table comparative_evaluation_patterns
    # ------------------------------------------------------------------
    op.create_table(
        "comparative_evaluation_patterns",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "question_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("questions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "variant_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("solution_variants.id"),
            nullable=True,
        ),
        sa.Column("pattern_signature", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("comparative_evaluation_patterns")
    op.drop_column("reasoning_clarification_requests", "embedding")
    # On ne supprime pas l'extension vector en downgrade : elle peut être
    # utilisée par d'autres éléments du schéma non gérés par cette migration.
