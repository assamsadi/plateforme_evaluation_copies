"""
Repository ReasoningClarificationRequest — mécanisme d'Active Learning
(§ conversation) : le Reasoning Graph Agent pose une question au prof
face à une partie floue de sa correction, avant de créer la
ReasoningStep correspondante.

answer() : quand le prof répond, marque la demande ANSWERED. La création
de la ReasoningStep résultante (et le lien via resulting_step_id) est
faite par le SERVICE juste après (l'agent reprend son traitement suite
à l'interrupt LangGraph REASONING_CLARIFICATION), pas ici — ce repository
ne fait qu'enregistrer la réponse, jamais la logique de reprise du graphe.

validate_alternative_answer() (câblage HITL indexation RAG, Priorité 1) :
même principe qu'answer() — enregistre UNIQUEMENT la décision du prof
(accepted/rejected) sur la ligne. L'indexation dans ValidatedAlternative
Answer (côté RAG Comparative_Evaluation_Agent) est orchestrée par le
SERVICE juste après, jamais ici — ce repository ne connaît pas
ValidatedAlternativeAnswerRepository.

resolve_coherence_ambiguity()/list_resolved_coherence_ambiguities_by_
exercise() (correctif AMBIGUOUS_COHERENCE) : même principe — enregistre
UNIQUEMENT la décision coherent/incoherent du prof (resolved_as_coherent,
colonne typée dédiée). C'est comparative_evaluation_node.py (à la reprise)
qui relit ces décisions résolues pour les injecter dans EvaluationRequest.
coherence_ambiguity_resolutions, jamais ce repository.
"""
import uuid
from datetime import datetime, timezone
from typing import Literal, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationSeverity,
    ClarificationStatus,
    ComparativeClarificationKind,
    ReasoningClarificationRequest,
)


class ReasoningClarificationRequestRepositoryProtocol(Protocol):
    async def get_by_id(self, request_id: uuid.UUID) -> ReasoningClarificationRequest | None: ...
    async def list_pending(self) -> list[ReasoningClarificationRequest]: ...
    async def list_pending_blocking_by_exercise(
        self, exercise_id: uuid.UUID
    ) -> list[ReasoningClarificationRequest]: ...
    async def list_by_variant(
        self, variant_id: uuid.UUID
    ) -> list[ReasoningClarificationRequest]: ...
    async def create(
        self,
        agent_question: str,
        unclear_content: str | None = None,
        variant_id: uuid.UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        proposed_answer: str | None = None,
        severity: ClarificationSeverity = ClarificationSeverity.BLOCKING,
        criterion_id: str | None = None,
        comparative_clarification_kind: ComparativeClarificationKind | None = None,
        submission_id: uuid.UUID | None = None,
    ) -> ReasoningClarificationRequest: ...
    async def list_pending_blocking_by_question_and_submission(
        self, question_id: uuid.UUID, submission_id: uuid.UUID,
    ) -> list[ReasoningClarificationRequest]: ...
    async def answer(
        self,
        request_id: uuid.UUID,
        professor_answer: str,
        answered_by_professor_id: uuid.UUID,
    ) -> ReasoningClarificationRequest | None: ...
    async def validate_alternative_answer(
        self,
        request_id: uuid.UUID,
        accepted: bool,
        professor_id: uuid.UUID,
    ) -> ReasoningClarificationRequest | None: ...
    async def resolve_coherence_ambiguity(
        self,
        request_id: uuid.UUID,
        resolved_as: Literal["coherent", "incoherent"],
        professor_id: uuid.UUID,
    ) -> ReasoningClarificationRequest | None: ...
    async def list_resolved_coherence_ambiguities_by_exercise(
        self, exercise_id: uuid.UUID
    ) -> list[ReasoningClarificationRequest]: ...
    async def link_resulting_step(
        self, request_id: uuid.UUID, step_id: uuid.UUID
    ) -> ReasoningClarificationRequest | None: ...


class SQLAlchemyReasoningClarificationRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, request_id: uuid.UUID
    ) -> ReasoningClarificationRequest | None:
        return await self._session.get(ReasoningClarificationRequest, request_id)

    async def list_pending(self) -> list[ReasoningClarificationRequest]:
        """Toutes les questions en attente de réponse du prof, tous exercices confondus."""
        result = await self._session.execute(
            select(ReasoningClarificationRequest)
            .where(ReasoningClarificationRequest.status == ClarificationStatus.PENDING)
            .order_by(ReasoningClarificationRequest.created_at)
        )
        return list(result.scalars().all())

    async def list_pending_blocking_by_exercise(
        self, exercise_id: uuid.UUID
    ) -> list[ReasoningClarificationRequest]:
        """
        Toutes les clarifications PENDING de sévérité BLOCKING pour cet
        exercice — utilisé par exercise_service.publish() (condition
        bloquante) et par extraction_verification_service.
        get_pending_blocking_clarifications() (écran récapitulatif, hors
        périmètre ici). WARNING/INFORMATIONAL sont exclues : persistées,
        mais ne bloquent jamais publish() (Phase 4/6).

        Remplace l'ancienne list_pending_by_exercise (Reasoning_Graph_Agent
        seul, chemin variant_id → SolutionVariant → Question) : couvre en
        plus related_entity_type="Question"/"Bareme" (Extraction_
        Verification_Agent, Phase 4) — deux chemins disjoints, fusionnés en
        Python plutôt qu'un UNION SQL (fréquence d'appel faible, uniquement
        à la publication).
        """
        from app.domain.models.assessment.bareme import Bareme
        from app.domain.models.assessment.question import Question
        from app.domain.models.assessment.solution_variant import SolutionVariant

        question_ids = list(
            (
                await self._session.execute(
                    select(Question.id).where(Question.exercise_id == exercise_id)
                )
            ).scalars().all()
        )
        bareme_ids = (
            list(
                (
                    await self._session.execute(
                        select(Bareme.id).where(Bareme.question_id.in_(question_ids))
                    )
                ).scalars().all()
            )
            if question_ids
            else []
        )

        variant_result = await self._session.execute(
            select(ReasoningClarificationRequest)
            .join(
                SolutionVariant,
                ReasoningClarificationRequest.variant_id == SolutionVariant.id,
            )
            .join(Question, SolutionVariant.question_id == Question.id)
            .where(
                Question.exercise_id == exercise_id,
                ReasoningClarificationRequest.status == ClarificationStatus.PENDING,
                ReasoningClarificationRequest.severity == ClarificationSeverity.BLOCKING,
            )
        )
        results = list(variant_result.scalars().all())
        seen_ids = {r.id for r in results}

        entity_conditions = []
        if question_ids:
            entity_conditions.append(
                (ReasoningClarificationRequest.related_entity_type == "Question")
                & ReasoningClarificationRequest.related_entity_id.in_(question_ids)
            )
        if bareme_ids:
            entity_conditions.append(
                (ReasoningClarificationRequest.related_entity_type == "Bareme")
                & ReasoningClarificationRequest.related_entity_id.in_(bareme_ids)
            )
        if entity_conditions:
            entity_result = await self._session.execute(
                select(ReasoningClarificationRequest).where(
                    or_(*entity_conditions),
                    ReasoningClarificationRequest.status == ClarificationStatus.PENDING,
                    ReasoningClarificationRequest.severity == ClarificationSeverity.BLOCKING,
                )
            )
            for request in entity_result.scalars().all():
                if request.id not in seen_ids:
                    results.append(request)
                    seen_ids.add(request.id)

        results.sort(key=lambda r: r.created_at)
        return results

    async def list_by_variant(
        self, variant_id: uuid.UUID
    ) -> list[ReasoningClarificationRequest]:
        result = await self._session.execute(
            select(ReasoningClarificationRequest)
            .where(ReasoningClarificationRequest.variant_id == variant_id)
            .order_by(ReasoningClarificationRequest.created_at)
        )
        return list(result.scalars().all())

    async def create(
        self,
        agent_question: str,
        unclear_content: str | None = None,
        variant_id: uuid.UUID | None = None,
        related_entity_type: str | None = None,
        related_entity_id: uuid.UUID | None = None,
        proposed_answer: str | None = None,
        severity: ClarificationSeverity = ClarificationSeverity.BLOCKING,
        criterion_id: str | None = None,
        comparative_clarification_kind: ComparativeClarificationKind | None = None,
        submission_id: uuid.UUID | None = None,
    ) -> ReasoningClarificationRequest:
        """
        Crée une demande de clarification.
        variant_id OU (related_entity_type + related_entity_id) doit être fourni.
        unclear_content : propre au Reasoning Graph Agent, None pour
        Extraction_Verification_Agent (Phase 6) qui pose une question
        directement, sans "contenu flou" séparé à isoler.
        criterion_id : câblage HITL indexation RAG — renseigné uniquement
        pour Comparative_Evaluation_Agent (MULTIPLE_DISTINCT_ANSWERS), None
        pour tous les autres appelants (comportement inchangé).
        comparative_clarification_kind : correctif AMBIGUOUS_COHERENCE —
        renseigné uniquement par comparative_evaluation_node.py (les 2
        sous-types MULTIPLE_DISTINCT_ANSWERS), None pour tous les autres
        appelants (comportement inchangé).
        submission_id : cf. docstring modèle — renseigné uniquement par
        comparative_evaluation_node.py (seul appelant à connaître une
        soumission réelle au moment de la création), None pour tous les
        autres (Reasoning_Graph_Agent, Extraction_Verification_Agent).
        """
        request = ReasoningClarificationRequest(
            variant_id=variant_id,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            unclear_content=unclear_content,
            agent_question=agent_question,
            proposed_answer=proposed_answer,
            severity=severity,
            status=ClarificationStatus.PENDING,
            criterion_id=criterion_id,
            comparative_clarification_kind=comparative_clarification_kind,
            submission_id=submission_id,
        )
        self._session.add(request)
        await self._session.flush()
        return request

    async def list_pending_blocking_by_question_and_submission(
        self, question_id: uuid.UUID, submission_id: uuid.UUID,
    ) -> list[ReasoningClarificationRequest]:
        """
        Écran "Mes résultats" (2026-09-06) — LA justification réelle de
        Comparative_Evaluation_Agent pour une question bloquée, filtrée à la
        soumission exacte (cf. docstring submission_id du modèle : sans ce
        filtre, related_entity_id="Question" seul est partagé par toute
        soumission heurtant le même critère). Ne retourne jamais les lignes
        Reasoning_Graph_Agent/Extraction_Verification_Agent (submission_id
        toujours None pour elles, donc jamais de faux-positif possible ici
        même sans filtrer explicitement sur related_entity_type).
        """
        result = await self._session.execute(
            select(ReasoningClarificationRequest)
            .where(
                ReasoningClarificationRequest.related_entity_type == "Question",
                ReasoningClarificationRequest.related_entity_id == question_id,
                ReasoningClarificationRequest.submission_id == submission_id,
                ReasoningClarificationRequest.status == ClarificationStatus.PENDING,
                ReasoningClarificationRequest.severity == ClarificationSeverity.BLOCKING,
            )
            .order_by(ReasoningClarificationRequest.created_at)
        )
        return list(result.scalars().all())

    async def answer(
        self,
        request_id: uuid.UUID,
        professor_answer: str,
        answered_by_professor_id: uuid.UUID,
    ) -> ReasoningClarificationRequest | None:
        request = await self.get_by_id(request_id)
        if request is None:
            return None
        request.professor_answer = professor_answer
        request.answered_by_professor_id = answered_by_professor_id
        request.answered_at = datetime.now(timezone.utc)
        request.status = ClarificationStatus.ANSWERED
        await self._session.flush()
        return request

    async def validate_alternative_answer(
        self,
        request_id: uuid.UUID,
        accepted: bool,
        professor_id: uuid.UUID,
    ) -> ReasoningClarificationRequest | None:
        """
        Câblage HITL indexation RAG (Priorité 1) — même bookkeeping
        qu'answer() (status/answered_by_professor_id/answered_at), mais
        professor_answer fixe (accept/reject), jamais un texte libre
        détourné pour encoder une décision booléenne. L'indexation
        ValidatedAlternativeAnswer (si accepted=True) est orchestrée par le
        SERVICE juste après (cf. docstring module) — pas ici.
        """
        request = await self.get_by_id(request_id)
        if request is None:
            return None
        request.professor_answer = (
            "Validé comme réponse alternative légitime." if accepted
            else "Rejeté — traité comme incorrect."
        )
        request.answered_by_professor_id = professor_id
        request.answered_at = datetime.now(timezone.utc)
        request.status = ClarificationStatus.ANSWERED
        await self._session.flush()
        return request

    async def resolve_coherence_ambiguity(
        self,
        request_id: uuid.UUID,
        resolved_as: Literal["coherent", "incoherent"],
        professor_id: uuid.UUID,
    ) -> ReasoningClarificationRequest | None:
        """
        Correctif AMBIGUOUS_COHERENCE — même bookkeeping qu'answer()/
        validate_alternative_answer() (status/answered_by_professor_id/
        answered_at), mais professor_answer fixe (2 valeurs) + resolved_
        as_coherent (colonne typée, relue par comparative_evaluation_node.py
        à la reprise pour construire EvaluationRequest.coherence_ambiguity_
        resolutions) — jamais un texte libre détourné pour encoder cette
        décision.
        """
        request = await self.get_by_id(request_id)
        if request is None:
            return None
        request.professor_answer = (
            "Résolu comme cohérent — traitement repris comme si le filtre "
            "de cohérence avait initialement renvoyé COHERENT."
            if resolved_as == "coherent" else
            "Résolu comme incohérent — traitement repris comme si le filtre "
            "de cohérence avait initialement renvoyé INCOHERENT."
        )
        request.resolved_as_coherent = (resolved_as == "coherent")
        request.answered_by_professor_id = professor_id
        request.answered_at = datetime.now(timezone.utc)
        request.status = ClarificationStatus.ANSWERED
        await self._session.flush()
        return request

    async def list_resolved_coherence_ambiguities_by_exercise(
        self, exercise_id: uuid.UUID
    ) -> list[ReasoningClarificationRequest]:
        """
        Toutes les clarifications COHERENCE_AMBIGUITY déjà ANSWERED pour cet
        exercice — relu par comparative_evaluation_node.py à CHAQUE
        exécution (pas seulement à la reprise) pour construire l'override
        par (question_id, criterion_id) : une résolution s'applique à
        TOUTES les soumissions futures pour cette question/ce critère,
        jamais scopée à la seule soumission qui l'a déclenchée — même
        portée que le mécanisme alternative_answer déjà existant
        (ValidatedAlternativeAnswer, cross-soumissions par construction).
        """
        from app.domain.models.assessment.question import Question

        question_ids = list(
            (
                await self._session.execute(
                    select(Question.id).where(Question.exercise_id == exercise_id)
                )
            ).scalars().all()
        )
        if not question_ids:
            return []

        result = await self._session.execute(
            select(ReasoningClarificationRequest).where(
                ReasoningClarificationRequest.related_entity_type == "Question",
                ReasoningClarificationRequest.related_entity_id.in_(question_ids),
                ReasoningClarificationRequest.comparative_clarification_kind
                == ComparativeClarificationKind.COHERENCE_AMBIGUITY,
                ReasoningClarificationRequest.status == ClarificationStatus.ANSWERED,
            )
        )
        return list(result.scalars().all())

    async def link_resulting_step(
        self, request_id: uuid.UUID, step_id: uuid.UUID
    ) -> ReasoningClarificationRequest | None:
        """Appelée par le service après que l'agent a repris et créé la
        ReasoningStep grâce à la réponse du prof — trace le lien pour
        l'explicabilité et la future indexation few-shot (§6)."""
        request = await self.get_by_id(request_id)
        if request is None:
            return None
        request.resulting_step_id = step_id
        await self._session.flush()
        return request