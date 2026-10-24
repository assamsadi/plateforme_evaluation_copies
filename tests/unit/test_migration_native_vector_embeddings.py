"""
Test unitaire — garde-fou de la migration f6a7b8c9d0e1 (Vector(384) natif
pgvector, câblage Priorité 2, chantier RAG).

Vit ici (tests/unit/) plutôt que tests/integration/ : pur, connexion
mockée, aucun DB réel requis — tests/integration/conftest.py applique un
fixture autouse db_session (async) à tout ce dossier, inadapté à un test
synchrone qui n'a besoin que de vérifier un contrôle Python pur.

Ne teste jamais contre une vraie instance sans pgvector (aucune disponible
dans cet environnement — le Docker de ce projet ET l'installation locale
directe ont tous deux pgvector actif, cf. rapport du chantier).
"""
import importlib.util
import pathlib
from unittest.mock import MagicMock

import pytest


def _load_migration_module(name: str):
    migration_path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "alembic" / "versions" / "2026_08_13_1100-f6a7b8c9d0e1_native_vector_embeddings.py"
    )
    spec = importlib.util.spec_from_file_location(name, migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_migration_require_pgvector_raises_explicitly_when_absent(monkeypatch):
    """
    Câblage Priorité 2 — la migration DOIT échouer explicitement (jamais un
    repli dégradé silencieux) si pgvector n'est pas actif.
    """
    migration = _load_migration_module("migration_f6a7b8c9d0e1_absent")

    mock_result = MagicMock()
    mock_result.first.return_value = None  # pg_extension : aucune ligne -> absent
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_result

    monkeypatch.setattr(migration.op, "get_bind", lambda: mock_conn)
    with pytest.raises(RuntimeError, match="pgvector"):
        migration._require_pgvector()


def test_migration_require_pgvector_passes_when_present(monkeypatch):
    migration = _load_migration_module("migration_f6a7b8c9d0e1_present")

    mock_result = MagicMock()
    mock_result.first.return_value = (1,)  # pg_extension : une ligne -> présent
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_result

    monkeypatch.setattr(migration.op, "get_bind", lambda: mock_conn)
    migration._require_pgvector()  # ne lève rien
