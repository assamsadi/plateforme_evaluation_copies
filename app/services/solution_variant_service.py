"""
Service orchestrant les variantes de solution et leur graphe de raisonnement associé.

Règles métier appliquées :
1. Une variante de solution peut être générée par une IA ou fournie par le professeur,
   et possède un graphe orienté acyclique d'étapes de raisonnement.
2. Si le graphe contient un cycle, l'algorithme de Kahn (côté repository) lèvera CyclicGraphError.
3. Le Reasoning Graph Agent peut interroger le professeur sur une partie floue via une
   ReasoningClarificationRequest, et lier la réponse à l'étape générée ultérieurement
   (Active Learning).

Câblage HITL indexation RAG (Priorité 1) :
4. validate_alternative_answer_clarification() résout une clarification
   MULTIPLE_DISTINCT_ANSWERS (Comparative_Evaluation_Agent,
   comparative_clarification_kind == ALTERNATIVE_ANSWER — cf.
   InvalidClarificationTypeError sinon, DEPUIS le correctif AMBIGUOUS_
   COHERENCE point 5 ci-dessous : criterion_id seul ne suffit plus à
   distinguer, un 2ème sous-type le partage désormais) : accepted=True
   indexe la réponse candidate dans ValidatedAlternativeAnswer (embedding
   calculé par le repository dédié, cf. app/core/embeddings.py) ;
   accepted=False n'indexe rien. Ce service orchestre les 2 repositories
   (ReasoningClarificationRequestRepository + ValidatedAlternativeAnswer
   Repository) — ni l'un ni l'autre ne connaît l'autre.

Correctif AMBIGUOUS_COHERENCE :
5. resolve_coherence_ambiguity_clarification() résout l'AUTRE sous-type
   MULTIPLE_DISTINCT_ANSWERS (comparative_clarification_kind ==
   COHERENCE_AMBIGUITY) — décision coherent/incoherent, PAS un accept/
   reject de réponse candidate (sémantique différente, endpoint dédié).
   N'indexe RIEN (contrairement au point 4) : la décision est relue par
   comparative_evaluation_node.py à la reprise (ReasoningClarification
   Request.resolved_as_coherent), jamais consommée ici.
"""
import uuid
from typing import Literal, Protocol

from app.core.exceptions import (
    ClarificationRequestNotFoundError,
    InvalidClarificationTypeError,
    VariantNotFoundError,
)
from app.domain.models.assessment.reasoning_clarification_request import (
    ComparativeClarificationKind,
    ReasoningClarificationRequest,
)
from app.domain.models.assessment.reasoning_step import ReasoningStep
from app.domain.models.assessment.solution_variant import (
    SolutionVariant,
    VariantDifficulty,
    VariantStatus,
    VariantSource,
)
from app.domain.repositories.reasoning_clarification_request_repository import (
    ReasoningClarificationRequestRepositoryProtocol,
)
from app.domain.repositories.solution_variant_repository import SolutionVariantRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.repositories.validated_alternative_answer_repository import (
    ValidatedAlternativeAnswerRepositoryProtocol,
)
from app.domain.schemas.solution_schemas import (
    ReasoningClarificationRequestRead,
    ReasoningStepRead,
    SolutionVariantRead,
)


class SolutionVariantServiceProtocol(Protocol):
    async def create_variant(
        self,
        question_id: uuid.UUID,
        content: str,
        source: VariantSource,
        difficulty_level: VariantDifficulty,
        is_reference: bool,
        structured_content: dict | None,
        steps_data: list[dict],
    ) -> SolutionVariantRead: ...

    async def validate_variant(
        self,
        variant_id: uuid.UUID,
        professor_id: uuid.UUID,
        status: VariantStatus,
        review_comment: str | None,
    ) -> SolutionVariantRead: ...

    async def get_ordered_reasoning_graph(self, variant_id: uuid.UUID) -> list[ReasoningStepRead]: ...

    async def request_clarification(
        self, variant_id: uuid.UUID, unclear_content: str, agent_question: str
    ) -> ReasoningClarificationRequestRead: ...

    async def answer_clarification(
        self, request_id: uuid.UUID, professor_id: uuid.UUID, answer: str
    ) -> ReasoningClarificationRequestRead: ...

    async def link_clarification_to_step(
        self, request_id: uuid.UUID, step_id: uuid.UUID
    ) -> ReasoningClarificationRequestRead: ...

    async def list_pending_clarifications(self) -> list[ReasoningClarificationRequestRead]: ...

    async def validate_alternative_answer_clarification(
        self, request_id: uuid.UUID, professor_id: uuid.UUID, accepted: bool,
    ) -> ReasoningClarificationRequestRead: ...

    async def resolve_coherence_ambiguity_clarification(
        self, request_id: uuid.UUID, professor_id: uuid.UUID, resolved_as: Literal["coherent", "incoherent"],
    ) -> ReasoningClarificationRequestRead: ...


class SolutionVariantService:
    def __init__(
        self,
        variant_repo: SolutionVariantRepositoryProtocol,
        clarification_repo: ReasoningClarificationRequestRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
        validated_answer_repo: ValidatedAlternativeAnswerRepositoryProtocol,
    ) -> None:
        self._variant_repo = variant_repo
        self._clarification_repo = clarification_repo
        self._user_repo = user_repo
        self._validated_answer_repo = validated_answer_repo

    async def _to_variant_read(self, variant: SolutionVariant) -> SolutionVariantRead:
        """
        Bug pré-existant corrigé ici (découvert au câblage frontend de
        l'authoring professeur) : lisait variant.reasoning_steps comme une
        relation ORM — SolutionVariant n'en déclare aucune (aucun
        relationship() dans le modèle), donc tout appel plantait avec
        AttributeError avant même d'atteindre model_validate. Corrigé pour
        requêter les étapes via get_reasoning_steps_ordered (même méthode
        déjà utilisée, avec succès, par get_ordered_reasoning_graph),
        rattachées en attribut transitoire pour le model_validate final.
        """
        steps = await self._variant_repo.get_reasoning_steps_ordered(variant.id)
        for step in steps:
            if getattr(step, "related_competency_name", None) is None:
                step.related_competency_name = None
        variant.reasoning_steps = steps
        return SolutionVariantRead.model_validate(variant)

    def _to_clarification_read(
        self, req: ReasoningClarificationRequest, professor_name: str | None = None
    ) -> ReasoningClarificationRequestRead:
        """
        answered_by_professor_name (schéma) est un champ aplati, absent du
        modèle ORM (ReasoningClarificationRequest n'a pas cette colonne) —
        DOIT être posé en attribut transitoire avant model_validate, y
        compris quand professor_name est None (clarification non répondue,
        cas normal de /clarifications/pending). Le `if professor_name:`
        d'origine sautait cette affectation dès que professor_name était
        falsy, laissant l'attribut absent -> pydantic_core.ValidationError
        "Field required" (jamais un str | None réellement optionnel côté
        objet source, malgré le typage du schéma) — 500 constaté en test
        réel sur CHAQUE clarification en attente (aucune n'a de répondant).
        """
        req.answered_by_professor_name = professor_name
        return ReasoningClarificationRequestRead.model_validate(req)

    async def create_variant(
        self,
        question_id: uuid.UUID,
        content: str,
        source: VariantSource,
        difficulty_level: VariantDifficulty,
        is_reference: bool,
        structured_content: dict | None,
        steps_data: list[dict],
    ) -> SolutionVariantRead:
        variant = await self._variant_repo.create_with_reasoning_graph(
            question_id=question_id,
            content=content,
            source=source,
            difficulty_level=difficulty_level,
            is_reference=is_reference,
            structured_content=structured_content,
            steps_data=steps_data,
        )
        return await self._to_variant_read(variant)

    async def validate_variant(
        self,
        variant_id: uuid.UUID,
        professor_id: uuid.UUID,
        status: VariantStatus,
        review_comment: str | None,
    ) -> SolutionVariantRead:
        variant = await self._variant_repo.validate(
            variant_id=variant_id,
            professor_id=professor_id,
            status=status,
            review_comment=review_comment,
        )
        if not variant:
            raise VariantNotFoundError(variant_id)
        return await self._to_variant_read(variant)

    async def get_ordered_reasoning_graph(self, variant_id: uuid.UUID) -> list[ReasoningStepRead]:
        steps = await self._variant_repo.get_reasoning_steps_ordered(variant_id)
        result: list[ReasoningStepRead] = []
        for s in steps:
            s.related_competency_name = None
            result.append(ReasoningStepRead.model_validate(s))
        return result

    async def request_clarification(
        self, variant_id: uuid.UUID, unclear_content: str, agent_question: str
    ) -> ReasoningClarificationRequestRead:
        request = await self._clarification_repo.create(
            variant_id=variant_id,
            unclear_content=unclear_content,
            agent_question=agent_question,
        )
        return self._to_clarification_read(request)

    async def answer_clarification(
        self, request_id: uuid.UUID, professor_id: uuid.UUID, answer: str
    ) -> ReasoningClarificationRequestRead:
        request = await self._clarification_repo.answer(
            request_id=request_id,
            professor_answer=answer,
            answered_by_professor_id=professor_id,
        )
        if not request:
            raise ClarificationRequestNotFoundError(request_id)
        prof_name = None
        if request.answered_by_professor_id:
            professor = await self._user_repo.get_by_id(request.answered_by_professor_id)
            prof_name = f"{professor.first_name} {professor.last_name}" if professor else None
        return self._to_clarification_read(request, prof_name)

    async def link_clarification_to_step(
        self, request_id: uuid.UUID, step_id: uuid.UUID
    ) -> ReasoningClarificationRequestRead:
        request = await self._clarification_repo.link_resulting_step(
            request_id=request_id,
            step_id=step_id,
        )
        if not request:
            raise ClarificationRequestNotFoundError(request_id)
        return self._to_clarification_read(request)

    async def list_pending_clarifications(self) -> list[ReasoningClarificationRequestRead]:
        requests = await self._clarification_repo.list_pending()
        return [self._to_clarification_read(req) for req in requests]

    async def validate_alternative_answer_clarification(
        self, request_id: uuid.UUID, professor_id: uuid.UUID, accepted: bool,
    ) -> ReasoningClarificationRequestRead:
        """
        Câblage HITL indexation RAG (Priorité 1) — résout une clarification
        MULTIPLE_DISTINCT_ANSWERS (Comparative_Evaluation_Agent). Vérifie
        AVANT toute écriture que la ligne ciblée en est bien une, et
        PRÉCISÉMENT du bon sous-type (comparative_clarification_kind ==
        ALTERNATIVE_ANSWER) — DEPUIS le correctif AMBIGUOUS_COHERENCE,
        criterion_id seul ne suffit plus (les deux sous-types le partagent) :
        jamais un accept/reject appliqué à une clarification COHERENCE_
        AMBIGUITY (sémantique différente) ni à une clarification Reasoning_
        Graph_Agent/Extraction_Verification_Agent.

        accepted=True : indexe la réponse candidate (request.unclear_content,
        cf. son docstring modèle) dans ValidatedAlternativeAnswer via
        ValidatedAlternativeAnswerRepository.create_validated_answer()
        (embedding calculé là-bas, app/core/embeddings.py). accepted=False :
        la clarification est marquée résolue, rien n'est indexé.
        """
        request = await self._clarification_repo.get_by_id(request_id)
        if request is None:
            raise ClarificationRequestNotFoundError(request_id)
        if request.comparative_clarification_kind != ComparativeClarificationKind.ALTERNATIVE_ANSWER:
            raise InvalidClarificationTypeError(request_id)

        updated = await self._clarification_repo.validate_alternative_answer(
            request_id=request_id,
            accepted=accepted,
            professor_id=professor_id,
        )
        if updated is None:
            raise ClarificationRequestNotFoundError(request_id)

        if accepted:
            await self._validated_answer_repo.create_validated_answer(
                question_id=updated.related_entity_id,
                criterion_id=updated.criterion_id,
                answer_text=updated.unclear_content or "",
                validated_by_professor_id=professor_id,
            )

        prof_name = None
        if updated.answered_by_professor_id:
            professor = await self._user_repo.get_by_id(updated.answered_by_professor_id)
            prof_name = f"{professor.first_name} {professor.last_name}" if professor else None
        return self._to_clarification_read(updated, prof_name)

    async def resolve_coherence_ambiguity_clarification(
        self, request_id: uuid.UUID, professor_id: uuid.UUID, resolved_as: Literal["coherent", "incoherent"],
    ) -> ReasoningClarificationRequestRead:
        """
        Correctif AMBIGUOUS_COHERENCE — résout l'AUTRE sous-type
        MULTIPLE_DISTINCT_ANSWERS (comparative_clarification_kind ==
        COHERENCE_AMBIGUITY, jamais ALTERNATIVE_ANSWER — cf.
        InvalidClarificationTypeError sinon, même garde symétrique que
        validate_alternative_answer_clarification).

        N'indexe RIEN (contrairement au point 4, docstring module) : la
        décision (resolved_as_coherent) est relue par comparative_
        evaluation_node.py à la reprise, injectée dans EvaluationRequest.
        coherence_ambiguity_resolutions — c'est LÀ que le traitement reprend
        comme si le filtre avait initialement renvoyé COHERENT/INCOHERENT,
        jamais ici (ce service ne fait qu'enregistrer la décision).
        """
        request = await self._clarification_repo.get_by_id(request_id)
        if request is None:
            raise ClarificationRequestNotFoundError(request_id)
        if request.comparative_clarification_kind != ComparativeClarificationKind.COHERENCE_AMBIGUITY:
            raise InvalidClarificationTypeError(request_id)

        updated = await self._clarification_repo.resolve_coherence_ambiguity(
            request_id=request_id,
            resolved_as=resolved_as,
            professor_id=professor_id,
        )
        if updated is None:
            raise ClarificationRequestNotFoundError(request_id)

        prof_name = None
        if updated.answered_by_professor_id:
            professor = await self._user_repo.get_by_id(updated.answered_by_professor_id)
            prof_name = f"{professor.first_name} {professor.last_name}" if professor else None
        return self._to_clarification_read(updated, prof_name)

