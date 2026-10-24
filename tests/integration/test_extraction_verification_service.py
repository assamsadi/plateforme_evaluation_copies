"""
Test d'intégration — ExtractionVerificationService, contre une vraie DB
(même pattern que tests/integration/repositories/*.py). L'agent tourne
réellement, seul invoke_llm_with_fallback est mocké (comme dans les tests
unitaires de l'agent).

Couvre, en un seul scénario séquentiel (setup lourd partagé, cf. ticket
Phase 6 — "un test d'intégration complet") :
  1. Persistance réussie d'un exercice simple (Bareme, SolutionVariant
     TEACHER_ORIGINAL + ReasoningStep, AgentDecisionLog).
  2. Bareme Cas 2 (GLOBAL_PROPOSED) -> validation_status=PENDING_REVIEW.
  3. ReasoningClarificationRequest créée, récupérable groupée via
     get_pending_blocking_clarifications().
  4. publish() bloqué tant que la clarification BLOCKING est en attente,
     débloqué une fois répondue.
  5. Republication refusée une fois l'exercice publié.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.agents.context import AgentExecutionContext
from app.agents.extraction_verification_exceptions import ExerciseAlreadyPublishedError
from app.core.exceptions import IncompleteExerciseSetupError
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.bareme import BaremeValidationStatus
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import ClarificationSeverity
from app.domain.models.assessment.teacher_correction_block import (
    BlockEvidenceLevel,
    TeacherCorrectionBlock,
)
from app.domain.repositories.agent_decision_log_repository import SQLAlchemyAgentDecisionLogRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.reasoning_clarification_request_repository import (
    SQLAlchemyReasoningClarificationRequestRepository,
)
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.teacher_correction_block_repository import (
    SQLAlchemyTeacherCorrectionBlockRepository,
)
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.services.exercise_service import ExerciseService
from app.services.extraction_verification_service import ExtractionVerificationService
from app.agents.Extraction_Verification_Agent import (
    _BaremeSchema,
    _DecompositionSchema,
    _SubquestionPointsSchema,
)


async def _seed_exercise_with_question(db_session) -> tuple[Exercise, Question, uuid.UUID]:
    """Programme/Groupe/Module/Professeur + Exercise DRAFT + 1 Question."""
    user_repo = SQLAlchemyUserRepository(db_session)

    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add_all([group, module])
    await db_session.flush()

    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com",
        hashed_password="hash",
        first_name="Prof",
        last_name="Test",
        department="Maths",
        title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    exercise = Exercise(
        module_id=module.id,
        created_by_professor_id=professor.id,
        title="Exercice de test",
        status=ExerciseStatus.DRAFT,
    )
    db_session.add(exercise)
    await db_session.flush()

    question = Question(
        exercise_id=exercise.id,
        order=1,
        statement="Calculer l'aire du rectangle.",
    )
    db_session.add(question)
    await db_session.flush()

    block = TeacherCorrectionBlock(
        exercise_id=exercise.id,
        question_id=question.id,
        content_type=ExtractionContentType.TEXT,
        raw_text="Aire = L * l = 12 cm2. Note globale : 5 points.",
        evidence_level=BlockEvidenceLevel.LABEL_EXPLICITE,
        justification="seed de test",
    )
    db_session.add(block)
    await db_session.flush()

    return exercise, question, professor.id


def _mock_llm_response(schema_cls: type, payload: dict):
    """
    Construit une VRAIE instance du schéma structured-output (response_schema
    dans invoke_llm_with_fallback) — pas un MagicMock avec .content en JSON.
    L'agent utilise response_schema=... (structured output) depuis le fix
    session du 2026-08-17 (cf. mémoire [[project_extraction_verification_agent_json_fix]]) ;
    _decompose_steps/_extract_or_propose_bareme/_extract_subquestion_points
    font `result if isinstance(result, SchemaClass) else SchemaClass.model_validate(result)`
    — un MagicMock().content ne correspond plus au contrat réel et ne serait
    jamais validé correctement (ancien pattern JSON-en-texte, périmé).
    """
    parsed = schema_cls.model_validate(payload)
    fake_spec = MagicMock()
    fake_spec.provider = "groq"
    fake_spec.model_name = "llama-3.3-70b"
    return (parsed, fake_spec, False, {"total_tokens": 100})


_DECOMPOSITION_PAYLOAD = {
    "steps": [
        {
            "step_ref": "s1", "order": 1, "step_type": "given_data",
            "description": "L=4cm, l=3cm", "source_span": "L=4cm, l=3cm",
            "formula": None, "anomaly_detected": False, "anomaly_justification": None,
        },
        {
            "step_ref": "s2", "order": 2, "step_type": "computation",
            "description": "Aire = 12 cm2", "source_span": "Aire = 4*3 = 12 cm2",
            "formula": None, "anomaly_detected": False, "anomaly_justification": None,
        },
        {
            "step_ref": "s3", "order": 3, "step_type": "conclusion",
            "description": "Aire = 12 cm2", "source_span": "Donc l'aire est 12 cm2",
            "formula": None, "anomaly_detected": False, "anomaly_justification": None,
        },
    ],
    "involves_graph_plot": False,
    "mandated_method": None,
}

_BAREME_PAYLOAD_GLOBAL_PROPOSED = {
    "case": "GLOBAL_PROPOSED",
    "total_points": 5.0,
    "criteria": [
        {"label": "exactitude", "points": 2.5, "correction_mode": "solution_worked", "verifiable_conditions": [], "disqualifying": False},
        {"label": "cohérence", "points": 1.0, "correction_mode": "solution_worked", "verifiable_conditions": [], "disqualifying": False},
        {"label": "complétude", "points": 1.0, "correction_mode": "solution_worked", "verifiable_conditions": [], "disqualifying": False},
        {"label": "justification", "points": 0.5, "correction_mode": "solution_worked", "verifiable_conditions": [], "disqualifying": False},
    ],
    "justification": "Proposition basée sur la décomposition (aucun détail par critère fourni).",
}


@pytest.mark.anyio
async def test_verify_extraction_full_lifecycle(db_session):
    exercise, question, professor_id = await _seed_exercise_with_question(db_session)

    exercise_repo = SQLAlchemyExerciseRepository(db_session)
    blocks_repo = SQLAlchemyTeacherCorrectionBlockRepository(db_session)
    variants_repo = SQLAlchemySolutionVariantRepository(db_session)
    decision_log_repo = SQLAlchemyAgentDecisionLogRepository(db_session)
    clarification_repo = SQLAlchemyReasoningClarificationRequestRepository(db_session)
    module_repo = SQLAlchemyModuleRepository(db_session)
    user_repo = SQLAlchemyUserRepository(db_session)

    service = ExtractionVerificationService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=blocks_repo,
        solution_variant_repository=variants_repo,
        decision_log_repository=decision_log_repo,
        clarification_repository=clarification_repo,
    )

    responses = [
        _mock_llm_response(_DecompositionSchema, _DECOMPOSITION_PAYLOAD),
        _mock_llm_response(_BaremeSchema, _BAREME_PAYLOAD_GLOBAL_PROPOSED),
    ]

    # --- 1/2. Persistance réussie + Bareme Cas 2 -> PENDING_REVIEW ---
    with patch(
        "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
        side_effect=responses,
    ):
        with patch("app.observability.langfuse.langfuse", MagicMock()):
            result = await service.verify_extraction(exercise.id)

    assert result.questions_processed == 1
    assert result.baremes_created == 1
    assert result.baremes_pending_review == 1
    assert result.reasoning_steps_created == 3
    assert result.decomposition_failures == 0
    assert result.bareme_failures == 0
    assert result.blocking_clarifications_created >= 1

    reloaded_exercise = await exercise_repo.get_by_id(exercise.id)
    reloaded_question = next(q for q in reloaded_exercise.questions if q.id == question.id)
    assert reloaded_question.bareme is not None
    assert reloaded_question.bareme.validation_status == BaremeValidationStatus.PENDING_REVIEW

    # SolutionVariant TEACHER_ORIGINAL is_reference=True créée.
    variants = await variants_repo.list_by_question(question.id)
    assert len(variants) == 1
    assert variants[0].is_reference is True
    assert variants[0].source.value == "teacher_original"

    # --- 3. Clarification BLOCKING créée, récupérable groupée ---
    pending = await service.get_pending_blocking_clarifications(exercise.id)
    assert len(pending) >= 1
    blocking = pending[0]
    assert blocking.severity == ClarificationSeverity.BLOCKING
    assert blocking.related_entity_type == "Bareme"
    assert blocking.related_entity_id == reloaded_question.bareme.id
    assert "Confirmez-vous" in blocking.agent_question

    # --- 4. publish() bloqué tant que la clarification est PENDING ---
    exercise_service = ExerciseService(
        exercise_repository=exercise_repo,
        module_repository=module_repo,
        user_repository=user_repo,
        clarification_repository=clarification_repo,
        solution_variant_repository=variants_repo,
        # Bug préexistant corrigé ici (sans rapport avec le chantier création
        # upload-only) : submission_repository est un paramètre requis
        # depuis l'audit CRUD authoring (ExerciseService.delete), jamais mis
        # à jour dans ce test d'intégration — TypeError à la construction.
        submission_repository=SQLAlchemySubmissionRepository(db_session),
    )
    with pytest.raises(IncompleteExerciseSetupError):
        await exercise_service.publish(
            exercise_id=exercise.id,
            requesting_professor_id=professor_id,
            status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
            course_id=None,
            deadline=None,
        )

    # Répond à la clarification -> ne bloque plus.
    await clarification_repo.answer(
        request_id=blocking.id,
        professor_answer="Répartition confirmée telle quelle.",
        answered_by_professor_id=professor_id,
    )
    pending_after_answer = await service.get_pending_blocking_clarifications(exercise.id)
    assert pending_after_answer == []

    # Confirmation professeur explicite (audit "garanties transverses",
    # Plan B) — requise par publish() en plus de la complétude technique.
    await exercise_service.confirm_publication_readiness(
        exercise_id=exercise.id, requesting_professor_id=professor_id,
    )

    published = await exercise_service.publish(
        exercise_id=exercise.id,
        requesting_professor_id=professor_id,
        status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
        course_id=None,
        deadline=None,
    )
    assert published.status == ExerciseStatus.PUBLISHED_AS_HOMEWORK

    # --- 5. Republication refusée une fois publié ---
    with pytest.raises(ExerciseAlreadyPublishedError):
        await service.verify_extraction(exercise.id)


_SUBQUESTION_POINTS_PAYLOAD = {
    "questions": [{"question_order": 1, "subquestion_points": {"1.1": 2, "1.2": 1}}]
}


@pytest.mark.anyio
async def test_verify_extraction_persists_subquestion_points_from_case0(db_session):
    """
    Chantier barème C2PCT natif (Cas 0) — preuve réelle contre une vraie DB :
    Question.subquestion_points est bien persisté depuis le résultat de
    l'agent, via set_question_subquestion_points (même principe que
    covered_subquestions déjà couvert ci-dessus).
    """
    exercise, question, _professor_id = await _seed_exercise_with_question(db_session)

    # Bloc SUPPLÉMENTAIRE (en plus du bloc seedé par le helper) contenant un
    # barème C2PCT natif explicite (motif "chiffre.chiffre" requis par le
    # pré-filtre du Cas 0) — _combine_text concatène tous les blocs d'une
    # question, jamais besoin de remplacer le bloc existant.
    blocks_repo = SQLAlchemyTeacherCorrectionBlockRepository(db_session)
    db_session.add(TeacherCorrectionBlock(
        exercise_id=exercise.id, question_id=question.id, content_type=ExtractionContentType.TEXT,
        raw_text="BARÈME\n1) 1.1 -> 2 points\n   1.2 -> 1 point",
        evidence_level=BlockEvidenceLevel.LABEL_EXPLICITE, justification="seed Cas 0",
    ))
    await db_session.flush()

    service = ExtractionVerificationService(
        exercise_repository=SQLAlchemyExerciseRepository(db_session),
        teacher_correction_block_repository=blocks_repo,
        solution_variant_repository=SQLAlchemySolutionVariantRepository(db_session),
        decision_log_repository=SQLAlchemyAgentDecisionLogRepository(db_session),
        clarification_repository=SQLAlchemyReasoningClarificationRequestRepository(db_session),
    )

    responses = [
        _mock_llm_response(_SubquestionPointsSchema, _SUBQUESTION_POINTS_PAYLOAD),
        _mock_llm_response(_DecompositionSchema, _DECOMPOSITION_PAYLOAD),
        _mock_llm_response(_BaremeSchema, _BAREME_PAYLOAD_GLOBAL_PROPOSED),
    ]

    with patch(
        "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback", side_effect=responses,
    ):
        with patch("app.observability.langfuse.langfuse", MagicMock()):
            await service.verify_extraction(exercise.id)

    reloaded = await SQLAlchemyExerciseRepository(db_session).get_by_id(exercise.id)
    reloaded_question = next(q for q in reloaded.questions if q.id == question.id)
    assert reloaded_question.subquestion_points == {"1.1": "2", "1.2": "1"}


# ---------------------------------------------------------------------------
# Reasoning_Graph_Agent v2 — preuve DB réelle que l'enrichissement (Agent 5)
# ne perd jamais les signaux déjà calculés par Agent 4 (canonical_form,
# dimensional_check_result, ...), et que les ReasoningStep sont mis à jour
# EN PLACE (jamais une nouvelle version qui superséderait la précédente).
# Cf. mémoire de session : Agent 5 v1 reparsait le texte source
# indépendamment d'Agent 4, ce qui supersédait ses steps et perdait
# canonical_form avant que Comparative_Evaluation_Agent ne puisse le lire.
# ---------------------------------------------------------------------------

_DECOMPOSITION_PAYLOAD_WITH_FORMULA = {
    "steps": [
        {
            "step_ref": "s1", "order": 1, "step_type": "given_data",
            "description": "L=4cm, l=3cm", "source_span": "L=4cm, l=3cm",
            "formula": None,
        },
        {
            "step_ref": "s2", "order": 2, "step_type": "computation",
            "description": "Aire = 12 cm2", "source_span": "Aire = 4*3 = 12 cm2",
            "formula": None,
        },
        {
            "step_ref": "s3", "order": 3, "step_type": "conclusion",
            "description": "Aire = 12 cm2", "source_span": "Donc l'aire est 12 cm2",
            # Formule en notation standard (pas de LaTeX nécessaire ici) —
            # déclenche _compute_canonical_form côté Agent 4, déjà vérifié
            # produire "Eq(A, L*l)" pour cette entrée exacte (cf. mémoire
            # [[project_extraction_verification_latex_math_fix]]).
            "formula": "A = L*l",
        },
    ],
}


async def _reasoning_graph_mock_invoke(task_type, messages, response_schema, context):
    """
    Reconstruit un enrichissement plausible (chaîne linéaire is_core_step=True)
    à partir des VRAIS step_id envoyés par le service (les ReasoningStep.id
    réels générés à la persistance d'Agent 4) — jamais des identifiants
    inventés à l'avance, pour que le test reste honnête sur le vrai contrat
    step_id in -> step_id out.
    """
    import json as _json

    from app.agents.Reasoning_Graph_Agent import _GraphEnrichmentSchema

    user_content = messages[1]["content"]
    steps_payload = _json.loads(user_content[user_content.index("[") : user_content.rindex("]") + 1])

    enrichments = []
    prev_id = None
    for sp in sorted(steps_payload, key=lambda s: s["order"]):
        enrichments.append({
            "step_id": sp["step_id"],
            "depends_on_refs": [prev_id] if prev_id else [],
            "is_core_step": True,
            "tools_used": [],
            "concept_tags": [],
        })
        prev_id = sp["step_id"]

    parsed = _GraphEnrichmentSchema.model_validate({
        "construction_confidence": 0.9,
        "enrichments": enrichments,
    })
    fake_spec = MagicMock()
    fake_spec.provider = "gemini"
    fake_spec.model_name = "test"
    return parsed, fake_spec, False, {}


@pytest.mark.anyio
async def test_reasoning_graph_agent_enriches_without_losing_canonical_form(db_session):
    from sqlalchemy import select

    from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepDependency
    from app.services.reasoning_graph_service import ReasoningGraphService

    exercise, question, _professor_id = await _seed_exercise_with_question(db_session)

    exercise_repo = SQLAlchemyExerciseRepository(db_session)
    blocks_repo = SQLAlchemyTeacherCorrectionBlockRepository(db_session)
    variants_repo = SQLAlchemySolutionVariantRepository(db_session)

    service = ExtractionVerificationService(
        exercise_repository=exercise_repo,
        teacher_correction_block_repository=blocks_repo,
        solution_variant_repository=variants_repo,
        decision_log_repository=SQLAlchemyAgentDecisionLogRepository(db_session),
        clarification_repository=SQLAlchemyReasoningClarificationRequestRepository(db_session),
    )

    responses = [
        _mock_llm_response(_DecompositionSchema, _DECOMPOSITION_PAYLOAD_WITH_FORMULA),
        _mock_llm_response(_BaremeSchema, _BAREME_PAYLOAD_GLOBAL_PROPOSED),
    ]
    with patch(
        "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback", side_effect=responses,
    ):
        with patch("app.observability.langfuse.langfuse", MagicMock()):
            result = await service.verify_extraction(exercise.id)

    assert result.reasoning_steps_created == 3

    variants = await variants_repo.list_by_question(question.id)
    assert len(variants) == 1
    variant = variants[0]

    # --- Étapes d'Agent 4 persistées : canonical_form déjà présent ---
    steps_before = await variants_repo.get_reasoning_steps_ordered(variant.id)
    assert len(steps_before) == 3
    conclusion_before = next(s for s in steps_before if s.order == 3)
    assert conclusion_before.extraction_signals is not None
    assert conclusion_before.extraction_signals.get("canonical_form") == "Eq(A, L*l)"

    # --- Reasoning_Graph_Agent (Agent 5), réel, enrichit les VRAIS steps ---
    with patch(
        "app.agents.Reasoning_Graph_Agent.invoke_llm_with_fallback",
        side_effect=_reasoning_graph_mock_invoke,
    ):
        with patch("app.observability.langfuse.langfuse", MagicMock()):
            reasoning_service = ReasoningGraphService(db_session)
            graph_read = await reasoning_service.build_graph_for_variant(variant.id)

    assert graph_read.is_valid_dag is True
    assert graph_read.step_count == 3

    # --- Vérification DB directe : canonical_form a SURVÉCU, mise à jour EN
    # PLACE (jamais une nouvelle version), et les arêtes DAG d'Agent 5 ont
    # remplacé la chaîne linéaire naïve posée par Agent 4 ---
    steps_after_result = await db_session.execute(
        select(ReasoningStep).where(ReasoningStep.variant_id == variant.id)
    )
    steps_after = list(steps_after_result.scalars().all())
    assert len(steps_after) == 3
    assert all(s.superseded_by is None for s in steps_after)
    assert all(s.version == 1 for s in steps_after)

    conclusion_after = next(s for s in steps_after if s.order == 3)
    assert conclusion_after.id == conclusion_before.id
    assert conclusion_after.extraction_signals.get("canonical_form") == "Eq(A, L*l)"
    assert conclusion_after.extraction_signals.get("is_core_step") is True
    assert "downstream_step_refs" in conclusion_after.extraction_signals

    deps_result = await db_session.execute(
        select(ReasoningStepDependency).where(
            ReasoningStepDependency.step_id.in_([s.id for s in steps_after])
        )
    )
    dependencies = list(deps_result.scalars().all())
    assert len(dependencies) == 2
