"""
Test d'intégration — pipeline_graph.py, branche exercise_setup, contre une
vraie DB (checkpointer Postgres réel inclus) et un vrai LangGraph. Seuls les
appels LLM/Azure sont mockés (OCR_Extraction_Agent.execute,
Document_Structuring_Agent.execute, invoke_llm_with_fallback pour
Extraction_Verification_Agent, storage_service.download) — même principe
que les tests d'intégration précédents (agent réel, seul le LLM est mocké).

Couvre :
  1. Run complet sans pause (structuration COMPLETE, aucune clarification
     BLOCKING) : le graph traverse entry -> structuring -> extraction_
     verification -> fin, tout est persisté (Bareme, SolutionVariant/
     ReasoningStep, Job).
  2. Pause sur structuration INCOMPLETE : le graph s'arrête à
     await_structuring_resolution_node via interrupt(), resumable.
  3. Pause sur clarification BLOCKING : le graph s'arrête à
     await_clarification_resolution_node via interrupt(), resumable.
  4. Retry après échec partiel : un deuxième ainvoke() sur le même thread_id
     après un échec ne duplique pas les TeacherCorrectionBlock déjà
     persistés (nuance de latence/régression discutée avant le câblage).
"""
import uuid
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest

from app.agents.document_structuring_exceptions import StructuringIncompleteError
from app.agents.Document_Structuring_Agent import DocumentStructuringAgent, StructuringReport
from app.agents.OCR_Extraction_Agent import OCRExtractionAgent
from app.agents.Reasoning_Graph_Agent import (
    ReasoningGraphAgent,
    ReasoningGraphReport,
    ReasoningStepGraphOutput,
)
from app.agents.Extraction_Verification_Agent import ClarificationRequest, ClarificationSeverity
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_step import ReasoningStepType
from app.domain.models.assessment.solution_variant import SolutionVariant
from app.domain.models.system_infrastructure.job import JobStatus
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.schemas.submission_schemas import RawExtractedBlock
from app.graph.checkpointer import get_checkpointer, setup_checkpointer_tables
from app.graph.pipeline_graph import compile_pipeline_graph
from app.graph.state import PipelineState
from langgraph.types import Command

import json as json_module


async def _seed_exercise(db_session) -> tuple[Exercise, uuid.UUID]:
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
        last_name="Graph",
        department="Maths",
        title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    exercise = Exercise(
        module_id=module.id,
        created_by_professor_id=professor.id,
        title="Exercice graph",
        status=ExerciseStatus.DRAFT,
    )
    db_session.add(exercise)
    await db_session.flush()

    return exercise, professor.id


def _make_valid_scan_bytes() -> bytes:
    """
    PNG net/contrasté réel (pas un placeholder b"fake-pdf-bytes") : depuis
    le câblage de scan_quality_control_node, storage_service.download()
    alimente un VRAI contrôle qualité déterministe (OpenCV, non mocké) avant
    OCR_Extraction_Agent — un placeholder échouerait ce contrôle. mime_type
    posé à "image/png" en conséquence (cf. _make_initial_state).
    """
    arr = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.putText(arr, "Enonce et correction", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.rectangle(arr, (10, 10), (390, 390), (0, 0, 0), 2)
    _, buffer = cv2.imencode(".png", arr)
    return buffer.tobytes()


def _make_raw_block() -> RawExtractedBlock:
    return RawExtractedBlock(
        image_crop_path="crops/block1.png",
        content_type="TEXT",
        prediction_ocr="Aire = L * l = 12 cm2. Note globale : 5 points.",
        confidence_score=Decimal("0.95"),
        bounding_box={"x": 0, "y": 0, "w": 10, "h": 10},
        page_number=1,
        block_order_index=0,
        evidence_level="label_explicite",
    )


def _make_initial_state(exercise: Exercise, professor_id: uuid.UUID) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(exercise.id),
        flow_type="exercise_setup",
        trace_id=str(exercise.id),
        exercise_id=str(exercise.id),
        module_id=str(exercise.module_id),
        professor_id=str(professor_id),
        raw_file_path="exercises/doc.pdf",
        mime_type="image/png",
        created_at=now,
        updated_at=now,
    )


def _decomposition_payload() -> dict:
    return {
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


def _make_graph_report(variant_id=None, blocking: bool = False) -> ReasoningGraphReport:
    """
    Construit un ReasoningGraphReport directement sans passer par le LLM ni
    _validate_variable_availability. Les étapes sont mathématiquement cohérentes
    (variables disponibles) pour ne pas déclencher la validation constraint-based.
    blocking=True ajoute une ClarificationRequest BLOCKING pour tester la pause HITL.
    """
    import uuid as _uuid
    vid = variant_id or _uuid.uuid4()
    clarifications = []
    if blocking:
        clarifications.append(
            ClarificationRequest(
                related_field="construction_confidence",
                agent_question="Faible confiance de structuration (0.40) — vérifier les dépendances.",
                proposed_answer=None,
                severity=ClarificationSeverity.BLOCKING,
            )
        )
    steps = [
        ReasoningStepGraphOutput(
            step_ref="s1", order=1, step_type=ReasoningStepType.GIVEN_DATA,
            description="Aire = L * l = 12 cm2",
            formula="Aire = L * l",
            source_span="Aire = L * l = 12 cm2",
            is_core_step=True,
        ),
        ReasoningStepGraphOutput(
            step_ref="s2", order=2, step_type=ReasoningStepType.CONCLUSION,
            description="Note globale : 5 points.",
            formula=None,
            source_span="Note globale : 5 points.",
            is_core_step=True,
            depends_on_refs=["s1"],
        ),
    ]
    return ReasoningGraphReport(
        variant_id=vid,
        steps=steps,
        construction_confidence=0.4 if blocking else 0.95,
        source_coverage_ratio=0.96,
        clarifications=clarifications,
        is_valid_dag=True,
        model_version="groq:llama-3.3-70b",
    )



def _bareme_payload_detailed() -> dict:
    return {
        "case": "DETAILED",
        "total_points": 5.0,
        "criteria": [
            {
                "label": "exactitude", "points": 5.0, "correction_mode": "solution_worked",
                "verifiable_conditions": [], "disqualifying": False,
                "test_cases": [], "reference_code": None, "expected_complexity": None,
            },
        ],
        "justification": "Rattachement explicite.",
    }


def _mock_llm_response(payload: dict):
    fake_response = MagicMock()
    fake_response.content = json_module.dumps(payload, ensure_ascii=False)
    fake_spec = MagicMock()
    fake_spec.provider = "groq"
    fake_spec.model_name = "llama-3.3-70b"
    return (fake_response, fake_spec, False, {"total_tokens": 100})


@asynccontextmanager
async def _reuse_session(db_session):
    """
    Remplace get_db_context() dans les nœuds pour la durée du test : chaque
    nœud ouvre normalement SA PROPRE session (get_db_context réel, commit/
    rollback/close à chaque appel) — en test, la donnée seedée via db_session
    n'est que flush (pas commit, isolation entre tests oblige), donc invisible
    d'une session distincte. On réutilise ici la session du test partout,
    sans la committer/fermer (le fixture db_session en reste propriétaire),
    même principe que tests/integration/conftest.py pour get_db (FastAPI).
    """
    yield db_session


def _patch_node_db_sessions(db_session) -> ExitStack:
    """
    get_db_context est importé (donc lié) au niveau module dans chaque nœud —
    patcher app.core.database.get_db_context ne suffit pas, il faut patcher
    la référence locale de CHAQUE module qui l'a importée.
    """
    stack = ExitStack()
    for target in (
        "app.graph.nodes.entry_router_node.get_db_context",
        "app.graph.nodes.document_structuring_node.get_db_context",
        "app.graph.nodes.extraction_verification_node.get_db_context",
        "app.graph.nodes.reasoning_graph_node.get_db_context",
        "app.graph.nodes.solution_variant_generation_node.get_db_context",
    ):
        stack.enter_context(patch(target, lambda: _reuse_session(db_session)))
    return stack


@pytest.mark.anyio
async def test_full_run_no_pause_persists_everything(db_session):
    from sqlalchemy import select
    from app.domain.models.assessment.reasoning_step import ReasoningStep

    exercise, professor_id = await _seed_exercise(db_session)
    await setup_checkpointer_tables()

    structuring_report = StructuringReport(
        exercise_id=exercise.id,
        status="COMPLETE",
        sections_created=[{"order": 1, "title": "Partie 1"}],
        questions_created=[{"order": 1, "statement": "Calculer l'aire.", "section_order": 1}],
        correction_blocks_created=[
            {
                "content_type": "TEXT",
                "evidence_level": "label_explicite",
                "justification": "Bloc de correction rattaché.",
                "section_order": 1,
                "question_order": 1,
                "raw_text": "Aire = L * l = 12 cm2. Note globale : 5 points.",
            }
        ],
        unresolved_block_count=0,
        questions_without_correction_count=0,
        label_conflict_count=0,
        empty_section_count=0,
        block_classifications=[
            {"justification": "Bloc CORRECTION.", "model_used": "groq:llama-3.3-70b", "confidence": 0.9},
        ],
    )

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.exercise_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch.object(DocumentStructuringAgent, "execute", AsyncMock(return_value=structuring_report)),
        patch(
            "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
            side_effect=[
                _mock_llm_response(_decomposition_payload()),
                _mock_llm_response(_bareme_payload_detailed()),
            ],
        ),
        patch.object(ReasoningGraphAgent, "execute", AsyncMock(return_value=_make_graph_report())),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, professor_id)
            config = {"configurable": {"thread_id": str(exercise.id)}}
            result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" not in result
    assert result["status"] == "RUNNING"
    assert result["structuring_status"] == "COMPLETE"
    assert result["blocking_clarification_count"] == 0

    # Vérification que le graphe de raisonnement de référence a été persisté en base.
    # ExtractionVerificationService crée les steps v1 (depuis _decomposition_payload, 3 steps).
    # ReasoningGraphService les supersède avec les steps v2 du rapport mock (2 steps).
    # La requête ramène tous les steps (v1 supersédés + v2 actifs = 5 total) ;
    # les steps actifs (superseded_by is None) correspondent aux 2 steps du mock
    # (s1 et s2) + s3 de v1 non supersédé (notre mock n'a que 2 steps, pas 3).
    # On vérifie que ReasoningGraphService a bien tourné en inspectant la version max.
    stmt = (
        select(ReasoningStep)
        .join(SolutionVariant, SolutionVariant.id == ReasoningStep.variant_id)
        .join(Question, Question.id == SolutionVariant.question_id)
        .where(Question.exercise_id == exercise.id)
    )
    steps = (await db_session.execute(stmt)).scalars().all()
    # Au moins les 2 steps du rapport mock ont été créés en version 2.
    steps_v2 = [s for s in steps if s.version == 2]
    assert len(steps_v2) == 2, f"Attendu 2 steps v2, obtenu {len(steps_v2)} (total: {len(steps)})"

    job_repo = SQLAlchemyJobRepository(db_session)
    job = await job_repo.get_active_job_for_thread(exercise.id)
    assert job is not None
    assert job.status == JobStatus.RUNNING
    assert job.current_node == "entry_router_node"


@pytest.mark.anyio
async def test_incomplete_structuring_pauses_resumably(db_session):
    exercise, professor_id = await _seed_exercise(db_session)
    await setup_checkpointer_tables()

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.exercise_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch.object(
            DocumentStructuringAgent,
            "execute",
            AsyncMock(side_effect=StructuringIncompleteError(
                exercise_id=exercise.id, unresolved_blocks=1,
                questions_without_correction=0, label_conflicts=0, empty_sections=0,
            )),
        ),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, professor_id)
            config = {"configurable": {"thread_id": str(exercise.id)}}
            result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" in result
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload["reason"] == "structuring_incomplete"

    # Toujours resumable : le thread n'a jamais atteint __end__.
    async with get_checkpointer() as checkpointer:
        graph = compile_pipeline_graph(checkpointer)
        state_snapshot = await graph.aget_state({"configurable": {"thread_id": str(exercise.id)}})
        assert state_snapshot.next == ("await_structuring_resolution_node",)


@pytest.mark.anyio
async def test_blocking_clarification_pauses_resumably(db_session):
    exercise, professor_id = await _seed_exercise(db_session)
    await setup_checkpointer_tables()

    structuring_report = StructuringReport(
        exercise_id=exercise.id,
        status="COMPLETE",
        sections_created=[{"order": 1, "title": "Partie 1"}],
        questions_created=[{"order": 1, "statement": "Calculer l'aire.", "section_order": 1}],
        correction_blocks_created=[
            {
                "content_type": "TEXT",
                "evidence_level": "label_explicite",
                "justification": "Bloc de correction rattaché.",
                "section_order": 1,
                "question_order": 1,
                "raw_text": "Aire = L * l = 12 cm2. Note globale : 5 points.",
            }
        ],
        unresolved_block_count=0,
        questions_without_correction_count=0,
        label_conflict_count=0,
        empty_section_count=0,
        block_classifications=[
            {"justification": "Bloc CORRECTION.", "model_used": "groq:llama-3.3-70b", "confidence": 0.9},
        ],
    )
    bareme_global_proposed = {
        "case": "GLOBAL_PROPOSED",
        "total_points": 5.0,
        "criteria": [
            {
                "label": "exactitude", "points": 5.0, "correction_mode": "solution_worked",
                "verifiable_conditions": [], "disqualifying": False,
                "test_cases": [], "reference_code": None, "expected_complexity": None,
            },
        ],
        "justification": "Proposition sans détail par critère.",
    }

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.exercise_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch.object(DocumentStructuringAgent, "execute", AsyncMock(return_value=structuring_report)),
        patch(
            "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
            side_effect=[
                _mock_llm_response(_decomposition_payload()),
                _mock_llm_response(bareme_global_proposed),
            ],
        ),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, professor_id)
            config = {"configurable": {"thread_id": str(exercise.id)}}
            result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" in result
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload["reason"] == "clarification_review"
    assert interrupt_payload["blocking_clarification_count"] >= 1


@pytest.mark.anyio
async def test_retry_after_extraction_verification_failure_does_not_replay_structuring(db_session):
    """
    Vérifie la nuance discutée avant le câblage (aucune régression latence/
    fonctionnelle) : un échec APRÈS document_structuring_node (déjà
    checkpointé, complet) suivi d'un retry sur le même thread_id reprend à
    extraction_verification_node, sans rejouer OCR+structuration — donc sans
    dupliquer Question/TeacherCorrectionBlock.

    Nuance honnête à noter : ce bénéfice tient à la granularité choisie (2
    nœuds distincts entre structuring et extraction_verification), pas à
    l'intérieur de document_structuring_node lui-même — un échec DURANT ce
    nœud (entre OCR et structuration) rejouerait toujours les deux depuis le
    début au prochain essai, exactement comme avant le câblage (nœud combiné
    volontairement, cf. pipeline_graph.py).
    """
    from sqlalchemy import select
    from app.domain.models.assessment.question import Question

    exercise, professor_id = await _seed_exercise(db_session)
    await setup_checkpointer_tables()

    structuring_report = StructuringReport(
        exercise_id=exercise.id,
        status="COMPLETE",
        sections_created=[{"order": 1, "title": "Partie 1"}],
        questions_created=[{"order": 1, "statement": "Calculer l'aire.", "section_order": 1}],
        correction_blocks_created=[
            {
                "content_type": "TEXT",
                "evidence_level": "label_explicite",
                "justification": "Bloc de correction rattaché.",
                "section_order": 1,
                "question_order": 1,
                "raw_text": "Aire = L * l = 12 cm2. Note globale : 5 points.",
            }
        ],
        unresolved_block_count=0,
        questions_without_correction_count=0,
        label_conflict_count=0,
        empty_section_count=0,
        block_classifications=[
            {"justification": "Bloc CORRECTION.", "model_used": "groq:llama-3.3-70b", "confidence": 0.9},
        ],
    )
    config = {"configurable": {"thread_id": str(exercise.id)}}

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.exercise_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch.object(DocumentStructuringAgent, "execute", AsyncMock(return_value=structuring_report)),
        patch(
            "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
            AsyncMock(side_effect=RuntimeError("panne fournisseur LLM transitoire")),
        ),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, professor_id)
            with pytest.raises(RuntimeError, match="panne fournisseur"):
                await graph.ainvoke(initial_state, config=config)

    questions_after_failure = (
        await db_session.execute(select(Question).where(Question.exercise_id == exercise.id))
    ).scalars().all()
    assert len(questions_after_failure) == 1  # structuring bien persistée, une seule fois

    # Retry : même thread_id, input=None (reprend depuis le dernier checkpoint,
    # pas depuis l'état initial) — simule le comportement autoretry_for de Celery.
    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
            side_effect=[
                _mock_llm_response(_decomposition_payload()),
                _mock_llm_response(_bareme_payload_detailed()),
            ],
        ),
        patch.object(ReasoningGraphAgent, "execute", AsyncMock(return_value=_make_graph_report())),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            result = await graph.ainvoke(None, config=config)

    assert "__interrupt__" not in result
    assert result["structuring_status"] == "COMPLETE"

    questions_after_retry = (
        await db_session.execute(select(Question).where(Question.exercise_id == exercise.id))
    ).scalars().all()
    assert len(questions_after_retry) == 1  # toujours une seule Question : OCR+structuration pas rejouées


@pytest.mark.anyio
async def test_reasoning_graph_blocking_clarification_pauses_resumably(db_session):
    exercise, professor_id = await _seed_exercise(db_session)
    await setup_checkpointer_tables()

    structuring_report = StructuringReport(
        exercise_id=exercise.id,
        status="COMPLETE",
        sections_created=[{"order": 1, "title": "Partie 1"}],
        questions_created=[{"order": 1, "statement": "Calculer l'aire.", "section_order": 1}],
        correction_blocks_created=[
            {
                "content_type": "TEXT",
                "evidence_level": "label_explicite",
                "justification": "Bloc de correction rattaché.",
                "section_order": 1,
                "question_order": 1,
                "raw_text": "Aire = L * l = 12 cm2. Note globale : 5 points.",
            }
        ],
        unresolved_block_count=0,
        questions_without_correction_count=0,
        label_conflict_count=0,
        empty_section_count=0,
        block_classifications=[
            {"justification": "Bloc CORRECTION.", "model_used": "groq:llama-3.3-70b", "confidence": 0.9},
        ],
    )

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.exercise_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch.object(DocumentStructuringAgent, "execute", AsyncMock(return_value=structuring_report)),
        patch(
            "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
            side_effect=[
                _mock_llm_response(_decomposition_payload()),
                _mock_llm_response(_bareme_payload_detailed()),
            ],
        ),
        patch.object(ReasoningGraphAgent, "execute", AsyncMock(return_value=_make_graph_report(blocking=True))),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, professor_id)
            config = {"configurable": {"thread_id": str(exercise.id)}}
            result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" in result
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload["reason"] == "clarification_review"

    async with get_checkpointer() as checkpointer:
        graph = compile_pipeline_graph(checkpointer)
        state_snapshot = await graph.aget_state({"configurable": {"thread_id": str(exercise.id)}})
        assert state_snapshot.next == ("await_clarification_resolution_node",)


@pytest.mark.anyio
async def test_reasoning_graph_node_skipped_if_extraction_clarification_blocking(db_session):
    from sqlalchemy import select
    from app.domain.models.assessment.reasoning_step import ReasoningStep

    exercise, professor_id = await _seed_exercise(db_session)
    await setup_checkpointer_tables()

    structuring_report = StructuringReport(
        exercise_id=exercise.id,
        status="COMPLETE",
        sections_created=[{"order": 1, "title": "Partie 1"}],
        questions_created=[{"order": 1, "statement": "Calculer l'aire.", "section_order": 1}],
        correction_blocks_created=[
            {
                "content_type": "TEXT",
                "evidence_level": "label_explicite",
                "justification": "Bloc de correction rattaché.",
                "section_order": 1,
                "question_order": 1,
                "raw_text": "Aire = L * l = 12 cm2. Note globale : 5 points.",
            }
        ],
        unresolved_block_count=0,
        questions_without_correction_count=0,
        label_conflict_count=0,
        empty_section_count=0,
        block_classifications=[
            {"justification": "Bloc CORRECTION.", "model_used": "groq:llama-3.3-70b", "confidence": 0.9},
        ],
    )
    bareme_global_proposed = {
        "case": "GLOBAL_PROPOSED",
        "total_points": 5.0,
        "criteria": [
            {
                "label": "exactitude", "points": 5.0, "correction_mode": "solution_worked",
                "verifiable_conditions": [], "disqualifying": False,
                "test_cases": [], "reference_code": None, "expected_complexity": None,
            },
        ],
        "justification": "Proposition sans détail par critère.",
    }

    reasoning_agent_mock = AsyncMock()

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.exercise_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch.object(DocumentStructuringAgent, "execute", AsyncMock(return_value=structuring_report)),
        patch(
            "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
            side_effect=[
                _mock_llm_response(_decomposition_payload()),
                _mock_llm_response(bareme_global_proposed),
            ],
        ),
        patch.object(ReasoningGraphAgent, "execute", reasoning_agent_mock),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, professor_id)
            config = {"configurable": {"thread_id": str(exercise.id)}}
            result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" in result
    # Reasoning_Graph_Agent ne doit JAMAIS avoir été appelé
    reasoning_agent_mock.assert_not_called()

    # L'ExtractionVerificationService crée toujours les steps v1 (3 steps via _decomposition_payload).
    # Le reasoning_graph_node a été sauté (pause avant son exécution) → aucun step v2.
    # Signal que reasoning_graph_node est bien sauté : tous les steps sont de version 1.
    stmt = (
        select(ReasoningStep)
        .join(SolutionVariant, SolutionVariant.id == ReasoningStep.variant_id)
        .join(Question, Question.id == SolutionVariant.question_id)
        .where(Question.exercise_id == exercise.id)
    )
    steps = (await db_session.execute(stmt)).scalars().all()
    # Extraction verification crée 3 steps v1.
    assert len(steps) == 3, f"Attendu 3 steps v1 (extraction seulement), obtenu {len(steps)}"
    # reasoning_graph_node sauté → aucun step de version supérieure à 1.
    assert all(s.version == 1 for s in steps), "Des steps v2+ existent — reasoning_graph_node n'a pas été sauté"


@pytest.mark.anyio
async def test_routing_after_resume_respects_paused_at_node(db_session):
    from sqlalchemy import select
    from app.domain.models.assessment.reasoning_step import ReasoningStep

    await setup_checkpointer_tables()

    def _make_structuring_report(exercise_id):
        return StructuringReport(
            exercise_id=exercise_id,
            status="COMPLETE",
            sections_created=[{"order": 1, "title": "Partie 1"}],
            questions_created=[{"order": 1, "statement": "Calculer l'aire.", "section_order": 1}],
            correction_blocks_created=[
                {
                    "content_type": "TEXT",
                    "evidence_level": "label_explicite",
                    "justification": "Bloc de correction rattaché.",
                    "section_order": 1,
                    "question_order": 1,
                    "raw_text": "Aire = L * l = 12 cm2. Note globale : 5 points.",
                }
            ],
            unresolved_block_count=0,
            questions_without_correction_count=0,
            label_conflict_count=0,
            empty_section_count=0,
            block_classifications=[
                {"justification": "Bloc CORRECTION.", "model_used": "groq:llama-3.3-70b", "confidence": 0.9},
            ],
        )

    bareme_global_proposed = {
        "case": "GLOBAL_PROPOSED",
        "total_points": 5.0,
        "criteria": [
            {
                "label": "exactitude", "points": 5.0, "correction_mode": "solution_worked",
                "verifiable_conditions": [], "disqualifying": False,
                "test_cases": [], "reference_code": None, "expected_complexity": None,
            },
        ],
        "justification": "Proposition sans détail par critère.",
    }

    # --- CAS 1 : extraction_verification_node pause -> resume -> reasoning_graph_node ---
    # Chaque cas utilise son propre exercise pour éviter toute interférence de données.
    exercise1, professor_id1 = await _seed_exercise(db_session)
    structuring_report1 = _make_structuring_report(exercise1.id)

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.exercise_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch.object(DocumentStructuringAgent, "execute", AsyncMock(return_value=structuring_report1)),
        patch(
            "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
            side_effect=[
                _mock_llm_response(_decomposition_payload()),
                _mock_llm_response(bareme_global_proposed),  # Provoque une pause extraction
            ],
        ),
        patch.object(ReasoningGraphAgent, "execute", AsyncMock(return_value=_make_graph_report())),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise1, professor_id1)
            config1 = {"configurable": {"thread_id": str(exercise1.id)}}

            # Premier ainvoke : pause au niveau de extraction_verification_node
            result = await graph.ainvoke(initial_state, config=config1)
            assert "__interrupt__" in result
            assert result["paused_at_node"] == "extraction_verification_node"

            # Reprise via Command(resume=True) : obligatoire après interrupt().
            # ainvoke(None) rejouerait le nœud depuis le début et retomberait sur interrupt().
            result = await graph.ainvoke(Command(resume=True), config=config1)
            assert "__interrupt__" not in result
            assert result["status"] == "RUNNING"
            assert result["paused_at_node"] is None

    # Vérification de la persistance : les steps v2 produits par reasoning_graph_node après la reprise
    stmt = (
        select(ReasoningStep)
        .join(SolutionVariant, SolutionVariant.id == ReasoningStep.variant_id)
        .join(Question, Question.id == SolutionVariant.question_id)
        .where(Question.exercise_id == exercise1.id)
    )
    steps1 = (await db_session.execute(stmt)).scalars().all()
    steps1_v2 = [s for s in steps1 if s.version == 2]
    assert len(steps1_v2) == 2, f"CAS 1 : attendu 2 steps v2, obtenu {len(steps1_v2)}"

    # --- CAS 2 : reasoning_graph_node pause -> resume -> reasoning_graph_node ---
    exercise2, professor_id2 = await _seed_exercise(db_session)
    structuring_report2 = _make_structuring_report(exercise2.id)

    agent_mock = AsyncMock(side_effect=[
        _make_graph_report(blocking=True),   # Premier run : pause
        _make_graph_report(blocking=False),  # Second run (après reprise) : succès
    ])

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.exercise_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch.object(DocumentStructuringAgent, "execute", AsyncMock(return_value=structuring_report2)),
        patch(
            "app.agents.Extraction_Verification_Agent.invoke_llm_with_fallback",
            side_effect=[
                _mock_llm_response(_decomposition_payload()),
                _mock_llm_response(_bareme_payload_detailed()),  # Pas de pause extraction
            ],
        ),
        patch.object(ReasoningGraphAgent, "execute", agent_mock),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise2, professor_id2)
            config2 = {"configurable": {"thread_id": str(exercise2.id)}}

            # Premier ainvoke : pause au niveau de reasoning_graph_node
            result = await graph.ainvoke(initial_state, config=config2)
            assert "__interrupt__" in result
            assert result["paused_at_node"] == "reasoning_graph_node"

            # Reprise via Command(resume=True)
            result = await graph.ainvoke(Command(resume=True), config=config2)
            assert "__interrupt__" not in result
            assert result["paused_at_node"] is None

    # Vérification : steps v2 créés après la reprise
    stmt = (
        select(ReasoningStep)
        .join(SolutionVariant, SolutionVariant.id == ReasoningStep.variant_id)
        .join(Question, Question.id == SolutionVariant.question_id)
        .where(Question.exercise_id == exercise2.id)
    )
    steps2 = (await db_session.execute(stmt)).scalars().all()
    steps2_v2 = [s for s in steps2 if s.version == 2]
    assert len(steps2_v2) == 2, f"CAS 2 : attendu 2 steps v2, obtenu {len(steps2_v2)}"

    # --- CAS 3 : paused_at_node inconnu -> ValueError strict ---
    # La table de routage est pure (pas d'effet de bord), on la teste directement.
    # LangGraph appelle le routeur dès aupdate_state, donc pas besoin de passer par le graph complet.
    from app.graph.routing import route_after_clarification_resolution
    from app.graph.state import PipelineState
    from datetime import datetime, timezone

    exercise3, professor_id3 = await _seed_exercise(db_session)
    bad_state = _make_initial_state(exercise3, professor_id3)
    bad_state.paused_at_node = "unknown_node"

    with pytest.raises(ValueError, match="Nœud de pause 'unknown_node' inconnu"):
        route_after_clarification_resolution(bad_state)

    # Vérification du cas None (paused_at_node absent)
    null_state = _make_initial_state(exercise3, professor_id3)
    null_state.paused_at_node = None

    with pytest.raises(ValueError, match="paused_at_node est vide ou None"):
        route_after_clarification_resolution(null_state)


@pytest.mark.anyio
async def test_targeted_resume_skips_already_succeeded_variants(db_session):
    from app.domain.models.assessment.question import Question
    from app.domain.models.assessment.solution_variant import SolutionVariant, VariantSource, VariantDifficulty
    from app.graph.nodes.reasoning_graph_node import reasoning_graph_node
    from app.domain.schemas.reasoning_graph_schemas import ReasoningGraphRead
    from app.services.reasoning_graph_service import ReasoningGraphService

    exercise, professor_id = await _seed_exercise(db_session)
    q1 = Question(exercise_id=exercise.id, order=1, statement="Q1 statement")
    q2 = Question(exercise_id=exercise.id, order=2, statement="Q2 statement")
    db_session.add_all([q1, q2])
    await db_session.flush()

    v1 = SolutionVariant(question_id=q1.id, is_reference=True, content="Sol Q1", version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE)
    v2 = SolutionVariant(question_id=q2.id, is_reference=True, content="Sol Q2", version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE)
    db_session.add_all([v1, v2])
    await db_session.flush()

    state = _make_initial_state(exercise, professor_id)

    # Premier passage : V1 réussit (blocking=0), V2 échoue (blocking=1)
    calls = []
    async def mock_build_graph(variant_id, trace_id=None):
        calls.append(variant_id)
        if variant_id == v1.id:
            return ReasoningGraphRead(
                variant_id=variant_id, construction_confidence=0.9,
                source_coverage_ratio=1.0, is_valid_dag=True, step_count=2,
                blocking_clarification_count=0, model_version="mock"
            )
        else:
            return ReasoningGraphRead(
                variant_id=variant_id, construction_confidence=0.5,
                source_coverage_ratio=0.5, is_valid_dag=False, step_count=1,
                blocking_clarification_count=1, model_version="mock"
            )

    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_build_graph),
    ):
        state = await reasoning_graph_node(state)

    assert state.status == "PAUSED"
    assert state.paused_at_node == "reasoning_graph_node"
    assert state.pending_reasoning_graph_variant_ids == [str(v2.id)]
    assert calls == [v1.id, v2.id]  # Les 2 variantes traitées au 1er passage

    # Reprise : V2 réussit
    calls.clear()
    async def mock_build_graph_resume(variant_id, trace_id=None):
        calls.append(variant_id)
        return ReasoningGraphRead(
            variant_id=variant_id, construction_confidence=0.95,
            source_coverage_ratio=1.0, is_valid_dag=True, step_count=2,
            blocking_clarification_count=0, model_version="mock"
        )

    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_build_graph_resume),
    ):
        state = await reasoning_graph_node(state)

    assert state.status == "RUNNING"
    assert state.paused_at_node is None
    assert state.pending_reasoning_graph_variant_ids == []
    # VERIFICATION PRINCIPALE : V1 (qui avait déjà réussi) N'A PAS ÉTÉ RAPPELÉE !
    assert calls == [v2.id]


@pytest.mark.anyio
async def test_no_new_version_created_for_succeeded_variants_on_resume(db_session):
    from sqlalchemy import select
    from app.domain.models.assessment.question import Question
    from app.domain.models.assessment.solution_variant import SolutionVariant, VariantSource, VariantDifficulty
    from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepType
    from app.graph.nodes.reasoning_graph_node import reasoning_graph_node
    from app.domain.schemas.reasoning_graph_schemas import ReasoningGraphRead
    from app.services.reasoning_graph_service import ReasoningGraphService

    exercise, professor_id = await _seed_exercise(db_session)
    q1 = Question(exercise_id=exercise.id, order=1, statement="Q1")
    q2 = Question(exercise_id=exercise.id, order=2, statement="Q2")
    db_session.add_all([q1, q2])
    await db_session.flush()

    v1 = SolutionVariant(question_id=q1.id, is_reference=True, content="Sol Q1", version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE)
    v2 = SolutionVariant(question_id=q2.id, is_reference=True, content="Sol Q2", version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE)
    db_session.add_all([v1, v2])
    await db_session.flush()

    # On crée manuellement des steps v1 pour V1
    step_v1 = ReasoningStep(
        variant_id=v1.id, order=1, step_type=ReasoningStepType.FORMULA_APPLICATION, description="V1 step", version=1
    )
    db_session.add(step_v1)
    await db_session.flush()

    state = _make_initial_state(exercise, professor_id)

    # 1er passage: V1 OK, V2 bloquant
    async def mock_run1(variant_id, trace_id=None):
        if variant_id == v1.id:
            return ReasoningGraphRead(
                variant_id=variant_id, construction_confidence=0.9,
                source_coverage_ratio=1.0, is_valid_dag=True, step_count=1,
                blocking_clarification_count=0, model_version="mock"
            )
        return ReasoningGraphRead(
            variant_id=variant_id, construction_confidence=0.4,
            source_coverage_ratio=0.4, is_valid_dag=False, step_count=0,
            blocking_clarification_count=1, model_version="mock"
        )

    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_run1),
    ):
        state = await reasoning_graph_node(state)

    assert state.pending_reasoning_graph_variant_ids == [str(v2.id)]

    # Reprise: V2 OK
    async def mock_run2(variant_id, trace_id=None):
        return ReasoningGraphRead(
            variant_id=variant_id, construction_confidence=0.9,
            source_coverage_ratio=1.0, is_valid_dag=True, step_count=1,
            blocking_clarification_count=0, model_version="mock"
        )

    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_run2),
    ):
        state = await reasoning_graph_node(state)

    # Vérifier que v1 n'a toujours qu'une version=1 et que sa variante.version n'a pas bougé
    await db_session.refresh(v1)
    assert v1.version == 1

    stmt = select(ReasoningStep).where(ReasoningStep.variant_id == v1.id)
    steps = (await db_session.execute(stmt)).scalars().all()
    assert len(steps) == 1
    assert steps[0].version == 1


@pytest.mark.anyio
async def test_routing_to_end_only_when_all_targets_resolved(db_session):
    from app.domain.models.assessment.question import Question
    from app.domain.models.assessment.solution_variant import SolutionVariant, VariantSource, VariantDifficulty
    from app.graph.nodes.reasoning_graph_node import reasoning_graph_node
    from app.domain.schemas.reasoning_graph_schemas import ReasoningGraphRead
    from app.services.reasoning_graph_service import ReasoningGraphService

    exercise, professor_id = await _seed_exercise(db_session)
    q1 = Question(exercise_id=exercise.id, order=1, statement="Q1")
    q2 = Question(exercise_id=exercise.id, order=2, statement="Q2")
    q3 = Question(exercise_id=exercise.id, order=3, statement="Q3")
    db_session.add_all([q1, q2, q3])
    await db_session.flush()

    v1 = SolutionVariant(question_id=q1.id, is_reference=True, content="S1", version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE)
    v2 = SolutionVariant(question_id=q2.id, is_reference=True, content="S2", version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE)
    v3 = SolutionVariant(question_id=q3.id, is_reference=True, content="S3", version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE)
    db_session.add_all([v1, v2, v3])
    await db_session.flush()

    state = _make_initial_state(exercise, professor_id)

    # Run 1: Les 3 variantes sont bloquantes
    async def mock_run1(variant_id, trace_id=None):
        return ReasoningGraphRead(
            variant_id=variant_id, construction_confidence=0.4,
            source_coverage_ratio=0.4, is_valid_dag=False, step_count=0,
            blocking_clarification_count=1, model_version="mock"
        )

    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_run1),
    ):
        state = await reasoning_graph_node(state)

    assert state.status == "PAUSED"
    assert set(state.pending_reasoning_graph_variant_ids) == {str(v1.id), str(v2.id), str(v3.id)}

    # Reprise 1: V1 et V2 résolues, V3 reste bloquante
    async def mock_run2(variant_id, trace_id=None):
        if variant_id in (v1.id, v2.id):
            return ReasoningGraphRead(
                variant_id=variant_id, construction_confidence=0.9,
                source_coverage_ratio=1.0, is_valid_dag=True, step_count=1,
                blocking_clarification_count=0, model_version="mock"
            )
        return ReasoningGraphRead(
            variant_id=variant_id, construction_confidence=0.4,
            source_coverage_ratio=0.4, is_valid_dag=False, step_count=0,
            blocking_clarification_count=1, model_version="mock"
        )

    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_run2),
    ):
        state = await reasoning_graph_node(state)

    # DOIT PAUSER À NOUVEAU car V3 n'est pas résolue !
    assert state.status == "PAUSED"
    assert state.pending_reasoning_graph_variant_ids == [str(v3.id)]

    # Reprise 2: V3 enfin résolue
    async def mock_run3(variant_id, trace_id=None):
        return ReasoningGraphRead(
            variant_id=variant_id, construction_confidence=0.9,
            source_coverage_ratio=1.0, is_valid_dag=True, step_count=1,
            blocking_clarification_count=0, model_version="mock"
        )

    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_run3),
    ):
        state = await reasoning_graph_node(state)

    # Tout résolu -> RUNNING
    assert state.status == "RUNNING"
    assert state.pending_reasoning_graph_variant_ids == []


@pytest.mark.anyio
async def test_retry_limit_raises_error_after_max_retries(db_session):
    from app.domain.models.assessment.question import Question
    from app.domain.models.assessment.solution_variant import SolutionVariant, VariantSource, VariantDifficulty
    from app.graph.nodes.reasoning_graph_node import reasoning_graph_node
    from app.domain.schemas.reasoning_graph_schemas import ReasoningGraphRead
    from app.services.reasoning_graph_service import ReasoningGraphService

    exercise, professor_id = await _seed_exercise(db_session)
    q1 = Question(exercise_id=exercise.id, order=1, statement="Q1")
    db_session.add(q1)
    await db_session.flush()

    v1 = SolutionVariant(question_id=q1.id, is_reference=True, content="S1", version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE)
    db_session.add(v1)
    await db_session.flush()

    state = _make_initial_state(exercise, professor_id)

    async def mock_blocking(variant_id, trace_id=None):
        return ReasoningGraphRead(
            variant_id=variant_id, construction_confidence=0.4,
            source_coverage_ratio=0.4, is_valid_dag=False, step_count=0,
            blocking_clarification_count=1, model_version="mock"
        )

    # 1er passage
    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_blocking),
    ):
        state = await reasoning_graph_node(state)
    assert state.status == "PAUSED"

    # Reprises 1, 2, 3 (MAX_RETRIES = 3 retentatives autorisées)
    for retry in range(1, 4):
        with (
            _patch_node_db_sessions(db_session),
            patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_blocking),
        ):
            state = await reasoning_graph_node(state)
        assert state.status == "PAUSED"

    # 5ème appel (reprise 4, retry_count atteint 4 > 3) -> doit lever RuntimeError
    with (
        _patch_node_db_sessions(db_session),
        patch.object(ReasoningGraphService, "build_graph_for_variant", side_effect=mock_blocking),
    ):
        with pytest.raises(RuntimeError, match="Nombre maximal de retentatives HITL"):
            await reasoning_graph_node(state)








