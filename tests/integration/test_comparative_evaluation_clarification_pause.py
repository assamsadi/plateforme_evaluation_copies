"""
Test d'intégration — pause HITL réelle sur clarification BLOCKING résolvable
(correctif découvertes annexes, priorité 1), à travers le graph LangGraph
COMPILÉ (checkpointer Postgres réel), pas des mocks isolés.

Avant le premier correctif (découvertes annexes, priorité 1), une
ClarificationRequest BLOCKING produite par Comparative_Evaluation_Agent
(MULTIPLE_DISTINCT_ANSWERS) ne déclenchait JAMAIS de pause. Ce premier
correctif a couvert le sous-cas COHERENT + aucun match RAG ("réponse
alternative inédite"). CE fichier couvre désormais AUSSI le second sous-cas,
AMBIGUOUS_COHERENCE ("effort réel ou hors-sujet ?"), résolu via le correctif
dédié (POST /clarifications/{id}/resolve-coherence-ambiguity) — les DEUX
sous-cas déclenchent maintenant une pause réelle, symétriquement.

Couvre :
  1. Clarification BLOCKING résolvable (alternative_answer) -> pause réelle
     (interrupt, reason=clarification_review, paused_at_node=comparative_
     evaluation_node), ReasoningClarificationRequest persistée.
  2. Reprise SANS résolution (le prof n'a pas encore répondu) -> re-pause
     immédiate, JAMAIS de doublon de ReasoningClarificationRequest (dédup
     contre list_pending_blocking_by_exercise).
  3. Reprise APRÈS résolution simulée -> le run continue réellement jusqu'à
     evaluation_node (Evaluation persistée).
  4. AMBIGUOUS_COHERENCE seule -> pause réelle également (comparative_
     clarification_kind=COHERENCE_AMBIGUITY), même mécanisme, symétrique
     au sous-cas 1.
  5. Reprise sans résoudre l'ambiguïté -> jamais de doublon (même dédup).
  6. Résolution "coherent"/"incoherent" via le repository (simule l'appel
     API) -> la reprise atteint evaluation_node (branche réutilisée déjà
     prouvée équivalente au niveau agent, cf. test_comparative_evaluation_
     agent.py — ce fichier prouve le CÂBLAGE bout en bout, pas la logique
     de notation elle-même, mockée ici comme dans les tests 1-3).
"""
import uuid
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest
from sqlalchemy import select
from langgraph.types import Command

from app.agents.Comparative_Evaluation_Agent import (
    ClarificationRequest,
    ClarificationSeverity,
    CoherenceStatus,
    ComparativeEvaluationAgent,
    ComparativeEvaluationReport,
    CriterionEvaluationResult,
)
from app.agents.Extraction_Verification_Agent import CorrectionMode
from app.agents.OCR_Extraction_Agent import OCRExtractionAgent
from app.agents.Question_Attachment_Agent import AttachmentResult, QuestionAttachmentAgent
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.bareme import Bareme, BaremeValidationStatus
from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import (
    ComparativeClarificationKind,
    ReasoningClarificationRequest,
)
from app.domain.repositories.reasoning_clarification_request_repository import (
    SQLAlchemyReasoningClarificationRequestRepository,
)
from app.domain.models.assessment.solution_variant import (
    SolutionVariant,
    VariantDifficulty,
    VariantSource,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.schemas.submission_schemas import AttachedExtractedBlock, RawExtractedBlock
from app.graph.checkpointer import get_checkpointer, setup_checkpointer_tables
from app.graph.pipeline_graph import compile_pipeline_graph
from app.graph.state import PipelineState


def _make_valid_scan_bytes() -> bytes:
    arr = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.putText(arr, "Copie etudiant", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.rectangle(arr, (10, 10), (390, 390), (0, 0, 0), 2)
    _, buffer = cv2.imencode(".png", arr)
    return buffer.tobytes()


def _make_raw_block() -> RawExtractedBlock:
    return RawExtractedBlock(
        image_crop_path="crops/block1.png", content_type="TEXT",
        prediction_ocr="Une reponse alternative inedite.", confidence_score=Decimal("0.9"),
        bounding_box={"x": 0, "y": 0, "w": 10, "h": 10}, page_number=1,
        block_order_index=0, evidence_level="label_explicite",
    )


async def _seed_submission(db_session):
    user_repo = SQLAlchemyUserRepository(db_session)

    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add_all([group, module])
    await db_session.flush()

    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Pause", department="Info", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Pause", student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id, enrollment_year=2024, level="L3",
    )
    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice pause HITL", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()
    question = Question(exercise_id=exercise.id, order=1, statement="Question ouverte.")
    db_session.add(question)
    await db_session.flush()
    bareme = Bareme(
        question_id=question.id, points=Decimal("5.00"),
        criteria=[{
            "id": "crit-1", "label": "reponse", "points": 5.0,
            "correction_mode": CorrectionMode.MULTIPLE_DISTINCT_ANSWERS.value,
            "verifiable_conditions": [], "disqualifying": False, "test_cases": [],
            "reference_code": None, "expected_complexity": None,
        }],
        validation_status=BaremeValidationStatus.CONFIRMED,
    )
    db_session.add(bareme)
    reference_variant = SolutionVariant(
        question_id=question.id, is_reference=True, content="Une des reponses possibles.",
        version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE,
    )
    db_session.add(reference_variant)
    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.PENDING_OCR, document_path="submissions/doc.pdf",
        document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()
    return exercise, question, submission, professor


def _make_initial_state(exercise, submission) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(submission.id), flow_type="student_evaluation", trace_id=str(submission.id),
        exercise_id=str(exercise.id), submission_id=str(submission.id),
        module_id=str(exercise.module_id), student_id=str(submission.student_id),
        raw_file_path=submission.document_path, mime_type="image/png",
        created_at=now, updated_at=now,
    )


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


def _blocking_report(question_id) -> ComparativeEvaluationReport:
    """Cas résolvable : COHERENT + pas de match RAG -> BLOCKING persistée."""
    return ComparativeEvaluationReport(
        question_id=question_id,
        criterion_results=[
            CriterionEvaluationResult(
                criterion_id="crit-1", correction_mode=CorrectionMode.MULTIPLE_DISTINCT_ANSWERS,
                is_satisfied=None, coherence_status=CoherenceStatus.COHERENT,
                clarification_request=ClarificationRequest(
                    related_field="criterion[crit-1].multiple_distinct_answers",
                    agent_question="Reponse alternative inedite valide ?",
                    proposed_answer="Valider cette reponse alternative comme correcte.",
                    severity=ClarificationSeverity.BLOCKING,
                ),
                justification="test", confidence_score=0.9,
            ),
        ],
        overall_confidence=0.9, subquestion_judgments=[],
    )


def _clean_report(question_id) -> ComparativeEvaluationReport:
    """Après résolution : plus aucune clarification (simule le nouveau verdict)."""
    return ComparativeEvaluationReport(
        question_id=question_id,
        criterion_results=[
            CriterionEvaluationResult(
                criterion_id="crit-1", correction_mode=CorrectionMode.MULTIPLE_DISTINCT_ANSWERS,
                is_satisfied=True, score_ratio=1.0, coherence_status=CoherenceStatus.COHERENT,
                clarification_request=None, justification="resolu", confidence_score=0.95,
            ),
        ],
        overall_confidence=0.95, subquestion_judgments=[],
    )


def _ambiguous_only_report(question_id) -> ComparativeEvaluationReport:
    """Cas NON résolvable (AMBIGUOUS_COHERENCE) -> ne doit JAMAIS déclencher de pause."""
    return ComparativeEvaluationReport(
        question_id=question_id,
        criterion_results=[
            CriterionEvaluationResult(
                criterion_id="crit-1", correction_mode=CorrectionMode.MULTIPLE_DISTINCT_ANSWERS,
                is_satisfied=None, coherence_status=CoherenceStatus.AMBIGUOUS_COHERENCE,
                clarification_request=ClarificationRequest(
                    related_field="criterion[crit-1].multiple_distinct_answers",
                    agent_question="Effort reel ou hors sujet ?", proposed_answer=None,
                    severity=ClarificationSeverity.BLOCKING,
                ),
                justification="test", confidence_score=0.7,
            ),
        ],
        overall_confidence=0.7, subquestion_judgments=[],
    )


def _all_patches(db_session, raw_block, attached_block, mock_event_publisher, comparative_result) -> ExitStack:
    """
    ExitStack unique (patches DB session par nœud + isolation LLM/Azure +
    verdict mocké de Comparative_Evaluation_Agent) — évite la syntaxe
    `with (a, *b, c):` qui ne déballe PAS une liste dynamique de context
    managers (chaque élément après `*` doit être une expression de context
    manager littérale, pas un itérable à étaler).
    """
    stack = ExitStack()
    for target in (
        "app.graph.nodes.entry_router_node.get_db_context",
        "app.graph.nodes.question_attachment_node.get_db_context",
        "app.graph.nodes.contestation_verification_node.get_db_context",
        "app.graph.nodes.comparative_evaluation_node.get_db_context",
        "app.graph.nodes.evaluation_node.get_db_context",
        "app.graph.nodes.competency_assessment_node.get_db_context",
        "app.graph.nodes.recommendation_node.get_db_context",
        "app.graph.nodes.feedback_node.get_db_context",
    ):
        stack.enter_context(patch(target, lambda: _reuse_session(db_session)))
    stack.enter_context(patch(
        "app.services.submission_ocr_pipeline_service.storage_service.download",
        new_callable=AsyncMock, return_value=_make_valid_scan_bytes(),
    ))
    stack.enter_context(patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[raw_block])))
    stack.enter_context(patch.object(
        QuestionAttachmentAgent, "execute",
        AsyncMock(return_value=AttachmentResult(attached_blocks=[attached_block])),
    ))
    stack.enter_context(patch(
        "app.services.submission_ocr_pipeline_service.EventPublisherService",
        return_value=mock_event_publisher,
    ))
    stack.enter_context(patch("app.observability.langfuse.langfuse", MagicMock()))
    stack.enter_context(patch.object(
        ComparativeEvaluationAgent, "execute", AsyncMock(return_value=comparative_result),
    ))
    # Le run atteint désormais feedback_node (chantier Feedback_Agent, câblé
    # après recommendation_node) — sans ce mock, le SEUL appel LLM du
    # pipeline tenterait un vrai appel réseau ici, hors du périmètre de ce
    # fichier (pause de clarification, pas Feedback_Agent).
    feedback_response = MagicMock()
    feedback_response.content = "Continue ainsi, comment pourrais-tu vérifier ton résultat ?"
    feedback_spec = MagicMock(provider="groq", model_name="llama-3.3-70b-versatile")
    stack.enter_context(patch(
        "app.agents.Feedback_Agent.invoke_llm_with_fallback",
        AsyncMock(return_value=(feedback_response, feedback_spec, False, {})),
    ))
    return stack


@pytest.mark.anyio
async def test_blocking_resolvable_clarification_pauses_the_graph(db_session):
    exercise, question, submission, professor = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    raw_block = _make_raw_block()
    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(), submission_id=submission.id, question_id=question.id,
    )
    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _blocking_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)
            result = await graph.ainvoke(Command(resume="confirmed"), config=config)

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["reason"] == "clarification_review"
    assert result["__interrupt__"][0].value["paused_at_node"] == "comparative_evaluation_node"

    clarifications = (
        await db_session.execute(
            select(ReasoningClarificationRequest).where(
                ReasoningClarificationRequest.related_entity_id == question.id
            )
        )
    ).scalars().all()
    assert len(clarifications) == 1
    assert clarifications[0].criterion_id == "crit-1"


@pytest.mark.anyio
async def test_resume_without_resolution_never_duplicates_clarification(db_session):
    exercise, question, submission, professor = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    raw_block = _make_raw_block()
    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(), submission_id=submission.id, question_id=question.id,
    )
    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _blocking_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)
            await graph.ainvoke(Command(resume="confirmed"), config=config)
            # Reprise SANS que le prof n'ait résolu la clarification (même
            # mock encore blocking) -> re-exécution de comparative_
            # evaluation_node (cf. CLARIFICATION_RESOLUTION_ROUTING_TABLE),
            # jamais un doublon de ReasoningClarificationRequest.
            result = await graph.ainvoke(Command(resume="clarification_reviewed"), config=config)

    assert "__interrupt__" in result  # toujours en pause, jamais perdu

    clarifications = (
        await db_session.execute(
            select(ReasoningClarificationRequest).where(
                ReasoningClarificationRequest.related_entity_id == question.id
            )
        )
    ).scalars().all()
    assert len(clarifications) == 1  # jamais 2


@pytest.mark.anyio
async def test_resume_after_resolution_reaches_evaluation_node(db_session):
    exercise, question, submission, professor = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    raw_block = _make_raw_block()
    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(), submission_id=submission.id, question_id=question.id,
    )
    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _blocking_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)
            await graph.ainvoke(Command(resume="confirmed"), config=config)

    # Résolution simulée : le prochain passage de Comparative_Evaluation_Agent
    # ne renvoie plus de clarification (comme si validate-alternative-answer
    # avait fait matcher le RAG au prochain appel réel).
    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _clean_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            result = await graph.ainvoke(Command(resume="clarification_reviewed"), config=config)

    assert "__interrupt__" not in result  # le run est allé jusqu'au bout

    evaluations = (
        await db_session.execute(select(Evaluation).where(Evaluation.submission_id == submission.id))
    ).scalars().all()
    assert len(evaluations) == 1


@pytest.mark.anyio
async def test_ambiguous_coherence_triggers_real_pause(db_session):
    """
    Correctif AMBIGUOUS_COHERENCE — symétrique à test_blocking_resolvable_
    clarification_pauses_the_graph, pour le second sous-cas. La ligne
    persistée porte comparative_clarification_kind=COHERENCE_AMBIGUITY
    (jamais ALTERNATIVE_ANSWER) — c'est ce discriminant qui permettra à
    /resolve-coherence-ambiguity de la reconnaître comme telle.
    """
    exercise, question, submission, professor = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    raw_block = _make_raw_block()
    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(), submission_id=submission.id, question_id=question.id,
    )
    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _ambiguous_only_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)
            result = await graph.ainvoke(Command(resume="confirmed"), config=config)

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["reason"] == "clarification_review"
    assert result["__interrupt__"][0].value["paused_at_node"] == "comparative_evaluation_node"

    clarifications = (
        await db_session.execute(
            select(ReasoningClarificationRequest).where(
                ReasoningClarificationRequest.related_entity_id == question.id
            )
        )
    ).scalars().all()
    assert len(clarifications) == 1
    assert clarifications[0].comparative_clarification_kind == ComparativeClarificationKind.COHERENCE_AMBIGUITY
    assert clarifications[0].criterion_id == "crit-1"

    evaluations = (
        await db_session.execute(select(Evaluation).where(Evaluation.submission_id == submission.id))
    ).scalars().all()
    assert evaluations == []  # rien de noté tant que la pause n'est pas résolue


@pytest.mark.anyio
async def test_resume_without_resolving_ambiguity_never_duplicates(db_session):
    exercise, question, submission, professor = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    raw_block = _make_raw_block()
    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(), submission_id=submission.id, question_id=question.id,
    )
    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _ambiguous_only_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)
            await graph.ainvoke(Command(resume="confirmed"), config=config)
            # Reprise SANS que le prof n'ait résolu l'ambiguïté (même mock
            # encore ambigu) -> re-exécution de comparative_evaluation_node,
            # jamais un doublon de ReasoningClarificationRequest.
            result = await graph.ainvoke(Command(resume="clarification_reviewed"), config=config)

    assert "__interrupt__" in result  # toujours en pause

    clarifications = (
        await db_session.execute(
            select(ReasoningClarificationRequest).where(
                ReasoningClarificationRequest.related_entity_id == question.id
            )
        )
    ).scalars().all()
    assert len(clarifications) == 1  # jamais 2


@pytest.mark.anyio
async def test_resolving_ambiguity_as_coherent_then_resume_reaches_evaluation_node(db_session):
    """
    Simule l'appel API /resolve-coherence-ambiguity (via le repository
    directement, même effet) avec resolved_as="coherent", puis la reprise
    du graph — doit atteindre evaluation_node comme n'importe quelle
    résolution. La preuve que "coherent" réutilise réellement la même
    branche que COHERENT natif est au niveau agent (test_comparative_
    evaluation_agent.py) — ici, câblage bout en bout uniquement.
    """
    exercise, question, submission, professor = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    raw_block = _make_raw_block()
    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(), submission_id=submission.id, question_id=question.id,
    )
    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _ambiguous_only_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)
            await graph.ainvoke(Command(resume="confirmed"), config=config)

    clarification = (
        await db_session.execute(
            select(ReasoningClarificationRequest).where(
                ReasoningClarificationRequest.related_entity_id == question.id
            )
        )
    ).scalar_one()
    clarification_repo = SQLAlchemyReasoningClarificationRequestRepository(db_session)
    await clarification_repo.resolve_coherence_ambiguity(
        request_id=clarification.id, resolved_as="coherent", professor_id=professor.id,
    )
    await db_session.flush()

    # Résolution simulée côté agent : le prochain passage ne renvoie plus de
    # clarification (comme si le bypass LLM + RAG avait abouti à un match).
    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _clean_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            result = await graph.ainvoke(Command(resume="clarification_reviewed"), config=config)

    assert "__interrupt__" not in result

    evaluations = (
        await db_session.execute(select(Evaluation).where(Evaluation.submission_id == submission.id))
    ).scalars().all()
    assert len(evaluations) == 1


@pytest.mark.anyio
async def test_resolving_ambiguity_as_incoherent_then_resume_reaches_evaluation_node(db_session):
    exercise, question, submission, professor = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    raw_block = _make_raw_block()
    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(), submission_id=submission.id, question_id=question.id,
    )
    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, _ambiguous_only_report(question.id)):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)
            await graph.ainvoke(Command(resume="confirmed"), config=config)

    clarification = (
        await db_session.execute(
            select(ReasoningClarificationRequest).where(
                ReasoningClarificationRequest.related_entity_id == question.id
            )
        )
    ).scalar_one()
    clarification_repo = SQLAlchemyReasoningClarificationRequestRepository(db_session)
    resolved = await clarification_repo.resolve_coherence_ambiguity(
        request_id=clarification.id, resolved_as="incoherent", professor_id=professor.id,
    )
    assert resolved.resolved_as_coherent is False
    await db_session.flush()

    # "incoherent" -> traité comme incorrect, jamais de clarification (même
    # branche que INCOHERENT natif, cf. agent) — le mock reflète ce verdict.
    incorrect_report = ComparativeEvaluationReport(
        question_id=question.id,
        criterion_results=[
            CriterionEvaluationResult(
                criterion_id="crit-1", correction_mode=CorrectionMode.MULTIPLE_DISTINCT_ANSWERS,
                is_satisfied=False, score_ratio=0.0, coherence_status=CoherenceStatus.INCOHERENT,
                clarification_request=None, justification="incoherent, resolu", confidence_score=0.9,
            ),
        ],
        overall_confidence=0.9, subquestion_judgments=[],
    )
    with _all_patches(db_session, raw_block, attached_block, mock_event_publisher, incorrect_report):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            result = await graph.ainvoke(Command(resume="clarification_reviewed"), config=config)

    assert "__interrupt__" not in result

    # Câblage bout en bout uniquement (cf. docstring module) — la
    # projection reste vide de covered_subquestions dans ce scénario
    # minimal, donc la valeur exacte du score n'est pas significative ici
    # (0.00 par construction, cf. Pedagogical_Evaluation_Agent : aucune
    # sous-question couverte -> aucune base pour attribuer le moindre
    # point). Seul compte : le run a bien atteint evaluation_node.
    evaluations = (
        await db_session.execute(select(Evaluation).where(Evaluation.submission_id == submission.id))
    ).scalars().all()
    assert len(evaluations) == 1
