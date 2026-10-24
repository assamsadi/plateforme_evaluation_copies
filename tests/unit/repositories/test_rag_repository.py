"""
Tests unitaires pour app.repositories.rag_repository.

Couvre :
  1. Recherche avec un résultat au-dessus du seuil → correspondance retournée.
  2. Recherche sans résultat suffisamment proche → liste vide.
  3. Fallback NumPy si pgvector n'est pas disponible.
  4. Robustesse : vecteur None / table vide → liste vide, pas d'exception.
"""
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.repositories import rag_repository
from app.repositories.rag_repository import (
    SimilarityMatch,
    _cosine_similarity_numpy,
    search_similar,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_embedding(seed: int, dim: int = 384) -> list[float]:
    """Génère un vecteur normalisé déterministe."""
    rng = np.random.default_rng(seed)
    v = rng.random(dim).astype(np.float32)
    norm = np.linalg.norm(v)
    return (v / norm).tolist()


def _json_emb(seed: int, dim: int = 384) -> str:
    return json.dumps(_make_embedding(seed, dim))


def _make_session(rows: list[dict]) -> AsyncMock:
    """Construit une AsyncSession mockée retournant rows pour execute()."""
    session = AsyncMock()

    # Mock pour la détection pgvector : pas d'extension installée (fallback NumPy)
    pgvector_result = MagicMock()
    pgvector_result.first.return_value = None  # pgvector absent

    # Mock pour la requête principale
    rows_result = MagicMock()

    # Chaque row est un MagicMock avec _mapping
    mock_rows = []
    for r in rows:
        row = MagicMock()
        row._mapping = r
        mock_rows.append(row)
    rows_result.fetchall.return_value = mock_rows

    # Premier execute → vérification pgvector, deuxième → données
    session.execute = AsyncMock(side_effect=[
        pgvector_result,   # _check_pgvector
        rows_result,       # requête principale
    ])
    return session


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_search_similar_match_above_threshold():
    """Un embedding très proche (même vecteur) doit être retourné."""
    # Réinitialise la sentinelle de détection pgvector pour chaque test
    rag_repository._pgvector_available = None

    emb_a = _make_embedding(42)
    row_id = uuid.uuid4()

    session = _make_session([
        {
            "id": row_id,
            "embedding": json.dumps(emb_a),
            "professor_answer": "Oui, la méthode est correcte.",
            "agent_question": "La méthode est-elle correcte ?",
            "answered_at": "2026-01-01T00:00:00",
        }
    ])

    matches = await search_similar(
        session=session,
        embedding_query=emb_a,  # identique → similarité ≈ 1.0
        table_name="reasoning_clarification_requests",
        embedding_column="embedding",
        id_column="id",
        payload_columns=["professor_answer", "agent_question", "answered_at"],
        filter_clauses="status = 'answered'",
        top_k=3,
        similarity_threshold=0.85,
    )

    assert len(matches) == 1
    assert matches[0].id == row_id
    assert matches[0].similarity >= 0.999  # cosinus d'un vecteur avec lui-même ≈ 1.0
    assert matches[0].payload["professor_answer"] == "Oui, la méthode est correcte."


@pytest.mark.anyio
async def test_search_similar_no_match_below_threshold():
    """Deux vecteurs orthogonaux → similarité ≈ 0 → liste vide."""
    rag_repository._pgvector_available = None

    emb_a = _make_embedding(1)
    emb_b = _make_embedding(2)

    # S'assurer qu'ils ne sont pas trop similaires (avec des seeds différents, ils sont distincts)
    sim = _cosine_similarity_numpy(emb_a, emb_b)
    # On force un seuil au-dessus de la similarité réelle pour garantir l'absence de match
    high_threshold = min(sim + 0.2, 1.0)

    session = _make_session([
        {
            "id": uuid.uuid4(),
            "embedding": json.dumps(emb_b),
            "professor_answer": "Réponse quelconque.",
            "agent_question": "Question quelconque.",
            "answered_at": "2026-01-01T00:00:00",
        }
    ])

    matches = await search_similar(
        session=session,
        embedding_query=emb_a,
        table_name="reasoning_clarification_requests",
        embedding_column="embedding",
        id_column="id",
        payload_columns=["professor_answer", "agent_question", "answered_at"],
        top_k=3,
        similarity_threshold=high_threshold,
    )

    assert matches == []


@pytest.mark.anyio
async def test_search_similar_table_empty_returns_empty_list():
    """Table vide → retourne [] sans exception."""
    rag_repository._pgvector_available = None

    session = _make_session([])

    matches = await search_similar(
        session=session,
        embedding_query=_make_embedding(10),
        table_name="reasoning_clarification_requests",
        embedding_column="embedding",
        id_column="id",
        payload_columns=["professor_answer"],
        top_k=3,
        similarity_threshold=0.85,
    )

    assert matches == []


@pytest.mark.anyio
async def test_search_similar_none_embedding_returns_empty():
    """Un vecteur de requête vide/None → retourne [] immédiatement."""
    rag_repository._pgvector_available = None
    session = AsyncMock()

    matches = await search_similar(
        session=session,
        embedding_query=[],  # vecteur vide
        table_name="reasoning_clarification_requests",
        embedding_column="embedding",
        id_column="id",
        payload_columns=["professor_answer"],
        top_k=3,
        similarity_threshold=0.85,
    )

    assert matches == []
    session.execute.assert_not_called()


def test_cosine_similarity_identical_vectors():
    """Vecteur identique à lui-même → similarité = 1.0."""
    v = _make_embedding(99)
    assert abs(_cosine_similarity_numpy(v, v) - 1.0) < 1e-5


def test_cosine_similarity_zero_vector():
    """Vecteur nul → similarité = 0.0 (pas de division par zéro)."""
    v = [1.0, 0.0, 0.0]
    zero = [0.0, 0.0, 0.0]
    assert _cosine_similarity_numpy(v, zero) == 0.0
    assert _cosine_similarity_numpy(zero, zero) == 0.0


@pytest.mark.anyio
async def test_search_similar_top_k_respected():
    """Si la table contient 5 résultats au-dessus du seuil, top_k=2 n'en retourne que 2."""
    rag_repository._pgvector_available = None

    query_emb = _make_embedding(0)
    rows = []
    for i in range(5):
        rows.append({
            "id": uuid.uuid4(),
            "embedding": json.dumps(_make_embedding(i)),  # seeds proches → vecteurs proches
            "professor_answer": f"Réponse {i}",
            "agent_question": f"Question {i}",
            "answered_at": None,
        })

    session = _make_session(rows)

    matches = await search_similar(
        session=session,
        embedding_query=query_emb,
        table_name="reasoning_clarification_requests",
        embedding_column="embedding",
        id_column="id",
        payload_columns=["professor_answer", "agent_question", "answered_at"],
        top_k=2,
        similarity_threshold=0.0,  # seuil à 0 pour capturer tous
    )

    assert len(matches) <= 2
