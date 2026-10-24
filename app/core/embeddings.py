"""
Module d'embeddings sémantiques pour l'infrastructure RAG.

Fournit embed_text(text) -> list[float] | None.

Modèle : sentence-transformers/all-MiniLM-L6-v2 (384 dimensions).
Chargement paresseux (lazy) : le modèle n'est instancié qu'au premier appel,
pas à l'import du module (évite d'alourdir le démarrage du serveur).

Comportement si sentence-transformers est indisponible (paquet non installé,
téléchargement bloqué, etc.) :
  - Un WARNING est émis UNE SEULE FOIS au premier appel (pas à chaque appel).
  - embed_text() retourne None.
  - Le code appelant (Reasoning_Graph_Agent, rag_repository) interprète None
    comme "RAG indisponible → comportement de repli, pas de crash".

Ce module ne doit JAMAIS lever d'exception vers l'extérieur.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Sentinelles d'état du chargement du modèle (None = pas encore tenté)
_model = None
_model_load_failed: bool = False

# Dimension produite par all-MiniLM-L6-v2
EMBEDDING_DIM: int = 384
_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"


def _load_model_once() -> bool:
    """
    Charge le modèle sentence-transformers la première fois qu'il est requis.
    Retourne True si le modèle est disponible, False sinon.
    Ne lève jamais d'exception.
    """
    global _model, _model_load_failed

    if _model is not None:
        return True
    if _model_load_failed:
        return False

    try:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        _model = SentenceTransformer(_MODEL_NAME)
        logger.info("Modèle d'embeddings RAG chargé : %s (%d dim)", _MODEL_NAME, EMBEDDING_DIM)
        return True
    except ImportError:
        _model_load_failed = True
        logger.warning(
            "[RAG] sentence-transformers n'est pas installé. "
            "Le mécanisme few-shot par récupération (RAG) est désactivé. "
            "Le système continue à fonctionner normalement (clarifications HITL inchangées). "
            "Pour activer le RAG, installez sentence-transformers : "
            "pip install sentence-transformers"
        )
        return False
    except Exception as exc:  # noqa: BLE001
        _model_load_failed = True
        logger.warning(
            "[RAG] Impossible de charger le modèle d'embeddings '%s' : %s. "
            "Le mécanisme few-shot par récupération (RAG) est désactivé. "
            "Le système continue à fonctionner normalement.",
            _MODEL_NAME, exc
        )
        return False


def embed_text(text: str) -> list[float] | None:
    """
    Calcule l'embedding sémantique du texte fourni.

    Retourne un vecteur dense de 384 flottants si le modèle est disponible,
    ou None si sentence-transformers est indisponible ou si le texte est vide.
    Ne lève jamais d'exception.

    Args:
        text: Le texte à vectoriser.

    Returns:
        list[float] de longueur EMBEDDING_DIM, ou None.
    """
    if not text or not text.strip():
        return None

    if not _load_model_once():
        return None

    try:
        vector = _model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vector.tolist()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[RAG] Erreur lors du calcul de l'embedding : %s", exc)
        return None


def is_available() -> bool:
    """Retourne True si le modèle d'embeddings est opérationnel."""
    return _load_model_once()
