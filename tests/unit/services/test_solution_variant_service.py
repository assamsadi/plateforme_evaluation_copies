import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import (
    ClarificationRequestNotFoundError,
    InvalidClarificationTypeError,
    VariantNotFoundError,
)
from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationSeverity,
    ClarificationStatus,
    ComparativeClarificationKind,
    ReasoningClarificationRequest,
)
from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepType
from app.domain.models.assessment.solution_variant import (
    SolutionVariant,
    VariantDifficulty,
    VariantSource,
    VariantStatus,
)
from app.services.solution_variant_service import SolutionVariantService
#lidentification de la question en cours de la reponse est repondu 





def _make_variant(variant_id: uuid.UUID, question_id: uuid.UUID) -> SolutionVariant:
    now = datetime.now(timezone.utc)
    variant = SolutionVariant(
        id=variant_id,
        question_id=question_id,
        content="Correction détaillée",
        structured_content=None,
        reasoning_summary=None,
        is_reference=True,
        source=VariantSource.TEACHER_ORIGINAL,
        difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        status=VariantStatus.APPROVED,
        validated_by_professor_id=None,
        review_comment=None,
        created_at=now,
        updated_at=now,
     


    )
    # reasoning_steps est une relation ORM, pas un kwarg constructeur
    variant.reasoning_steps = []
    return variant


def _make_step(step_id: uuid.UUID, variant_id: uuid.UUID) -> ReasoningStep:
    now = datetime.now(timezone.utc)
    step = ReasoningStep(
        id=step_id,
        variant_id=variant_id,
        order=1,
        step_type=ReasoningStepType.COMPUTATION,
        description="Calculer la dérivée",
        formula="f'(x)",
        concept_tags=[],
        tools_used=[],
        related_competency_code=None,
        created_at=now,
        updated_at=now,
    )
    # Champs aplatis requis par ReasoningStepRead, positionnés en mémoire
    # par le service — jamais des kwargs constructeur.
    step.related_competency_name = None
    step.depends_on_step_ids = []
    return step


def _make_clarification(request_id: uuid.UUID, variant_id: uuid.UUID) -> ReasoningClarificationRequest:
    now = datetime.now(timezone.utc)
    request = ReasoningClarificationRequest(
        id=request_id,
        variant_id=variant_id,
        unclear_content="Partie floue",
        agent_question="Pouvez-vous préciser ?",
        proposed_answer=None,
        severity=ClarificationSeverity.BLOCKING,
        status=ClarificationStatus.PENDING,
        professor_answer=None,
        answered_by_professor_id=None,
        answered_at=None,
        resulting_step_id=None,
        created_at=now,
        updated_at=now,
    )
    #champ aplati depuis la formulation de la question ne peut pas etre suggerer vrai 

    
    # Champ aplati requis par ReasoningClarificationRequestRead — le service
    # ne le positionne que si un nom de professeur est fourni.
    request.answered_by_professor_name = None
    return request


def _make_service(
    variant_repo=None, clarification_repo=None, user_repo=None, validated_answer_repo=None,
) -> SolutionVariantService:
    return SolutionVariantService(
        variant_repo or AsyncMock(),
        clarification_repo or AsyncMock(),
        user_repo or AsyncMock(),
        validated_answer_repo or AsyncMock(),
    )


@pytest.mark.anyio
async def test_create_variant_success():
    vid = uuid.uuid4()
    qid = uuid.uuid4()
    variant = _make_variant(vid, qid)
    steps_data = [{"order": 1, "description": "Étape"}]

    variant_repo = AsyncMock()
    variant_repo.create_with_reasoning_graph.return_value = variant
    variant_repo.get_reasoning_steps_ordered.return_value = []

    service = _make_service(variant_repo=variant_repo)
    result = await service.create_variant(
        qid, "Correction détaillée", VariantSource.TEACHER_ORIGINAL, VariantDifficulty.INTERMEDIAIRE, True, None, steps_data
    )

    assert result.id == vid
    assert result.content == "Correction détaillée"
    assert result.source == VariantSource.TEACHER_ORIGINAL
    assert result.reasoning_steps == []
    variant_repo.get_reasoning_steps_ordered.assert_awaited_once_with(vid)
    variant_repo.create_with_reasoning_graph.assert_awaited_once_with(
        question_id=qid,
        content="Correction détaillée",
        source=VariantSource.TEACHER_ORIGINAL,
        difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        is_reference=True,
        structured_content=None,
        steps_data=steps_data,
    )


@pytest.mark.anyio
async def test_validate_variant_success():
    vid = uuid.uuid4()
    qid = uuid.uuid4()
    pid = uuid.uuid4()
    variant = _make_variant(vid, qid)
    variant.status = VariantStatus.APPROVED
    variant.validated_by_professor_id = pid

    variant_repo = AsyncMock()
    variant_repo.validate.return_value = variant
    variant_repo.get_reasoning_steps_ordered.return_value = []

    service = _make_service(variant_repo=variant_repo)
    result = await service.validate_variant(vid, pid, VariantStatus.APPROVED, "Validé")

    assert result.status == VariantStatus.APPROVED
    assert result.validated_by_professor_id == pid
    variant_repo.validate.assert_awaited_once_with(
        variant_id=vid, professor_id=pid, status=VariantStatus.APPROVED, review_comment="Validé"
    )


@pytest.mark.anyio
async def test_validate_variant_not_found():
    vid = uuid.uuid4()
    variant_repo = AsyncMock()
    variant_repo.validate.return_value = None

    service = _make_service(variant_repo=variant_repo)
    with pytest.raises(VariantNotFoundError):
        await service.validate_variant(vid, uuid.uuid4(), VariantStatus.APPROVED, None)


@pytest.mark.anyio
async def test_get_ordered_reasoning_graph_success():
    vid = uuid.uuid4()
    step = _make_step(uuid.uuid4(), vid)

    variant_repo = AsyncMock()
    variant_repo.get_reasoning_steps_ordered.return_value = [step]

    service = _make_service(variant_repo=variant_repo)
    result = await service.get_ordered_reasoning_graph(vid)

    assert len(result) == 1
    assert result[0].description == "Calculer la dérivée"
    assert result[0].related_competency_name is None
    variant_repo.get_reasoning_steps_ordered.assert_awaited_once_with(vid)


@pytest.mark.anyio
async def test_request_clarification_success():
    rid = uuid.uuid4()
    vid = uuid.uuid4()
    request = _make_clarification(rid, vid)

    clarification_repo = AsyncMock()
    clarification_repo.create.return_value = request

    service = _make_service(clarification_repo=clarification_repo)
    result = await service.request_clarification(vid, "Partie floue", "Pouvez-vous préciser ?")

    assert result.id == rid
    assert result.status == ClarificationStatus.PENDING
    clarification_repo.create.assert_awaited_once_with(
        variant_id=vid, unclear_content="Partie floue", agent_question="Pouvez-vous préciser ?"
    )


@pytest.mark.anyio
async def test_answer_clarification_success():
    rid = uuid.uuid4()
    vid = uuid.uuid4()
    pid = uuid.uuid4()
    request = _make_clarification(rid, vid)
    request.status = ClarificationStatus.ANSWERED
    request.professor_answer = "Voici la précision"
    request.answered_by_professor_id = pid

    clarification_repo = AsyncMock()
    clarification_repo.answer.return_value = request

    user_repo = AsyncMock()
    professor = MagicMock()
    professor.first_name = "Alice"
    professor.last_name = "Dupont"
    user_repo.get_by_id.return_value = professor

    service = _make_service(clarification_repo=clarification_repo, user_repo=user_repo)
    result = await service.answer_clarification(rid, pid, "Voici la précision")

    assert result.professor_answer == "Voici la précision"
    assert result.answered_by_professor_name == "Alice Dupont"
    # Correctif : les noms de paramètres doivent correspondre à la VRAIE
    # signature du repository (professor_answer/answered_by_professor_id),
    # jamais professor_id/answer — cette assertion validait auparavant
    # l'appel bogué (TypeError certain en usage réel, jamais détecté par un
    # AsyncMock qui accepte n'importe quel kwarg).
    clarification_repo.answer.assert_awaited_once_with(
        request_id=rid, professor_answer="Voici la précision", answered_by_professor_id=pid,
    )


@pytest.mark.anyio
async def test_answer_clarification_not_found():
    rid = uuid.uuid4()
    clarification_repo = AsyncMock()
    clarification_repo.answer.return_value = None

    service = _make_service(clarification_repo=clarification_repo)
    with pytest.raises(ClarificationRequestNotFoundError):
        await service.answer_clarification(rid, uuid.uuid4(), "Réponse")


@pytest.mark.anyio
async def test_link_clarification_to_step_success():
    rid = uuid.uuid4()
    vid = uuid.uuid4()
    step_id = uuid.uuid4()
    request = _make_clarification(rid, vid)
    request.resulting_step_id = step_id

    clarification_repo = AsyncMock()
    clarification_repo.link_resulting_step.return_value = request

    service = _make_service(clarification_repo=clarification_repo)
    result = await service.link_clarification_to_step(rid, step_id)

    assert result.resulting_step_id == step_id
    clarification_repo.link_resulting_step.assert_awaited_once_with(
        request_id=rid, step_id=step_id
    )


@pytest.mark.anyio
async def test_link_clarification_to_step_not_found():
    rid = uuid.uuid4()
    clarification_repo = AsyncMock()
    clarification_repo.link_resulting_step.return_value = None

    service = _make_service(clarification_repo=clarification_repo)
    with pytest.raises(ClarificationRequestNotFoundError):
        await service.link_clarification_to_step(rid, uuid.uuid4())


@pytest.mark.anyio
async def test_list_pending_clarifications_success():
    rid = uuid.uuid4()
    vid = uuid.uuid4()
    request = _make_clarification(rid, vid)

    clarification_repo = AsyncMock()
    clarification_repo.list_pending.return_value = [request]

    service = _make_service(clarification_repo=clarification_repo)
    result = await service.list_pending_clarifications()

    assert len(result) == 1
    assert result[0].id == rid
    clarification_repo.list_pending.assert_awaited_once()


# ---------------------------------------------------------------------------
# Câblage HITL indexation RAG — validate_alternative_answer_clarification
# ---------------------------------------------------------------------------

def _make_mda_clarification(
    request_id: uuid.UUID, question_id: uuid.UUID, criterion_id: str | None = "crit-mda",
    comparative_clarification_kind: ComparativeClarificationKind | None = ComparativeClarificationKind.ALTERNATIVE_ANSWER,
) -> ReasoningClarificationRequest:
    now = datetime.now(timezone.utc)
    return ReasoningClarificationRequest(
        id=request_id,
        related_entity_type="Question",
        related_entity_id=question_id,
        criterion_id=criterion_id,
        comparative_clarification_kind=comparative_clarification_kind,
        resolved_as_coherent=None,
        unclear_content="Méthode alternative de l'étudiant.",
        agent_question="Une réponse alternative inédite... est-elle valide ?",
        proposed_answer="Valider cette réponse alternative comme correcte.",
        severity=ClarificationSeverity.BLOCKING,
        status=ClarificationStatus.PENDING,
        professor_answer=None,
        answered_by_professor_id=None,
        answered_at=None,
        resulting_step_id=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.anyio
async def test_validate_alternative_answer_accepted_indexes_validated_answer():
    rid = uuid.uuid4()
    qid = uuid.uuid4()
    pid = uuid.uuid4()
    request = _make_mda_clarification(rid, qid)

    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = request
    answered = _make_mda_clarification(rid, qid)
    answered.status = ClarificationStatus.ANSWERED
    answered.professor_answer = "Validé comme réponse alternative légitime."
    answered.answered_by_professor_id = pid
    clarification_repo.validate_alternative_answer.return_value = answered

    validated_answer_repo = AsyncMock()

    service = _make_service(
        clarification_repo=clarification_repo, validated_answer_repo=validated_answer_repo,
    )
    result = await service.validate_alternative_answer_clarification(rid, pid, accepted=True)

    assert result.status == ClarificationStatus.ANSWERED
    validated_answer_repo.create_validated_answer.assert_awaited_once_with(
        question_id=qid, criterion_id="crit-mda",
        answer_text="Méthode alternative de l'étudiant.", validated_by_professor_id=pid,
    )


@pytest.mark.anyio
async def test_validate_alternative_answer_rejected_indexes_nothing():
    rid = uuid.uuid4()
    qid = uuid.uuid4()
    pid = uuid.uuid4()
    request = _make_mda_clarification(rid, qid)

    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = request
    answered = _make_mda_clarification(rid, qid)
    answered.status = ClarificationStatus.ANSWERED
    answered.professor_answer = "Rejeté — traité comme incorrect."
    # validate_alternative_answer (repository réel) pose toujours
    # answered_by_professor_id, accepted=False ou non (même bookkeeping
    # qu'answer()) — reflété ici pour ne pas tester un état impossible.
    answered.answered_by_professor_id = pid
    clarification_repo.validate_alternative_answer.return_value = answered

    validated_answer_repo = AsyncMock()

    service = _make_service(
        clarification_repo=clarification_repo, validated_answer_repo=validated_answer_repo,
    )
    result = await service.validate_alternative_answer_clarification(rid, pid, accepted=False)

    assert result.professor_answer == "Rejeté — traité comme incorrect."
    validated_answer_repo.create_validated_answer.assert_not_awaited()


@pytest.mark.anyio
async def test_validate_alternative_answer_not_found():
    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = None

    service = _make_service(clarification_repo=clarification_repo)
    with pytest.raises(ClarificationRequestNotFoundError):
        await service.validate_alternative_answer_clarification(uuid.uuid4(), uuid.uuid4(), accepted=True)


@pytest.mark.anyio
async def test_validate_alternative_answer_rejects_non_mda_clarification():
    """
    Garde-fou — comparative_clarification_kind=None (clarification
    Reasoning_Graph_Agent ou Extraction_Verification_Agent, criterion_id
    également None) : jamais un accept/reject deviné. Le garde vérifie
    désormais comparative_clarification_kind (pas criterion_id seul, DEPUIS
    le correctif AMBIGUOUS_COHERENCE qui partage criterion_id non-None avec
    ALTERNATIVE_ANSWER — criterion_id seul ne suffit plus à distinguer).
    """
    rid = uuid.uuid4()
    qid = uuid.uuid4()
    request = _make_mda_clarification(rid, qid, criterion_id=None, comparative_clarification_kind=None)

    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = request

    service = _make_service(clarification_repo=clarification_repo)
    with pytest.raises(InvalidClarificationTypeError):
        await service.validate_alternative_answer_clarification(rid, uuid.uuid4(), accepted=True)
    clarification_repo.validate_alternative_answer.assert_not_awaited()


@pytest.mark.anyio
async def test_validate_alternative_answer_rejects_variant_origin_clarification():
    """Garde-fou — related_entity_type != 'Question' (même si criterion_id était par erreur non-None)."""
    rid = uuid.uuid4()
    vid = uuid.uuid4()
    request = _make_clarification(rid, vid)  # variant_id renseigné, related_entity_type=None
    request.criterion_id = "crit-mda"  # jamais censé arriver, garde quand même

    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = request

    service = _make_service(clarification_repo=clarification_repo)
    with pytest.raises(InvalidClarificationTypeError):
        await service.validate_alternative_answer_clarification(rid, uuid.uuid4(), accepted=True)


# ---------------------------------------------------------------------------
# Correctif AMBIGUOUS_COHERENCE — resolve_coherence_ambiguity_clarification
# ---------------------------------------------------------------------------

def _make_coherence_ambiguity_clarification(
    request_id: uuid.UUID, question_id: uuid.UUID,
) -> ReasoningClarificationRequest:
    now = datetime.now(timezone.utc)
    return ReasoningClarificationRequest(
        id=request_id,
        related_entity_type="Question",
        related_entity_id=question_id,
        criterion_id="crit-mda",
        comparative_clarification_kind=ComparativeClarificationKind.COHERENCE_AMBIGUITY,
        resolved_as_coherent=None,
        unclear_content=None,
        agent_question="Effort réel ou hors-sujet ?",
        proposed_answer=None,
        severity=ClarificationSeverity.BLOCKING,
        status=ClarificationStatus.PENDING,
        professor_answer=None,
        answered_by_professor_id=None,
        answered_at=None,
        resulting_step_id=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.anyio
async def test_resolve_coherence_ambiguity_as_coherent_success():
    rid = uuid.uuid4()
    qid = uuid.uuid4()
    pid = uuid.uuid4()
    request = _make_coherence_ambiguity_clarification(rid, qid)

    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = request
    answered = _make_coherence_ambiguity_clarification(rid, qid)
    answered.status = ClarificationStatus.ANSWERED
    answered.resolved_as_coherent = True
    answered.answered_by_professor_id = pid
    clarification_repo.resolve_coherence_ambiguity.return_value = answered

    service = _make_service(clarification_repo=clarification_repo)
    result = await service.resolve_coherence_ambiguity_clarification(rid, pid, resolved_as="coherent")

    assert result.status == ClarificationStatus.ANSWERED
    clarification_repo.resolve_coherence_ambiguity.assert_awaited_once_with(
        request_id=rid, resolved_as="coherent", professor_id=pid,
    )


@pytest.mark.anyio
async def test_resolve_coherence_ambiguity_as_incoherent_success():
    rid = uuid.uuid4()
    qid = uuid.uuid4()
    pid = uuid.uuid4()
    request = _make_coherence_ambiguity_clarification(rid, qid)

    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = request
    answered = _make_coherence_ambiguity_clarification(rid, qid)
    answered.status = ClarificationStatus.ANSWERED
    answered.resolved_as_coherent = False
    answered.answered_by_professor_id = pid
    clarification_repo.resolve_coherence_ambiguity.return_value = answered

    service = _make_service(clarification_repo=clarification_repo)
    result = await service.resolve_coherence_ambiguity_clarification(rid, pid, resolved_as="incoherent")

    assert result.resolved_as_coherent is False
    clarification_repo.resolve_coherence_ambiguity.assert_awaited_once_with(
        request_id=rid, resolved_as="incoherent", professor_id=pid,
    )


@pytest.mark.anyio
async def test_resolve_coherence_ambiguity_not_found():
    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = None

    service = _make_service(clarification_repo=clarification_repo)
    with pytest.raises(ClarificationRequestNotFoundError):
        await service.resolve_coherence_ambiguity_clarification(uuid.uuid4(), uuid.uuid4(), resolved_as="coherent")


@pytest.mark.anyio
async def test_resolve_coherence_ambiguity_rejects_alternative_answer_kind():
    """
    Garde-fou symétrique à test_validate_alternative_answer_rejects_non_mda_
    clarification — jamais une décision coherent/incoherent appliquée à une
    ligne ALTERNATIVE_ANSWER (sémantique différente, endpoint dédié).
    """
    rid = uuid.uuid4()
    qid = uuid.uuid4()
    request = _make_mda_clarification(rid, qid)  # kind=ALTERNATIVE_ANSWER par défaut

    clarification_repo = AsyncMock()
    clarification_repo.get_by_id.return_value = request

    service = _make_service(clarification_repo=clarification_repo)
    with pytest.raises(InvalidClarificationTypeError):
        await service.resolve_coherence_ambiguity_clarification(rid, uuid.uuid4(), resolved_as="coherent")
    clarification_repo.resolve_coherence_ambiguity.assert_not_awaited()