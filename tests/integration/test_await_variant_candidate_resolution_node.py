"""
Test d'intégration — await_variant_candidate_resolution_node.

Ce nœud (déclencheur 2.2 de Solution_Variant_Generation_Agent) est enregistré
dans pipeline_graph.py sans edge ENTRANTE (cf. son docstring et celui de
pipeline_graph.py : le déclencheur 2.2 lui-même reste hors périmètre). Les
2 premiers tests l'exercent via un micro-graph dédié (START ->
await_variant_candidate_resolution_node -> END), avec un vrai checkpointer
Postgres — exactement l'idiome déjà utilisé pour les autres nœuds
interrupt() de ce projet (cf. test_pipeline_graph_exercise_setup.py).

Câblage Priorité 2 — sa SORTIE est désormais câblée (routing.py::
VARIANT_CANDIDATE_RESOLUTION_ROUTING_TABLE) vers comparative_evaluation_node.
Le 3e test (test_resumption_through_full_graph_reaches_comparative_evaluation)
le prouve à travers le graph COMPLET (compile_pipeline_graph), pas le
micro-graph ci-dessus, en amorçant le checkpoint via aupdate_state(as_node=
...) — seule façon honnête d'atteindre ce nœud sans inventer un appelant
2.2 qui n'existe pas encore.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.graph.checkpointer import get_checkpointer, setup_checkpointer_tables
from app.graph.nodes.await_variant_candidate_resolution_node import (
    await_variant_candidate_resolution_node,
)
from app.graph.state import PipelineState


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


def _make_state(submission_id: str) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=submission_id,
        flow_type="student_evaluation",
        trace_id=submission_id,
        submission_id=submission_id,
        module_id=str(uuid.uuid4()),
        raw_file_path="submissions/copy.pdf",
        mime_type="application/pdf",
        student_candidate_method={
            "description": "Résolution par substitution directe.",
            "steps": [{"order": 1, "step_type": "computation"}],
            "concept_tags": ["substitution"],
        },
        status="RUNNING",
        pending_action=None,
        paused_at_node=None,
        created_at=now,
        updated_at=now,
    )


def _build_single_node_graph():
    graph = StateGraph(PipelineState)
    graph.add_node("await_variant_candidate_resolution_node", await_variant_candidate_resolution_node)
    graph.add_edge(START, "await_variant_candidate_resolution_node")
    graph.add_edge("await_variant_candidate_resolution_node", END)
    return graph


@pytest.mark.anyio
async def test_pauses_with_variant_candidate_review_reason():
    await setup_checkpointer_tables()
    submission_id = str(uuid.uuid4())

    async with get_checkpointer() as checkpointer:
        compiled = _build_single_node_graph().compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": submission_id}}
        result = await compiled.ainvoke(_make_state(submission_id), config=config)

        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        assert payload["reason"] == "variant_candidate_review"
        assert payload["submission_id"] == submission_id
        assert payload["student_candidate_method"]["description"] == "Résolution par substitution directe."


@pytest.mark.anyio
async def test_resumes_and_clears_pause_state():
    await setup_checkpointer_tables()
    submission_id = str(uuid.uuid4())

    async with get_checkpointer() as checkpointer:
        compiled = _build_single_node_graph().compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": submission_id}}

        await compiled.ainvoke(_make_state(submission_id), config=config)
        assert (await compiled.aget_state(config)).next  # toujours en pause

        result = await compiled.ainvoke(Command(resume="accepted"), config=config)

        assert "__interrupt__" not in result
        state_snapshot = await compiled.aget_state(config)
        assert not state_snapshot.next  # run terminé, plus de pause
        assert result["status"] == "RUNNING"
        # Câblage Priorité 2 : paused_at_node est désormais POSÉ (pas
        # remis à None) à la reprise — lu juste après par route_after_
        # variant_candidate_resolution dans le graph complet (cf. docstring
        # module ci-dessus). Ce micro-graph n'a pas cette edge (END direct),
        # donc la valeur posée reste visible telle quelle ici.
        assert result["paused_at_node"] == "await_variant_candidate_resolution_node"
        assert result["student_candidate_method"] is None


async def _seed_variant_candidate_scenario(db_session):
    """
    Seed minimal pour exercer comparative_evaluation_node en aval de la
    reprise (une Question/Bareme/SolutionVariant de référence/
    ExtractionCorrection) — mêmes modèles que test_pipeline_graph_
    student_evaluation.py, dupliqués ici plutôt qu'importés : ce fichier
    teste un nœud différent en isolation de graph, garder sa propre fixture
    plutôt que coupler les deux fichiers de test.
    """
    from decimal import Decimal

    from app.agents.Extraction_Verification_Agent import CorrectionMode
    from app.domain.models.academic.group import Group
    from app.domain.models.academic.module import Module
    from app.domain.models.academic.program import Program
    from app.domain.models.assessment.bareme import Bareme, BaremeValidationStatus
    from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
    from app.domain.models.assessment.extraction_correction import (
        ExtractionContentType,
        ExtractionCorrection,
        ExtractionEvidenceLevel,
    )
    from app.domain.models.assessment.question import Question
    from app.domain.models.assessment.solution_variant import (
        SolutionVariant,
        VariantDifficulty,
        VariantSource,
    )
    from app.domain.models.assessment.submission import Submission, SubmissionStatus
    from app.domain.repositories.user_repository import SQLAlchemyUserRepository

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
        first_name="Prof", last_name="Graph", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Student",
        student_number=f"STU_{uuid.uuid4()}"[:20], group_id=group.id,
        enrollment_year=2024, level="L3",
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice variant candidate", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.PENDING_OCR, document_path="submissions/doc.pdf",
        document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    question = Question(
        exercise_id=exercise.id, order=1, statement="Résoudre l'équation.",
        covered_subquestions=["1.1"],
    )
    db_session.add(question)
    await db_session.flush()

    bareme = Bareme(
        question_id=question.id, points=Decimal("4.00"),
        criteria=[{
            "id": "crit-1", "label": "exactitude", "points": 4.0,
            "correction_mode": CorrectionMode.CRITERIA_BASED.value,
            "verifiable_conditions": ["Résout correctement"],
            "disqualifying": False, "test_cases": [], "reference_code": None,
            "expected_complexity": None,
        }],
        validation_status=BaremeValidationStatus.CONFIRMED,
    )
    db_session.add(bareme)

    reference_variant = SolutionVariant(
        question_id=question.id, is_reference=True, content="x = 3.",
        version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE,
    )
    db_session.add(reference_variant)

    correction = ExtractionCorrection(
        submission_id=submission.id, question_id=question.id,
        image_crop_path="crops/block1.png", page_number=1,
        content_type=ExtractionContentType.TEXT,
        prediction_ocr="x = 3 par substitution directe.",
        confidence_score=Decimal("0.9"), bounding_box={"x": 0, "y": 0, "w": 10, "h": 10},
        evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
    )
    db_session.add(correction)
    await db_session.flush()

    return exercise, submission, question


@pytest.mark.anyio
async def test_resumption_through_full_graph_reaches_comparative_evaluation(db_session):
    """
    Câblage Priorité 2 — preuve à travers le graph COMPLET (pas le
    micro-graph à un seul nœud des 2 tests ci-dessus) : une reprise
    checkpointée à await_variant_candidate_resolution_node doit router,
    via route_after_variant_candidate_resolution (routing.py) et l'edge
    conditionnelle réelle de pipeline_graph.py, vers comparative_evaluation_
    node, puis jusqu'à evaluation_node -> une note persistée.

    Aucun appelant réel du déclencheur 2.2 n'existe encore (entrée du nœud
    toujours sans edge, cf. son docstring) : le checkpoint est donc amorcé
    directement via aupdate_state(as_node=...), qui place le graph "comme si"
    await_variant_candidate_resolution_node venait de produire cet état —
    exactement ce que ferait un vrai run s'il existait, sans en inventer un.
    """
    from contextlib import ExitStack
    from decimal import Decimal
    from unittest.mock import AsyncMock, MagicMock, patch

    from sqlalchemy import select

    from app.agents.Comparative_Evaluation_Agent import (
        ComparativeEvaluationAgent,
        ComparativeEvaluationReport,
        CriterionEvaluationResult,
        SubquestionJudgment,
    )
    from app.agents.Extraction_Verification_Agent import CorrectionMode
    from app.domain.models.assessment.evaluation import Evaluation
    from app.graph.pipeline_graph import compile_pipeline_graph

    exercise, submission, question = await _seed_variant_candidate_scenario(db_session)
    await setup_checkpointer_tables()

    submission_id = str(submission.id)
    config = {"configurable": {"thread_id": submission_id}}
    now = datetime.now(timezone.utc)

    full_state = {
        "thread_id": submission_id,
        "flow_type": "student_evaluation",
        "trace_id": submission_id,
        "exercise_id": str(exercise.id),
        "submission_id": submission_id,
        "module_id": str(exercise.module_id),
        "student_id": str(submission.student_id),
        "raw_file_path": submission.document_path,
        "mime_type": "application/pdf",
        "status": "RUNNING",
        "pending_action": None,
        "paused_at_node": "await_variant_candidate_resolution_node",
        "student_candidate_method": None,
        "created_at": now,
        "updated_at": now,
    }

    comparative_report = ComparativeEvaluationReport(
        question_id=question.id,
        criterion_results=[
            CriterionEvaluationResult(
                criterion_id="crit-1", correction_mode=CorrectionMode.CRITERIA_BASED,
                is_satisfied=True, score_ratio=1.0, justification="Résolution correcte.",
                confidence_score=0.9,
            )
        ],
        overall_confidence=0.9,
        subquestion_judgments=[
            SubquestionJudgment(
                subquestion_id="1.1", addressed=True, is_correct=True,
                evidence_reference="x = 3", source="new_llm_judgment",
                completion_ratio=Decimal("1.0"),
            ),
        ],
    )

    stack = ExitStack()
    for target in (
        "app.graph.nodes.comparative_evaluation_node.get_db_context",
        "app.graph.nodes.evaluation_node.get_db_context",
        "app.graph.nodes.competency_assessment_node.get_db_context",
        "app.graph.nodes.recommendation_node.get_db_context",
        # feedback_node lit réellement la Submission (précondition PENDING_
        # ARBITRATION, cf. FeedbackReportService) — contrairement à
        # recommendation_node ci-dessus (jamais eu besoin de la relire),
        # une session non patchée ne verrait pas la ligne encore non
        # committée par db_session -> SubmissionNotFoundError, cf. incident
        # constaté ici (chantier Feedback_Agent).
        "app.graph.nodes.feedback_node.get_db_context",
    ):
        stack.enter_context(patch(target, lambda: _reuse_session(db_session)))
    stack.enter_context(patch("app.observability.langfuse.langfuse", MagicMock()))
    stack.enter_context(
        patch.object(ComparativeEvaluationAgent, "execute", AsyncMock(return_value=comparative_report))
    )
    # Le run atteint désormais feedback_node (chantier Feedback_Agent, câblé
    # après recommendation_node) — sans ce mock, le SEUL appel LLM du
    # pipeline tenterait un vrai appel réseau ici, hors du périmètre de ce
    # test (câblage Priorité 2, pas Feedback_Agent).
    feedback_response = MagicMock()
    feedback_response.content = "Continue ainsi, comment pourrais-tu vérifier ton résultat ?"
    feedback_spec = MagicMock(provider="groq", model_name="llama-3.3-70b-versatile")
    stack.enter_context(
        patch(
            "app.agents.Feedback_Agent.invoke_llm_with_fallback",
            AsyncMock(return_value=(feedback_response, feedback_spec, False, {})),
        )
    )

    with stack:
        async with get_checkpointer() as checkpointer:
            compiled = compile_pipeline_graph(checkpointer)
            await compiled.aupdate_state(
                config, full_state, as_node="await_variant_candidate_resolution_node",
            )
            result = await compiled.ainvoke(None, config=config)

    assert "__interrupt__" not in result

    stmt = select(Evaluation).where(
        Evaluation.submission_id == submission.id, Evaluation.question_id == question.id,
    )
    evaluation = (await db_session.execute(stmt)).scalar_one()
    assert evaluation.score == Decimal("4.00")
