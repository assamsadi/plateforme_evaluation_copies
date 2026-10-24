import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_current_professor,
    get_current_user,
    get_decision_log_service,
    get_solution_variant_generation_service,
    get_solution_variant_service,
)
from app.domain.models.identity.user import User, Professor
from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.solution_schemas import (
    ReasoningClarificationAnswerRequest,
    ReasoningClarificationRequestRead,
    ReasoningStepRead,
    ReasoningStepUpdateRequest,
    ReasoningStepUpdateResponse,
    ResolveCoherenceAmbiguityRequest,
    SolutionVariantCreate,
    SolutionVariantRead,
    ValidateAlternativeAnswerRequest,
    VariantValidationRequest,
)
from app.domain.schemas.solution_variant_generation_schemas import (
    GuidedVariantGenerationAck,
    GuidedVariantGenerationRequest,
    SolutionVariantSummaryRead,
    VariantReviewRequest,
    VariantReviewResponse,
)
from app.domain.schemas.system_schemas import AgentDecisionLogRead
from app.services.decision_log_service import DecisionLogService
from app.services.solution_variant_generation_service import SolutionVariantGenerationService
from app.services.solution_variant_service import SolutionVariantService

router = APIRouter(tags=["teacher validation & solution variants"])


@router.post("/solution-variants", response_model=SolutionVariantRead, status_code=status.HTTP_201_CREATED)
async def create_solution_variant(
    schema: SolutionVariantCreate,
    variant_service: Annotated[SolutionVariantService, Depends(get_solution_variant_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    return await variant_service.create_variant(
        question_id=schema.question_id,
        content=schema.content,
        source=schema.source,
        difficulty_level=schema.difficulty_level,
        is_reference=schema.is_reference,
        structured_content=schema.structured_content,
        steps_data=[s.model_dump() for s in schema.reasoning_steps],
    )


@router.post("/solution-variants/{variant_id}/validate", response_model=SolutionVariantRead)
async def validate_solution_variant(
    variant_id: uuid.UUID,
    schema: VariantValidationRequest,
    variant_service: Annotated[SolutionVariantService, Depends(get_solution_variant_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    return await variant_service.validate_variant(
        variant_id=variant_id,
        professor_id=current_prof.id,
        status=schema.status,
        review_comment=schema.review_comment,
    )


@router.get("/solution-variants/{variant_id}/reasoning-graph", response_model=list[ReasoningStepRead])
async def get_reasoning_graph(
    variant_id: uuid.UUID,
    variant_service: Annotated[SolutionVariantService, Depends(get_solution_variant_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await variant_service.get_ordered_reasoning_graph(variant_id)


@router.patch("/reasoning-steps/{step_id}", response_model=ReasoningStepUpdateResponse)
async def update_reasoning_step(
    step_id: uuid.UUID,
    schema: ReasoningStepUpdateRequest,
    generation_service: Annotated[
        SolutionVariantGenerationService, Depends(get_solution_variant_generation_service)
    ],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Correction ciblée d'UNE étape du graphe de raisonnement (cf. mémoire de
    session) — distinct de /solution-variants/{id}/review (action=MODIFIED),
    qui ne permet de réécrire que TOUT le `content` de la variante en bloc.
    """
    step = await generation_service.update_reasoning_step(
        step_id=step_id,
        professor_id=current_prof.id,
        description=schema.description,
        formula=schema.formula,
    )
    return ReasoningStepUpdateResponse(id=step.id, description=step.description, formula=step.formula)


@router.get("/clarifications/pending", response_model=list[ReasoningClarificationRequestRead])
async def list_pending_clarifications(
    variant_service: Annotated[SolutionVariantService, Depends(get_solution_variant_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    return await variant_service.list_pending_clarifications()


@router.post("/clarifications/{request_id}/answer", response_model=ReasoningClarificationRequestRead)
async def answer_clarification(
    request_id: uuid.UUID,
    schema: ReasoningClarificationAnswerRequest,
    variant_service: Annotated[SolutionVariantService, Depends(get_solution_variant_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    return await variant_service.answer_clarification(
        request_id=request_id,
        professor_id=current_prof.id,
        answer=schema.professor_answer,
    )


@router.post(
    "/clarifications/{request_id}/validate-alternative-answer",
    response_model=ReasoningClarificationRequestRead,
)
async def validate_alternative_answer(
    request_id: uuid.UUID,
    schema: ValidateAlternativeAnswerRequest,
    variant_service: Annotated[SolutionVariantService, Depends(get_solution_variant_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Câblage HITL indexation RAG (Priorité 1) — résout une clarification
    MULTIPLE_DISTINCT_ANSWERS (Comparative_Evaluation_Agent). Endpoint
    DÉDIÉ, distinct de /answer (texte libre, sémantique différente) :
    accepted=True indexe la réponse candidate dans ValidatedAlternative
    Answer, accepted=False la rejette sans rien indexer.
    """
    return await variant_service.validate_alternative_answer_clarification(
        request_id=request_id,
        professor_id=current_prof.id,
        accepted=schema.accepted,
    )


@router.post(
    "/clarifications/{request_id}/resolve-coherence-ambiguity",
    response_model=ReasoningClarificationRequestRead,
)
async def resolve_coherence_ambiguity(
    request_id: uuid.UUID,
    schema: ResolveCoherenceAmbiguityRequest,
    variant_service: Annotated[SolutionVariantService, Depends(get_solution_variant_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Correctif AMBIGUOUS_COHERENCE — résout l'AUTRE sous-type de clarification
    MULTIPLE_DISTINCT_ANSWERS (Comparative_Evaluation_Agent), distinct de
    /validate-alternative-answer (accept/reject une réponse candidate,
    sémantique différente) : une décision sur la nature même du cas.
    resolved_as="coherent"/"incoherent" -> le traitement reprend, à la
    prochaine exécution de comparative_evaluation_node, comme si le filtre
    de cohérence avait initialement renvoyé COHERENT/INCOHERENT.
    """
    return await variant_service.resolve_coherence_ambiguity_clarification(
        request_id=request_id,
        professor_id=current_prof.id,
        resolved_as=schema.resolved_as,
    )


@router.get(
    "/questions/{question_id}/solution-variants",
    response_model=list[SolutionVariantSummaryRead],
)
async def list_question_solution_variants(
    question_id: uuid.UUID,
    generation_service: Annotated[
        SolutionVariantGenerationService, Depends(get_solution_variant_generation_service)
    ],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Découverte des variantes d'une question (gap trouvé le 2026-08-18) —
    sans cet endpoint, /review exige un variant_id que rien ne renvoyait en
    liste : le professeur n'avait aucun moyen de savoir QUELLES variantes
    existent pour une question donnée, seulement de valider une variante
    dont il connaissait déjà l'ID par ailleurs. Inclut la variante de
    référence (is_reference=True) pour comparaison.
    """
    return await generation_service.list_variants_for_question(question_id, current_prof.id)


@router.post(
    "/questions/{question_id}/solution-variants/generate-guided",
    response_model=GuidedVariantGenerationAck,
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_guided_solution_variant(
    question_id: uuid.UUID,
    schema: GuidedVariantGenerationRequest,
    generation_service: Annotated[
        SolutionVariantGenerationService, Depends(get_solution_variant_generation_service)
    ],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Déclencheur guidé (2.3, cf. audit Solution_Variant_Generation_Agent §1c) —
    réservé au professeur propriétaire de l'exercice de la question ciblée.
    Traitement en tâche de fond (aucune copie d'étudiant en attente ici,
    contrairement à 2.2) : dispatch Celery, notification au prof quand prêt.
    """
    await generation_service.ensure_professor_owns_question(question_id, current_prof.id)

    from app.tasks.solution_variant_generation_tasks import generate_guided_variant_task
    generate_guided_variant_task.delay(
        question_id=str(question_id),
        professor_id=str(current_prof.id),
        method_hint=schema.method_hint,
        concept_hint=schema.concept_hint,
    )

    return GuidedVariantGenerationAck(question_id=question_id)


@router.get(
    "/questions/{question_id}/decision-logs",
    response_model=CursorPage[AgentDecisionLogRead],
)
async def get_question_agent_decision_logs(
    question_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    decision_log_service: Annotated[
        DecisionLogService, Depends(get_decision_log_service)
    ],
    cursor: str | None = None,
    limit: int = 50,
):
    """
    Traçabilité professeur (cf. mémoire de session, Solution_Variant_
    Generation_Agent) — le détail de CHAQUE tentative de génération de
    variante pour cette question, acceptée (ACCEPTED) ou rejetée
    (REJECTED_SYMPY/REJECTED_DUPLICATE/REJECTED_SCHEMA), avec le nom de
    stratégie, la raison de rejet et le score de distinction. Sans cet
    endpoint, ces logs (related_entity_type="Question") n'étaient
    accessibles par AUCUN endpoint existant — get_exercise_decision_logs
    filtre strictement sur related_entity_type="Exercise", jamais
    "Question", donc ne les retourne jamais.

    Même politique d'accès que /exercises/{id}/decision-logs (DRAFT :
    professeur créateur uniquement ; publié : créateur ou admin).
    """
    return await decision_log_service.get_question_decision_logs(
        question_id=question_id,
        requesting_user=current_user,
        cursor=cursor,
        limit=limit,
    )


@router.post("/solution-variants/{variant_id}/review", response_model=VariantReviewResponse)
async def review_solution_variant(
    variant_id: uuid.UUID,
    schema: VariantReviewRequest,
    generation_service: Annotated[
        SolutionVariantGenerationService, Depends(get_solution_variant_generation_service)
    ],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Endpoint des 4 actions du rapport de validation professeur (Accepter/
    Refuser/Modifier/Supprimer), cf. audit Solution_Variant_Generation_Agent
    §6/§10 — variant_id vient toujours du chemin, jamais du corps (ignore
    silencieusement un variant_id de corps divergent plutôt que de risquer
    une confusion entre la ressource ciblée par l'URL et le payload).
    """
    await generation_service.ensure_professor_owns_variant(variant_id, current_prof.id)

    request = schema.model_copy(update={"variant_id": variant_id})
    variant, equity_report = await generation_service.review_variant_decision(request, current_prof.id)

    if variant is None:
        return VariantReviewResponse(deleted=True, retroactive_equity=equity_report)

    structured = variant.structured_content or {}
    return VariantReviewResponse(
        variant_id=variant.id,
        status=variant.status,
        content=variant.content,
        deleted=False,
        retroactive_equity=equity_report,
        # Traçabilité (cf. mémoire de session) : absents (None) pour une
        # variante non générée par IA — structured_content n'a jamais ces
        # clés dans ce cas, .get() reste sûr.
        strategy_name=structured.get("strategy_name"),
        distinction_score=structured.get("distinction_score"),
        intermediate_check_note=structured.get("intermediate_check_note"),
    )
