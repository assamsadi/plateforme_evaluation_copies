"""
ComparativeEvaluationPattern — table des signatures de méthodes indexées
pour le futur Comparative_Evaluation_Agent.

Chaque ligne représente une méthode de résolution connue et validée pour
une question donnée, encodée sous forme d'un embedding vectoriel calculé
sur une représentation stable de la structure du graphe de raisonnement
(step_type + concept_tags, pas le texte libre, qui varie trop d'un étudiant
à l'autre pour la même méthode).

Usage prévu (Phase 2 — Comparative_Evaluation_Agent) :
  Avant d'évaluer une méthode étudiante inconnue, le système cherche dans
  cette table si une méthode structurellement proche existe déjà parmi
  les variantes validées — permet de détecter une méthode alternative
  non encore connue vs une variante déjà acceptée.

Note d'infrastructure :
  La colonne `embedding` utilise le type pgvector `Vector(384)` si
  l'extension est disponible. Si elle ne l'est pas (environnement de dev
  sans pgvector installé), le service RAG bascule sur un calcul en mémoire
  et la colonne est traitée comme un tableau JSON au niveau ORM.
  L'activation de l'extension pgvector sur l'hôte PostgreSQL de production
  est OBLIGATOIRE avant la mise en production pour garantir le passage à
  l'échelle (index HNSW, recherche O(log N)).
"""
import uuid

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class ComparativeEvaluationPattern(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "comparative_evaluation_patterns"

    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=False, index=True
    )
    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("solution_variants.id"), nullable=True
    )

    # Sérialisation stable de la structure : JSON de {step_types: [...], concept_tags: [...]}
    # Calculée à partir du graphe de raisonnement validé, pas du texte libre.
    pattern_signature: Mapped[str] = mapped_column(Text, nullable=False)

    # Embedding vectoriel de pattern_signature (384 dim, all-MiniLM-L6-v2).
    # Stocké comme JSON si pgvector n'est pas disponible (fallback).
    # Sera migré vers Vector(384) lors de l'activation de l'extension.
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
