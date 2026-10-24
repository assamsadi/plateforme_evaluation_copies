"""
Repository ValidatedAlternativeAnswer (câblage Priorité 3).

Opération centrale : create_validated_answer — indexation d'une réponse
alternative validée par un professeur pour Comparative_Evaluation_Agent
(mode MULTIPLE_DISTINCT_ANSWERS, cf. docstring du modèle).

Contrairement à ReasoningClarificationRequest (créée PENDING, embedding
calculé plus tard une fois ANSWERED, cf. ReasoningGraphService.
index_clarification_embedding), une ValidatedAlternativeAnswer n'existe
QUE déjà validée — pas d'état intermédiaire à représenter, l'embedding est
donc calculé et persisté en un seul appel atomique.

Appelée par SolutionVariantService.validate_alternative_answer_clarification
(câblage Priorité 1, chantier RAG) sur acceptation professeur d'une
clarification MULTIPLE_DISTINCT_ANSWERS — plus une méthode "prête mais
jamais déclenchée" (docstring historique, corrigé ici).

embedding : Vector(384) natif pgvector (câblage Priorité 2) — testé
empiriquement, la coercition implicite texte->vector via SQLAlchemy/asyncpg
ÉCHOUE (DatatypeMismatchError), le type Python attendu est donc list[float]
directement, jamais une chaîne JSON sérialisée.
"""
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import embed_text
from app.domain.models.assessment.validated_alternative_answer import (
    ValidatedAlternativeAnswer,
)


class ValidatedAlternativeAnswerRepositoryProtocol(Protocol):
    async def create_validated_answer(
        self,
        question_id: uuid.UUID,
        criterion_id: str,
        answer_text: str,
        validated_by_professor_id: uuid.UUID,
    ) -> ValidatedAlternativeAnswer: ...


class SQLAlchemyValidatedAlternativeAnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_validated_answer(
        self,
        question_id: uuid.UUID,
        criterion_id: str,
        answer_text: str,
        validated_by_professor_id: uuid.UUID,
    ) -> ValidatedAlternativeAnswer:
        # embed_text ne lève jamais (cf. sa docstring) — None si
        # sentence-transformers indisponible ou texte vide. La ligne reste
        # créée dans tous les cas (consultable en texte brut), simplement
        # non retrouvable par similarité tant qu'aucun embedding n'existe
        # (même limite assumée que index_clarification_embedding).
        embedding = embed_text(answer_text)
        answer = ValidatedAlternativeAnswer(
            question_id=question_id,
            criterion_id=criterion_id,
            answer_text=answer_text,
            validated_by_professor_id=validated_by_professor_id,
            embedding=embedding,
        )
        self._session.add(answer)
        await self._session.flush()
        return answer
