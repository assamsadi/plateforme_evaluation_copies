"""
RAG Repository — Recherche de similarité vectorielle générique.

Fournit search_similar(), réutilisable par :
  - Reasoning_Graph_Agent (few-shot section 10ter) : clarifications résolues
    (reasoning_clarification_requests).
  - Comparative_Evaluation_Agent (mode MULTIPLE_DISTINCT_ANSWERS, câblage
    Priorité 3) : réponses alternatives validées par un professeur
    (validated_alternative_answers), filtrées par question_id/criterion_id
    via filter_params (jamais interpolées dans filter_clauses).

Architecture de fallback à deux niveaux :
  Niveau 1 — pgvector SQL (production) :
    Requête SQL avec l'opérateur cosinus `<=>` de pgvector.
    Nécessite que l'extension `vector` soit installée sur l'hôte Postgres.
    Retourne exactement top_k résultats filtrés par seuil.
  Niveau 2 — NumPy en mémoire (dev / test) :
    Charge tous les enregistrements ayant un embedding non nul et calcule
    la similarité cosinus en Python via NumPy.
    Correct pour les petits volumes, mais ne passe PAS à l'échelle en
    production (O(N) lectures + calcul en mémoire).

AVERTISSEMENT INFRA :
    L'installation de l'extension pgvector sur l'hôte PostgreSQL est
    OBLIGATOIRE avant toute mise en production. Le fallback NumPy est
    uniquement destiné à l'environnement de développement et aux tests
    unitaires. En production sans pgvector, chaque appel à search_similar()
    charge la totalité de la table en mémoire.

Point de calibration :
    similarity_threshold est réglé par défaut à 0.85 dans Settings.
    Cette valeur est empirique et devra être ajustée après observation
    des résultats en usage réel (ni trop stricte = jamais de match,
    ni trop laxiste = faux positifs qui appliquent une mauvaise réponse).
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Détecté une seule fois au premier appel (pas à l'import pour éviter une
# connexion DB prématurée).
_pgvector_available: bool | None = None


@dataclass
class SimilarityMatch:
    """Résultat d'une recherche de similarité."""
    id: uuid.UUID
    similarity: float  # [0.0, 1.0], 1.0 = identique
    # Données brutes de la ligne — utilisées différemment selon le contexte
    # (clarification résolue : professor_answer ; pattern : variant_id, etc.)
    payload: dict[str, Any]


async def _check_pgvector(session: AsyncSession) -> bool:
    """Détecte si l'extension pgvector est disponible en base de données."""
    global _pgvector_available
    if _pgvector_available is not None:
        return _pgvector_available
    try:
        result = await session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        _pgvector_available = result.first() is not None
        if _pgvector_available:
            logger.info("[RAG] Extension pgvector détectée : recherche vectorielle SQL activée.")
        else:
            logger.warning(
                "[RAG] Extension pgvector NON disponible en base de données. "
                "Basculement sur le calcul de similarité cosinus en mémoire (NumPy). "
                "Ce mode ne passe pas à l'échelle en production. "
                "L'installation du paquet OS postgresql-pgvector sur l'hôte "
                "PostgreSQL est OBLIGATOIRE avant la mise en production."
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[RAG] Impossible de vérifier la disponibilité de pgvector : %s", exc)
        _pgvector_available = False
    return _pgvector_available


def _cosine_similarity_numpy(a: list[float], b: list[float]) -> float:
    """Calcule la similarité cosinus entre deux vecteurs via NumPy."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


async def search_similar(
    session: AsyncSession,
    embedding_query: list[float],
    table_name: str,
    embedding_column: str,
    id_column: str,
    payload_columns: list[str],
    filter_clauses: str | None = None,
    filter_params: dict[str, Any] | None = None,
    top_k: int = 5,
    similarity_threshold: float = 0.85,
) -> list[SimilarityMatch]:
    """
    Recherche les enregistrements les plus similaires à embedding_query.

    Args:
        session: Session SQLAlchemy asynchrone.
        embedding_query: Vecteur de requête (384 floats pour all-MiniLM-L6-v2).
        table_name: Nom de la table cible.
        embedding_column: Nom de la colonne contenant l'embedding (Text/JSON).
        id_column: Nom de la colonne identifiant (UUID).
        payload_columns: Colonnes supplémentaires à retourner dans SimilarityMatch.payload.
        filter_clauses: Clause WHERE SQL additionnelle (ex. "status = 'answered'").
            Les valeurs DYNAMIQUES (jamais des littéraux constants au code)
            doivent être passées via filter_params en paramètres nommés
            (ex. "question_id = :question_id"), jamais interpolées
            directement dans cette chaîne — filter_clauses est concaténée
            telle quelle dans le SQL brut (injection sinon).
        filter_params: Valeurs des paramètres nommés référencés par
            filter_clauses (ex. {"question_id": "..."}) — liées via
            l'API de binding SQLAlchemy, jamais interpolées en texte.
        top_k: Nombre maximum de résultats retournés.
        similarity_threshold: Seuil minimal de similarité cosinus [0, 1].

    Returns:
        Liste de SimilarityMatch triée par similarité décroissante.
    """
    if not embedding_query:
        return []

    use_pgvector = await _check_pgvector(session)
    bind_params: dict[str, Any] = dict(filter_params or {})

    # Colonnes à sélectionner
    select_cols = ", ".join([id_column, embedding_column] + payload_columns)
    where_part = f"AND ({filter_clauses})" if filter_clauses else ""
    base_query = (
        f"SELECT {select_cols} FROM {table_name} "
        f"WHERE {embedding_column} IS NOT NULL {where_part}"
    )

    if use_pgvector:
        # Mode pgvector : distance cosinus SQL (1 - distance = similarité)
        # L'opérateur <=> retourne une distance cosinus [0, 2] normalisée en [0, 1].
        vec_literal = "[" + ",".join(str(v) for v in embedding_query) + "]"
        sql = text(
            f"SELECT {select_cols}, "
            f"1 - ({embedding_column}::vector <=> '{vec_literal}'::vector) AS similarity "
            f"FROM {table_name} "
            f"WHERE {embedding_column} IS NOT NULL {where_part} "
            f"ORDER BY similarity DESC LIMIT :top_k"
        )
        try:
            result = await session.execute(sql, {**bind_params, "top_k": top_k})
            rows = result.fetchall()
            matches = []
            for row in rows:
                row_dict = dict(row._mapping)
                similarity = float(row_dict.pop("similarity", 0.0))
                if similarity >= similarity_threshold:
                    matches.append(SimilarityMatch(
                        id=row_dict[id_column],
                        similarity=similarity,
                        payload={col: row_dict.get(col) for col in payload_columns},
                    ))
            return matches
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[RAG] Erreur lors de la recherche pgvector SQL (%s), "
                "basculement sur NumPy : %s", table_name, exc
            )
            # Fallback forcé si la requête SQL échoue malgré l'extension détectée

    # Mode fallback NumPy : lecture complète de la table
    try:
        result = await session.execute(text(f"{base_query} LIMIT 10000"), bind_params)
        rows = result.fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.error("[RAG] Impossible de lire la table %s : %s", table_name, exc)
        return []

    candidates: list[SimilarityMatch] = []
    for row in rows:
        row_dict = dict(row._mapping)
        raw_embedding = row_dict.get(embedding_column)
        if not raw_embedding:
            continue
        try:
            stored_vec: list[float] = (
                raw_embedding if isinstance(raw_embedding, list)
                else json.loads(raw_embedding)
            )
        except (ValueError, TypeError):
            continue

        sim = _cosine_similarity_numpy(embedding_query, stored_vec)
        if sim >= similarity_threshold:
            candidates.append(SimilarityMatch(
                id=row_dict[id_column],
                similarity=sim,
                payload={col: row_dict.get(col) for col in payload_columns},
            ))

    candidates.sort(key=lambda m: m.similarity, reverse=True)
    return candidates[:top_k]
