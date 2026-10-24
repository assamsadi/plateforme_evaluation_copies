"""
ReasoningClarificationRequest = mécanisme d'Active Learning : quand un
agent rencontre une partie FLOUE de la correction du professeur (ou d'un
barème, ou d'une décomposition de question), il ne doit jamais deviner
— il pose une question précise et ATTEND la réponse avant de progresser.

Initialement conçu pour le Reasoning Graph Agent (construction du graphe
de raisonnement pour une SolutionVariant), ce mécanisme est élargi à
tout agent qui rencontre une ambiguïté nécessitant une intervention
humaine : Document_Structuring_Agent (décomposition Question / section),
Variant_Generation_Agent (critères Bareme), etc.

Le champ `variant_id` reste présent mais nullable : pour les demandes
ciblant une variante, il est rempli. Pour les autres, on utilise la
référence polymorphe (related_entity_type, related_entity_id) qui suit
exactement le même pattern qu'AgentDecisionLog.

uncleared_content décrit la partie de la correction encore SANS étape
créée (le flou est détecté AVANT la création de la ReasoningStep,
jamais après — donc pas de correction rétroactive d'une étape déjà
enregistrée).

resulting_step_id trace, une fois la réponse obtenue, quelle étape a pu
être créée grâce à cette clarification — utile pour l'explicabilité et
pour la boucle d'apprentissage few-shot (§6) : chaque paire
question/réponse résolue est indexée en base vectorielle pour aider
l'agent sur des cas similaires futurs.

Les demandes sont présentées groupées au professeur (jamais une par
une), via `present_pending_requests(variant_id_or_entity)` dans le
service dédié.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Enum as PgEnum, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin, UUIDPKMixin


class ClarificationStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"


class ComparativeClarificationKind(StrEnum):
    """
    Discriminant (correctif AMBIGUOUS_COHERENCE) — MULTIPLE_DISTINCT_ANSWERS
    (Comparative_Evaluation_Agent) produit deux sous-types de clarification
    qui partagent EXACTEMENT la même forme (related_entity_type="Question",
    criterion_id renseigné, related_field identique) : aucun champ existant
    ne permettait de les distinguer avant ce champ (seul proposed_answer is
    None différait — un signal implicite, jamais conçu comme discriminant).
    Nécessaire pour que chaque endpoint de résolution (sémantiques
    différentes : accept/reject une réponse candidate VS trancher
    coherent/incoherent) rejette une ligne du mauvais type. None pour toute
    ligne qui n'origine pas de Comparative_Evaluation_Agent (Reasoning_
    Graph_Agent, Extraction_Verification_Agent).
    """
    ALTERNATIVE_ANSWER = "alternative_answer"
    COHERENCE_AMBIGUITY = "coherence_ambiguity"


class ClarificationSeverity(StrEnum):
    """
    Phase 6 (élargissement pour Extraction_Verification_Agent, Phase 4) :
    BLOCKING = aucune consommation en aval sans validation explicite du
    professeur (bloque publish(), cf. exercise_service._check_completeness).
    WARNING = utilisable provisoirement, professeur informé, ne bloque pas.
    INFORMATIONAL = simple trace, aucun impact. Les lignes créées avant
    l'existence de ce champ (Reasoning_Graph_Agent) sont rétroactivement
    BLOCKING (migration f6644dc544d9) — comportement de blocage inchangé
    pour ce mécanisme, qui n'avait jamais que des demandes bloquantes."""
    BLOCKING = "blocking"
    WARNING = "warning"
    INFORMATIONAL = "informational"


class ReasoningClarificationRequest(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "reasoning_clarification_requests"

    variant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("solution_variants.id"), nullable=True
    )
    # Référence polymorphe — même pattern qu'AgentDecisionLog.
    # Ex: ("bareme", <bareme_id>), ("question", <question_id>)
    # Mutuellement exclusif avec variant_id (l'un ou l'autre est rempli).
    related_entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    # Ajouté 2026-09-06 (test réel — écran "Mes résultats" ne pouvait pas
    # afficher LA vraie justification de l'agent pour une question bloquée :
    # related_entity_id="Question" est partagé par TOUTES les soumissions qui
    # heurtent le même critère, aucun moyen fiable de savoir laquelle une
    # ligne concerne). Nullable : seul Comparative_Evaluation_Agent (flow
    # student_evaluation, contexte soumission réel) le renseigne — Reasoning_
    # Graph_Agent (variant_id, exercise_setup) et Extraction_Verification_
    # Agent (bareme/question, exercise_setup également) n'ont structurellement
    # aucune soumission au moment de la création, toujours None pour eux.
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("submissions.id"), nullable=True
    )
    # Câblage HITL indexation RAG (Comparative_Evaluation_Agent,
    # MULTIPLE_DISTINCT_ANSWERS) — corrélation logique vers Bareme.
    # criteria[].id (JSON), PAS une FK SQL, même principe que
    # EvaluationCriteria.criterion_id/ValidatedAlternativeAnswer.criterion_id.
    # None pour toute ligne qui n'origine pas de ce mode (Reasoning_Graph_
    # Agent, Extraction_Verification_Agent) — related_entity_type="Question"
    # à lui seul ne suffit pas à distinguer (Extraction_Verification_Agent
    # l'utilise aussi), criterion_id non-None EST le signal distinctif.
    criterion_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Correctif AMBIGUOUS_COHERENCE — cf. docstring ComparativeClarificationKind.
    # None pour toute ligne hors Comparative_Evaluation_Agent.
    comparative_clarification_kind: Mapped[ComparativeClarificationKind | None] = mapped_column(
        PgEnum(
            ComparativeClarificationKind, name="comparative_clarification_kind",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
    )
    # Rempli uniquement à la résolution d'une ligne COHERENCE_AMBIGUITY —
    # True="coherent", False="incoherent" (cf. resolve_coherence_ambiguity,
    # repository). Colonne typée dédiée plutôt qu'un parsing de
    # professor_answer (texte libre) : jamais un contrôle de flux basé sur
    # une correspondance de chaîne fragile.
    resolved_as_coherent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Nullable depuis la Phase 6 (Extraction_Verification_Agent), MAIS reste
    # de facto obligatoire pour le flux Reasoning_Graph_Agent — l'invariant
    # n'est plus imposé par la DB, seulement par Pydantic :
    # ReasoningClarificationRequestCreate.unclear_content (solution_schemas.py)
    # garde `str` (non optionnel), et solution_variant_service.
    # request_clarification() est le seul appelant de repo.create() pour ce
    # flux, toujours avec une vraie valeur. Un futur appel direct à
    # repo.create() qui contournerait ce schéma (bypass Pydantic) pourrait
    # créer une ligne Reasoning_Graph_Agent sans unclear_content sans que la
    # DB ne s'y oppose — angle mort assumé, à garder en tête si ce repository
    # gagne un nouvel appelant pour ce flux.
    # Pour Extraction_Verification_Agent : concept sans objet (pas de
    # "contenu flou" à isoler, seulement une question posée directement) —
    # toujours None pour ces lignes.
    # Pour Comparative_Evaluation_Agent (MULTIPLE_DISTINCT_ANSWERS, câblage
    # HITL indexation RAG) : porte le texte COMPLET de la réponse candidate
    # de l'étudiant (pas tronqué comme dans agent_question), relu tel quel
    # à la validation pour indexer ValidatedAlternativeAnswer.
    unclear_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_question: Mapped[str] = mapped_column(Text, nullable=False)
    # Ce que l'agent propose, si applicable (ex. la répartition Cas 2
    # sérialisée) ; None si l'agent n'a aucune proposition, signalement seul.
    proposed_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    severity: Mapped[ClarificationSeverity] = mapped_column(
        # values_callable : cf. bareme.py — le type Postgres est créé avec
        # des valeurs minuscules, pas les noms membres Python.
        PgEnum(
            ClarificationSeverity, name="clarification_severity",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ClarificationSeverity.BLOCKING,
    )

    status: Mapped[ClarificationStatus] = mapped_column(
        PgEnum(ClarificationStatus, name="clarification_status"),
        nullable=False,
        default=ClarificationStatus.PENDING,
    )
    professor_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by_professor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=True
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rempli seulement après réponse, une fois l'agent capable de créer
    # l'étape correspondante — trace le lien clarification -> étape.
    resulting_step_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("reasoning_steps.id"), nullable=True
    )
    # Note: answered_by_professor_name est positionné dynamiquement en mémoire
    # par le service pour ReasoningClarificationRequestRead, pas comme colonne ORM.

    # Embedding vectoriel de agent_question (384 dim, all-MiniLM-L6-v2).
    # None tant que la clarification est PENDING.
    # Rempli dès que le professeur répond (status passe à ANSWERED) afin que
    # cette clarification résolue soit immédiatement retrouvable par recherche
    # de similarité (mécanisme few-shot section 10ter).
    # Vector(384) natif pgvector (câblage Priorité 2, chantier RAG) — plus un
    # TEXT/JSON : testé empiriquement (coercition implicite texte->vector
    # via SQLAlchemy/asyncpg ÉCHOUE, DatatypeMismatchError), donc le typage
    # Python DOIT correspondre au type SQL réel. Migration requiert pgvector
    # actif (échec explicite sinon, cf. migration dédiée) — plus de repli
    # TEXT possible pour cette colonne après ce câblage.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)

