"""
Migration — Vector(384) natif pgvector, câblage Priorité 2 (chantier RAG).

Convertit reasoning_clarification_requests.embedding et
validated_alternative_answers.embedding de TEXT/JSON vers vector(384)
natif pgvector, avec conversion IN PLACE des données déjà existantes
(ALTER COLUMN ... TYPE vector(384) USING embedding::vector — le texte JSON
déjà stocké, ex. "[0.12, -0.03, ...]", est directement compatible avec la
syntaxe d'entrée native de pgvector, aucune clarification/réponse déjà
indexée n'est perdue). NULL reste NULL (embedding pas encore calculé).

ÉCHEC EXPLICITE si l'extension vector n'est pas active sur l'instance
cible — AUCUN repli dégradé silencieux ici (contrairement à la toute
première migration RAG, a9b8c7d6e5f4, qui ne faisait qu'installer
l'extension en best-effort avant qu'aucun code n'en dépende). Cette
migration-ci convertit des colonnes vers un type qui EXIGE l'extension ;
un skip silencieux laisserait le schéma DB en TEXT alors que le code
Python (ORM typé Vector(384), cf. app/domain/models/assessment/
reasoning_clarification_request.py et validated_alternative_answer.py)
suppose déjà des vecteurs natifs — écart schéma/code non détectable avant
un crash en production. Testé empiriquement (câblage Priorité 2) : la
coercition implicite texte->vector via SQLAlchemy/asyncpg à l'écriture
échoue (DatatypeMismatchError) si la colonne réelle n'est pas vector.

Index HNSW (vector_cosine_ops, cohérent avec l'opérateur `<=>` déjà utilisé
par search_similar()) sur les deux colonnes — pas de paramètre `lists` à
recalibrer contrairement à IVFFLAT (tables qui démarrent vides et
grossissent avec l'usage).

Révision : 2026_08_13_1100-f6a7b8c9d0e1_native_vector_embeddings
Révision précédente : e5f6a7b8c9d0
"""
import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

_TABLES = ("reasoning_clarification_requests", "validated_alternative_answers")


def _require_pgvector() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    if result.first() is None:
        raise RuntimeError(
            "Migration f6a7b8c9d0e1 (Vector(384) natif) requiert l'extension "
            "pgvector active sur cette instance PostgreSQL — elle n'est PAS "
            "détectée (aucune ligne dans pg_extension pour 'vector'). "
            "Aucun repli automatique ici (contrairement à la migration RAG "
            "initiale a9b8c7d6e5f4) : le code applicatif (modèles ORM "
            "ReasoningClarificationRequest.embedding / "
            "ValidatedAlternativeAnswer.embedding) est typé Vector(384) et "
            "échouera à l'exécution contre une colonne TEXT. "
            "Activez l'extension AVANT de relancer cette migration : "
            "CREATE EXTENSION IF NOT EXISTS vector; "
            "(nécessite le paquet pgvector installé sur l'hôte PostgreSQL — "
            "cf. checklist de déploiement, cf. rapport de ce chantier)."
        )


def upgrade() -> None:
    _require_pgvector()

    for table in _TABLES:
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector(384) "
                f"USING embedding::vector"
            )
        )
        op.execute(
            sa.text(
                f"CREATE INDEX ix_{table}_embedding_hnsw ON {table} "
                f"USING hnsw (embedding vector_cosine_ops)"
            )
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(sa.text(f"DROP INDEX IF EXISTS ix_{table}_embedding_hnsw"))
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN embedding TYPE text "
                f"USING embedding::text"
            )
        )
