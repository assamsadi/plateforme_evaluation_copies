"""
ValidatedAlternativeAnswer — réponses étudiantes alternatives VALIDÉES par
un professeur, indexées pour Comparative_Evaluation_Agent (mode
MULTIPLE_DISTINCT_ANSWERS).

Câblage Priorité 3 — remplace l'usage erroné de reasoning_clarification_
requests dans _eval_multiple_distinct_answers (cf. son docstring) : cette
dernière table indexe des CLARIFICATIONS SUR LA CORRECTION DU PROFESSEUR
(mécanisme few-shot §10ter, embedding calculé sur agent_question — la
question posée par l'agent, pas une réponse d'étudiant), pas des réponses
d'étudiants validées comme correctes.

ComparativeEvaluationPattern (déjà existante) n'est pas non plus adaptée :
pattern_signature y encode la STRUCTURE du graphe de raisonnement
(step_types + concept_tags), jamais le texte libre d'une réponse finale
(cf. son docstring — "pas le texte libre, qui varie trop d'un étudiant à
l'autre pour la même méthode"), et variant_id la lie à une SolutionVariant
professeur, pas à une réponse d'étudiant ponctuelle.

Une ligne ici = un texte de réponse (answer_text) qu'un professeur a
explicitement validé comme une formulation alternative correcte pour un
(question_id, criterion_id) donné — typiquement en résolution d'un
ClarificationRequest MULTIPLE_DISTINCT_ANSWERS (cf. Comparative_Evaluation_
Agent._eval_multiple_distinct_answers, branche "réponse alternative inédite
et cohérente"). criterion_id référence l'id du critère DANS le JSON
Bareme.criteria — même corrélation logique (pas une vraie FK SQL) que
EvaluationCriteria.criterion_id.

Déclencheur HITL (câblage Priorité 1, chantier RAG) : create_validated_answer
est désormais réellement appelée par SolutionVariantService.validate_
alternative_answer_clarification, via POST /clarifications/{id}/
validate-alternative-answer — plus une fonction "prête mais jamais
déclenchée" (docstring historique, corrigé ici).

Vector(384) natif pgvector (câblage Priorité 2) — cf. docstring du champ
embedding ci-dessous.
"""
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class ValidatedAlternativeAnswer(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "validated_alternative_answers"

    question_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("questions.id"), nullable=False, index=True
    )
    # Corrélation logique vers Bareme.criteria[].id (JSON) — pas une FK SQL,
    # même principe que EvaluationCriteria.criterion_id.
    criterion_id: Mapped[str] = mapped_column(Text, nullable=False)

    answer_text: Mapped[str] = mapped_column(Text, nullable=False)

    validated_by_professor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=False
    )

    # Embedding vectoriel de answer_text (384 dim, all-MiniLM-L6-v2).
    # Vector(384) natif pgvector — testé empiriquement (câblage Priorité 2) :
    # la coercition implicite texte->vector via SQLAlchemy/asyncpg ÉCHOUE
    # (DatatypeMismatchError), le typage Python doit donc correspondre au
    # type SQL réel. Migration requiert pgvector actif (échec explicite
    # sinon) — plus de repli TEXT possible pour cette colonne.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
