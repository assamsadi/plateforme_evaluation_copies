"""
Test d'intégration — pipeline_graph.py, branche student_evaluation, contre
une vraie DB (checkpointer Postgres réel, vrai LangGraph). Même principe que
test_pipeline_graph_exercise_setup.py : seuls les appels LLM/Azure sont
mockés (OCR_Extraction_Agent.execute, storage_service.download) ;
Question_Attachment_Agent n'est pas exercé dans les 3 premiers tests
(aucune SolutionVariant de référence seedée -> build_question_refs()
renvoie [], le rattachement est sauté par construction, pas mocké).

Couvre :
  1. Run jusqu'à la pause de vérification étudiant (première pause réelle
     de cette branche).
  2. Reprise "confirmation simple" (Command(resume={})) -> fin de run.
  3. Reprise "contestation à traiter" (Command(resume={"contestation_pending":
     True})) -> route vers contestation_verification_node (seul nœud réel
     pré-existant à ce câblage) -> fin de run (aucune contestation PENDING
     réelle dans ce scénario, le nœud doit rester un no-op silencieux).
  4. Câblage Priorité 1 (workflow) : soumission simple, sans ambiguïté,
     jusqu'à comparative_evaluation_node -> evaluation_node -> note réelle
     persistée (Evaluation + EvaluationCriteria par compétence). Question_
     Attachment_Agent.execute et Comparative_Evaluation_Agent.execute
     mockés (même niveau d'isolation que ReasoningGraphAgent.execute dans
     test_pipeline_graph_exercise_setup.py — la correction de ces agents
     est déjà testée à l'unité, ce test vérifie le CÂBLAGE, pas leur logique
     interne).
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

from app.agents.Comparative_Evaluation_Agent import (
    ComparativeEvaluationAgent,
    ComparativeEvaluationReport,
    CriterionEvaluationResult,
    SubquestionJudgment,
)
from app.agents.Extraction_Verification_Agent import CorrectionMode
from app.agents.Question_Attachment_Agent import AttachmentResult, QuestionAttachmentAgent
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.bareme import Bareme, BaremeValidationStatus
from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.evaluation_criteria import EvaluationCriteria
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.extraction_correction import (
    ExtractionContentType,
    StructureType,
)
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.recommended_exercise import (
    RecommendationCategory,
    RecommendationStatus,
    RecommendedExercise,
)
from app.domain.models.assessment.solution_variant import (
    SolutionVariant,
    VariantDifficulty,
    VariantSource,
)
from app.domain.models.assessment.student_feedback_report import StudentFeedbackReport
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_observation import (
    StudentCompetencyObservation,
)
from app.domain.models.competency.student_competency_profile import (
    CompetencyTrend,
    StudentCompetencyProfile,
)
from app.domain.repositories.extraction_correction_repository import (
    SQLAlchemyExtractionCorrectionRepository,
)
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.schemas.submission_schemas import AttachedExtractedBlock, RawExtractedBlock
from app.graph.checkpointer import get_checkpointer, setup_checkpointer_tables
from app.graph.pipeline_graph import compile_pipeline_graph
from app.graph.state import PipelineState
from app.agents.OCR_Extraction_Agent import OCRExtractionAgent
from langgraph.types import Command


async def _seed_submission(db_session) -> tuple[Exercise, Submission]:
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
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com",
        hashed_password="hash",
        first_name="Bob",
        last_name="Student",
        student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id,
        enrollment_year=2024,
        level="L3",
    )

    exercise = Exercise(
        module_id=module.id,
        created_by_professor_id=professor.id,
        title="Exercice étudiant graph",
        status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    submission = Submission(
        exercise_id=exercise.id,
        student_id=student.id,
        attempt_number=1,
        status=SubmissionStatus.PENDING_OCR,
        document_path="submissions/doc.pdf",
        document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    return exercise, submission


def _make_valid_scan_bytes() -> bytes:
    """
    PNG net/contrasté réel : depuis le câblage de scan_quality_control_node,
    storage_service.download() alimente un VRAI contrôle qualité
    déterministe (OpenCV, non mocké) avant OCR_Extraction_Agent — un
    placeholder b"fake-pdf-bytes" échouerait ce contrôle. mime_type posé à
    "image/png" en conséquence (cf. _make_initial_state).
    """
    arr = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.putText(arr, "Copie etudiant", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.rectangle(arr, (10, 10), (390, 390), (0, 0, 0), 2)
    _, buffer = cv2.imencode(".png", arr)
    return buffer.tobytes()


def _make_raw_block() -> RawExtractedBlock:
    return RawExtractedBlock(
        image_crop_path="crops/block1.png",
        content_type="TEXT",
        prediction_ocr="Réponse de l'étudiant.",
        confidence_score=Decimal("0.9"),
        bounding_box={"x": 0, "y": 0, "w": 10, "h": 10},
        page_number=1,
        block_order_index=0,
        evidence_level="label_explicite",
    )


def _make_initial_state(exercise: Exercise, submission: Submission) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(submission.id),
        flow_type="student_evaluation",
        trace_id=str(submission.id),
        exercise_id=str(exercise.id),
        submission_id=str(submission.id),
        module_id=str(exercise.module_id),
        student_id=str(submission.student_id),
        raw_file_path=submission.document_path,
        mime_type="image/png",
        created_at=now,
        updated_at=now,
    )


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


def _patch_node_db_sessions(db_session) -> ExitStack:
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
    # Chantier Feedback_Agent — un run qui atteint le bout de la branche
    # student_evaluation traverse désormais feedback_node, dont le SEUL
    # appel LLM du pipeline n'est PAS best-effort (contrairement au
    # déclenchement Celery NotebookLM) : sans ce mock, tout test de ce
    # fichier qui va jusqu'au bout ferait un vrai appel réseau. Tests de
    # ce fichier dédiés au câblage Feedback_Agent (ci-dessous) remplacent
    # ce mock par un patch plus spécifique quand ils veulent contrôler
    # précisément le texte retourné.
    default_feedback_response = MagicMock()
    default_feedback_response.content = "Continue ainsi, comment pourrais-tu vérifier ton résultat ?"
    default_feedback_spec = MagicMock(provider="groq", model_name="llama-3.3-70b-versatile")
    stack.enter_context(patch(
        "app.agents.Feedback_Agent.invoke_llm_with_fallback",
        AsyncMock(return_value=(default_feedback_response, default_feedback_spec, False, {})),
    ))
    return stack


@pytest.mark.anyio
async def test_run_pauses_at_student_verification(db_session):
    exercise, submission = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.submission_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["reason"] == "student_verification"


@pytest.mark.anyio
async def test_simple_confirmation_resume_ends_run(db_session):
    exercise, submission = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.submission_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)

            result = await graph.ainvoke(Command(resume="confirmed"), config=config)

    assert "__interrupt__" not in result
    assert result["contestation_check_requested"] is False


@pytest.mark.anyio
async def test_contestation_resume_routes_to_contestation_node(db_session):
    exercise, submission = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.submission_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)

            result = await graph.ainvoke(
                Command(resume="contestation_pending"), config=config,
            )

    # Aucune contestation PENDING_VERIFICATION réelle dans ce scénario :
    # contestation_verification_node doit rester un no-op silencieux et le
    # run doit se terminer normalement (pas d'interruption supplémentaire).
    assert "__interrupt__" not in result
    assert result["contestation_check_requested"] is True


def _make_structure_raw_block() -> RawExtractedBlock:
    """
    Bloc STRUCTURE réaliste (mêmes données que test_ocr_agent_emits_structure_
    even_with_printed_aggregate côté OCR_Extraction_Agent) — pas une fixture
    TEXT comme _make_raw_block() ci-dessus (écart identifié à l'audit, Partie
    C1 : aucun test d'intégration graph n'exerçait encore STRUCTURE).
    """
    return RawExtractedBlock(
        image_crop_path="crops/structure_block1.png",
        content_type="STRUCTURE",
        structure_type="TABLE",
        prediction_ocr="Tableau de valeurs",
        structured_output={
            "rows": [
                {
                    "cells": [
                        {"content": "x", "origin": "PRINTED", "is_struck_through": False},
                        {"content": "f(x)", "origin": "PRINTED", "is_struck_through": False},
                    ]
                },
                {
                    "cells": [
                        {"content": "2", "origin": "HANDWRITTEN", "is_struck_through": False},
                        {"content": "4", "origin": "HANDWRITTEN", "is_struck_through": False},
                    ]
                },
            ]
        },
        confidence_score=Decimal("0.85"),
        reconstruction_confidence=Decimal("0.80"),
        bounding_box={"x": 0, "y": 0, "w": 10, "h": 10},
        page_number=1,
        block_order_index=0,
        origin="HANDWRITTEN",
        evidence_level="label_explicite",
    )


@pytest.mark.anyio
async def test_structure_block_survives_question_attachment_node(db_session):
    """
    Priorité 5 (audit, Partie C1) : un bloc STRUCTURE produit par l'agent 1
    traverse réellement question_attachment_node (via le vrai graph, vraie
    DB) sans perte du contenu structuré — pas une fixture TEXT comme les
    autres tests de ce fichier.

    NOTE — écart découvert en écrivant ce test, non corrigé ici (hors mandat
    Priorité 5, nécessiterait une migration de schéma) : ExtractionCorrection
    n'a AUCUNE colonne structure_type (vérifié : ni le modèle SQLAlchemy, ni
    raw_blocks_to_persistence_dicts(), ni bulk_create_for_submission() ne le
    portent) — ce champ produit par OCR_Extraction_Agent est donc perdu à la
    persistance, côté étudiant ET côté professeur (TeacherCorrectionBlock n'a
    pas non plus cette colonne). content_type et structured_output, eux,
    survivent intacts — vérifié ci-dessous.
    """
    exercise, submission = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}
    structure_block = _make_structure_raw_block()

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.submission_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[structure_block])),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            result = await graph.ainvoke(initial_state, config=config)

    assert "__interrupt__" in result  # pause de vérification étudiant atteinte normalement

    correction_repo = SQLAlchemyExtractionCorrectionRepository(db_session)
    corrections = await correction_repo.get_by_submission_id(submission.id)
    assert len(corrections) == 1
    persisted = corrections[0]

    assert persisted.content_type == ExtractionContentType.STRUCTURE
    assert persisted.structured_output == structure_block.structured_output

    # Écart documenté ci-dessus, gardé explicite plutôt que silencieux :
    # structure_type ne survit pas à la persistance, faute de colonne.
    assert not hasattr(persisted, "structure_type")


@pytest.mark.anyio
async def test_simple_submission_reaches_persisted_evaluation_score(db_session):
    """
    Câblage Priorité 1 — bout-en-bout réel, à travers le graph compilé :
    une soumission simple (une question, un critère, aucune ambiguïté)
    traverse OCR -> rattachement -> vérification étudiant (confirmation
    simple, sans contestation) -> comparative_evaluation_node ->
    evaluation_node, jusqu'à une note persistée en base.
    """
    exercise, submission = await _seed_submission(db_session)

    question = Question(
        exercise_id=exercise.id, order=1, statement="Calculer l'aire du rectangle.",
        covered_subquestions=["1.1", "3.1"],
        # Chantier barème C2PCT natif (Cas 0) — ce test exerce la CHAÎNE
        # C2PCT en aval (competency_assessment_node, cf. assertions plus
        # bas) : sans subquestion_points, le discriminant de routage
        # (calcul de note classique, ticket dédié) enverrait cette question
        # vers le mécanisme CLASSIQUE (barème à critères ci-dessous), qui
        # n'alimente jamais le profil de compétence C2PCT. Chiffrage exact
        # 3.00/3.00 -> mêmes bareme_share que l'ancien calcul proportionnel
        # (6.00 / 2 sous-questions), assertions plus bas inchangées.
        subquestion_points={"1.1": "3.00", "3.1": "3.00"},
    )
    db_session.add(question)
    await db_session.flush()

    bareme = Bareme(
        question_id=question.id,
        points=Decimal("6.00"),
        criteria=[
            {
                "id": "crit-1", "label": "exactitude", "points": 6.0,
                "correction_mode": CorrectionMode.CRITERIA_BASED.value,
                "verifiable_conditions": ["Calcule correctement l'aire"],
                "disqualifying": False, "test_cases": [], "reference_code": None,
                "expected_complexity": None,
            }
        ],
        validation_status=BaremeValidationStatus.CONFIRMED,
    )
    db_session.add(bareme)

    reference_variant = SolutionVariant(
        question_id=question.id, is_reference=True, content="Aire = L * l = 12 cm2.",
        version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE,
    )
    db_session.add(reference_variant)
    await db_session.flush()

    config = {"configurable": {"thread_id": str(submission.id)}}
    raw_block = _make_raw_block()

    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(),
        submission_id=submission.id,
        question_id=question.id,
    )

    comparative_report = ComparativeEvaluationReport(
        question_id=question.id,
        criterion_results=[
            CriterionEvaluationResult(
                criterion_id="crit-1",
                correction_mode=CorrectionMode.CRITERIA_BASED,
                is_satisfied=True,
                score_ratio=1.0,
                justification="Réponse correcte.",
                confidence_score=0.9,
            )
        ],
        overall_confidence=0.9,
        subquestion_judgments=[
            SubquestionJudgment(
                subquestion_id="1.1", addressed=True, is_correct=True,
                evidence_reference="Aire = 12 cm2", source="new_llm_judgment",
                completion_ratio=Decimal("1.0"),
            ),
            SubquestionJudgment(
                subquestion_id="3.1", addressed=True, is_correct=True,
                evidence_reference="Aire = L * l = 12 cm2", source="new_llm_judgment",
                completion_ratio=Decimal("1.0"),
            ),
        ],
    )

    # Ce test est le premier de ce fichier où le rattachement produit un
    # bloc avec question_id renseigné (SolutionVariant de référence seedée
    # -> build_question_refs() non vide) : contrairement aux 3 tests
    # pré-existants (aucune référence seedée, rattachement sauté par
    # construction, cf. leur docstring de module), submission_ocr_pipeline_
    # service.run() atteint donc réellement l'appel EventPublisherService.
    # publish_extraction_ready (Kafka), jamais mocké nulle part ailleurs
    # dans ce fichier — sans ce mock, échec réel ici (KafkaConnectionError,
    # aucun broker dans cet environnement de test), aucun rapport avec le
    # câblage Priorité 1 lui-même.
    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.submission_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[raw_block])),
        patch.object(
            QuestionAttachmentAgent, "execute",
            AsyncMock(return_value=AttachmentResult(attached_blocks=[attached_block])),
        ),
        patch.object(
            ComparativeEvaluationAgent, "execute",
            AsyncMock(return_value=comparative_report),
        ),
        patch(
            "app.services.submission_ocr_pipeline_service.EventPublisherService",
            return_value=mock_event_publisher,
        ),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)

            result = await graph.ainvoke(Command(resume="confirmed"), config=config)

    assert "__interrupt__" not in result

    stmt = select(Evaluation).where(
        Evaluation.submission_id == submission.id, Evaluation.question_id == question.id,
    )
    evaluation = (await db_session.execute(stmt)).scalar_one()

    # Bareme.points = 6, 2 sous-questions couvertes (1.1 -> DATA_AND_PLANNING,
    # 3.1 -> ALGORITHMIC_STRUCTURING), toutes les deux réussies -> 3.00 + 3.00 = 6.00.
    assert evaluation.score == Decimal("6.00")

    crit_stmt = select(EvaluationCriteria).where(EvaluationCriteria.evaluation_id == evaluation.id)
    criteria_rows = (await db_session.execute(crit_stmt)).scalars().all()
    by_competency = {c.competency_code: c for c in criteria_rows}
    assert set(by_competency) == {C2PCTSkillCode.DATA_AND_PLANNING, C2PCTSkillCode.ALGORITHMIC_STRUCTURING}
    assert by_competency[C2PCTSkillCode.DATA_AND_PLANNING].points_awarded == Decimal("3.00")
    assert by_competency[C2PCTSkillCode.DATA_AND_PLANNING].criterion_id is None
    assert by_competency[C2PCTSkillCode.DATA_AND_PLANNING].subquestion_detail["covered_count"] == 1

    # Câblage copy_report — preuve que le QuestionReport traverse RÉELLEMENT
    # le graph compilé (comparative_evaluation_node -> state.comparison_
    # results -> evaluation_node -> build_question_report ->
    # record_question_score) jusqu'à Evaluation.copy_report_detail, pas
    # seulement assemblé au niveau agent (déjà couvert par les tests
    # unitaires). Scénario "simple, sans ambiguïté" par construction (nom du
    # test) : les 2 sous-questions sont des réussites triviales
    # (source="new_llm_judgment", is_correct=True) -> ComparativeEvaluation
    # Agent.decision_entries est vide (cf. _build_decision_entries), donc
    # les 2 lignes de compétence portent decisions=[] ici, sans que cela
    # signale un défaut de câblage.
    assert evaluation.copy_report_detail is not None
    assert evaluation.copy_report_detail["note"] == "6.00"
    assert evaluation.copy_report_detail["bareme_points"] == "6.00"
    assert evaluation.copy_report_detail["consigne_respected"] is None
    report_by_competency = {
        line["competency"]: line for line in evaluation.copy_report_detail["competency_lines"]
    }
    assert set(report_by_competency) == {"data_and_planning", "algorithmic_structuring"}
    assert report_by_competency["data_and_planning"]["decisions"] == []
    assert report_by_competency["data_and_planning"]["points_awarded"] == "3.00"

    # Câblage Partie 2/2 (C2PCT) — preuve que competency_assessment_node
    # s'exécute RÉELLEMENT après evaluation_node dans CE MÊME run de graph
    # compilé (pas un appel de service isolé) : StudentCompetencyObservation
    # (Niveau 2) ET le cache StudentCompetencyProfile (Niveau 3) persistés,
    # un par compétence mobilisée (1.1 -> DATA_AND_PLANNING, 3.1 ->
    # ALGORITHMIC_STRUCTURING, chacune 1 sous-question couverte/réussie ->
    # performance_copie = 1/1 = 1.00000, calcul de référence à la main).
    obs_stmt = select(StudentCompetencyObservation).where(
        StudentCompetencyObservation.submission_id == submission.id,
    )
    observations = (await db_session.execute(obs_stmt)).scalars().all()
    obs_by_competency = {o.competency_code: o for o in observations}
    assert set(obs_by_competency) == {C2PCTSkillCode.DATA_AND_PLANNING, C2PCTSkillCode.ALGORITHMIC_STRUCTURING}
    assert obs_by_competency[C2PCTSkillCode.DATA_AND_PLANNING].performance_copie == Decimal("1.00000")
    assert obs_by_competency[C2PCTSkillCode.DATA_AND_PLANNING].subquestions_covered_count == 1
    assert obs_by_competency[C2PCTSkillCode.DATA_AND_PLANNING].subquestions_succeeded_count == 1
    assert obs_by_competency[C2PCTSkillCode.DATA_AND_PLANNING].question_ids == [str(question.id)]

    profile_stmt = select(StudentCompetencyProfile).where(
        StudentCompetencyProfile.student_id == submission.student_id,
    )
    profiles = (await db_session.execute(profile_stmt)).scalars().all()
    profile_by_competency = {p.competency_code: p for p in profiles}
    assert set(profile_by_competency) == {C2PCTSkillCode.DATA_AND_PLANNING, C2PCTSkillCode.ALGORITHMIC_STRUCTURING}
    dap_profile = profile_by_competency[C2PCTSkillCode.DATA_AND_PLANNING]
    assert dap_profile.mastery_level == Decimal("100.00")
    assert dap_profile.trend == CompetencyTrend.INSUFFICIENT_DATA  # une seule observation
    assert dap_profile.evaluations_count == 1
    assert dap_profile.confidence_level == Decimal("0.20")
    assert dap_profile.is_persistent_weakness is False


@pytest.mark.anyio
async def test_recommendation_node_persists_matching_library_exercise(db_session):
    """
    Câblage Phase 2 (chantier Recommendation_Agent) — preuve que
    recommendation_node s'exécute RÉELLEMENT après competency_assessment_node
    dans CE MÊME run de graph compilé (pas un appel de service isolé) : une
    sous-question ratée -> mastery_level bas -> RecommendedExercise ACTIVE
    persistée, pointant vers un exercice réellement ARCHIVED_IN_LIBRARY du
    module (jamais un exercice publié en devoir).
    """
    exercise, submission = await _seed_submission(db_session)

    question = Question(
        exercise_id=exercise.id, order=1, statement="Calculer l'aire du rectangle.",
        covered_subquestions=["1.1"],
        # Chantier barème C2PCT natif (Cas 0) — cf. commentaire équivalent
        # dans test_simple_submission_reaches_persisted_evaluation_score :
        # ce test exerce la chaîne C2PCT (competency_assessment_node ->
        # recommendation_node), qui n'est alimentée QUE par le mécanisme
        # C2PCT natif. Chiffrage exact 6.00 -> même bareme_share que
        # l'ancien calcul proportionnel (6.00 / 1 seule sous-question).
        subquestion_points={"1.1": "6.00"},
    )
    db_session.add(question)
    await db_session.flush()

    bareme = Bareme(
        question_id=question.id,
        points=Decimal("6.00"),
        criteria=[
            {
                "id": "crit-1", "label": "exactitude", "points": 6.0,
                "correction_mode": CorrectionMode.CRITERIA_BASED.value,
                "verifiable_conditions": ["Calcule correctement l'aire"],
                "disqualifying": False, "test_cases": [], "reference_code": None,
                "expected_complexity": None,
            }
        ],
        validation_status=BaremeValidationStatus.CONFIRMED,
    )
    db_session.add(bareme)

    reference_variant = SolutionVariant(
        question_id=question.id, is_reference=True, content="Aire = L * l = 12 cm2.",
        version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE,
    )
    db_session.add(reference_variant)

    # Exercice de bibliothèque couvrant la MÊME compétence (1.1 ->
    # DATA_AND_PLANNING, cf. c2pct_scaffold.py) — seul candidat possible pour
    # la recommandation générée par ce run.
    library_exercise = Exercise(
        module_id=exercise.module_id, created_by_professor_id=exercise.created_by_professor_id,
        title="Exo bibliotheque - aires", status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
    )
    db_session.add(library_exercise)
    await db_session.flush()
    library_question = Question(
        exercise_id=library_exercise.id, order=1, statement="Q1", covered_subquestions=["1.1"],
    )
    db_session.add(library_question)
    await db_session.flush()

    config = {"configurable": {"thread_id": str(submission.id)}}
    raw_block = _make_raw_block()

    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(),
        submission_id=submission.id,
        question_id=question.id,
    )

    # Sous-question ratée -> performance_copie = 0/1 = 0.00000 -> mastery_
    # level bas (palier "faiblesse occasionnelle") -> déclenche une
    # recommandation REMEDIATION pour DATA_AND_PLANNING.
    comparative_report = ComparativeEvaluationReport(
        question_id=question.id,
        criterion_results=[
            CriterionEvaluationResult(
                criterion_id="crit-1",
                correction_mode=CorrectionMode.CRITERIA_BASED,
                is_satisfied=False,
                score_ratio=0.0,
                justification="Réponse incorrecte.",
                confidence_score=0.9,
            )
        ],
        overall_confidence=0.9,
        subquestion_judgments=[
            SubquestionJudgment(
                subquestion_id="1.1", addressed=True, is_correct=False,
                evidence_reference="Aire = 8 cm2 (faux)", source="new_llm_judgment",
                completion_ratio=Decimal("0.0"),
            ),
        ],
    )

    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.submission_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[raw_block])),
        patch.object(
            QuestionAttachmentAgent, "execute",
            AsyncMock(return_value=AttachmentResult(attached_blocks=[attached_block])),
        ),
        patch.object(
            ComparativeEvaluationAgent, "execute",
            AsyncMock(return_value=comparative_report),
        ),
        patch(
            "app.services.submission_ocr_pipeline_service.EventPublisherService",
            return_value=mock_event_publisher,
        ),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)

            result = await graph.ainvoke(Command(resume="confirmed"), config=config)

    assert "__interrupt__" not in result

    stmt = select(RecommendedExercise).where(RecommendedExercise.student_id == submission.student_id)
    recommendations = (await db_session.execute(stmt)).scalars().all()
    assert len(recommendations) == 1
    rec = recommendations[0]
    assert rec.module_id == exercise.module_id
    assert rec.competency_code == C2PCTSkillCode.DATA_AND_PLANNING
    assert rec.category == RecommendationCategory.REMEDIATION
    assert rec.status == RecommendationStatus.ACTIVE
    assert rec.exercise_id == library_exercise.id  # jamais l'exercice-devoir lui-même
    assert rec.submission_id == submission.id


def _mock_feedback_llm_response(text: str):
    """Même convention que test_reasoning_graph_agent.py::_mock_response — conforme au 4-tuple invoke_llm_with_fallback."""
    fake_response = MagicMock()
    fake_response.content = text
    fake_spec = MagicMock()
    fake_spec.provider = "groq"
    fake_spec.model_name = "llama-3.3-70b-versatile"
    return (fake_response, fake_spec, False, {"total_tokens": 120})


@pytest.mark.anyio
async def test_feedback_node_persists_socratic_report_after_recommendation(db_session):
    """
    Câblage chantier Feedback_Agent (§7) — preuve bout-en-bout à travers le
    VRAI graph compilé (pas un appel de service isolé) : reprend exactement
    le scénario de test_recommendation_node_persists_matching_library_
    exercise ci-dessus (sous-question ratée -> RecommendedExercise ACTIVE),
    et vérifie que feedback_node s'exécute ENSUITE dans le MÊME run,
    jusqu'à un StudentFeedbackReport réellement persisté en base.

    Seul Feedback_Agent.invoke_llm_with_fallback est mocké ici (comme
    Comparative_Evaluation_Agent.execute pour les autres tests de ce
    fichier) — tout le reste (FeedbackReportService, feedback_node,
    persistance) est le vrai code, exercé à travers le vrai graph.
    """
    exercise, submission = await _seed_submission(db_session)

    question = Question(
        exercise_id=exercise.id, order=1, statement="Calculer l'aire du rectangle.",
        covered_subquestions=["1.1"],
        # Chantier barème C2PCT natif (Cas 0) — cf. commentaire équivalent
        # dans test_simple_submission_reaches_persisted_evaluation_score :
        # ce test reprend le scénario de test_recommendation_node_persists_
        # matching_library_exercise, dont la chaîne C2PCT (jusqu'à
        # recommendation_node) n'est alimentée QUE par le mécanisme C2PCT
        # natif.
        subquestion_points={"1.1": "6.00"},
    )
    db_session.add(question)
    await db_session.flush()

    bareme = Bareme(
        question_id=question.id,
        points=Decimal("6.00"),
        criteria=[
            {
                "id": "crit-1", "label": "exactitude", "points": 6.0,
                "correction_mode": CorrectionMode.CRITERIA_BASED.value,
                "verifiable_conditions": ["Calcule correctement l'aire"],
                "disqualifying": False, "test_cases": [], "reference_code": None,
                "expected_complexity": None,
            }
        ],
        validation_status=BaremeValidationStatus.CONFIRMED,
    )
    db_session.add(bareme)

    reference_variant = SolutionVariant(
        question_id=question.id, is_reference=True, content="Aire = L * l = 12 cm2.",
        version=1, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.FACILE,
    )
    db_session.add(reference_variant)

    library_exercise = Exercise(
        module_id=exercise.module_id, created_by_professor_id=exercise.created_by_professor_id,
        title="Exo bibliotheque - aires", status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
    )
    db_session.add(library_exercise)
    await db_session.flush()
    library_question = Question(
        exercise_id=library_exercise.id, order=1, statement="Q1", covered_subquestions=["1.1"],
    )
    db_session.add(library_question)
    await db_session.flush()

    config = {"configurable": {"thread_id": str(submission.id)}}
    raw_block = _make_raw_block()

    attached_block = AttachedExtractedBlock(
        **raw_block.model_dump(),
        submission_id=submission.id,
        question_id=question.id,
    )

    comparative_report = ComparativeEvaluationReport(
        question_id=question.id,
        criterion_results=[
            CriterionEvaluationResult(
                criterion_id="crit-1",
                correction_mode=CorrectionMode.CRITERIA_BASED,
                is_satisfied=False,
                score_ratio=0.0,
                justification="Réponse incorrecte.",
                confidence_score=0.9,
            )
        ],
        overall_confidence=0.9,
        subquestion_judgments=[
            SubquestionJudgment(
                subquestion_id="1.1", addressed=True, is_correct=False,
                evidence_reference="Aire = 8 cm2 (faux)", source="new_llm_judgment",
                completion_ratio=Decimal("0.0"),
            ),
        ],
    )

    mock_event_publisher = MagicMock()
    mock_event_publisher.publish_extraction_ready = AsyncMock()

    socratic_text = (
        "Tu as bien identifié qu'il fallait calculer une aire, c'est un bon réflexe. "
        "Relis ta réponse à la question 1 : que représente exactement L * l ici, et "
        "es-tu sûr d'avoir utilisé les bonnes valeurs de longueur et largeur ? "
        "Pour t'entraîner encore sur ce point, jette un œil à « Exo bibliotheque - aires »."
    )

    with (
        _patch_node_db_sessions(db_session),
        patch(
            "app.services.submission_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock,
            return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[raw_block])),
        patch.object(
            QuestionAttachmentAgent, "execute",
            AsyncMock(return_value=AttachmentResult(attached_blocks=[attached_block])),
        ),
        patch.object(
            ComparativeEvaluationAgent, "execute",
            AsyncMock(return_value=comparative_report),
        ),
        patch(
            "app.services.submission_ocr_pipeline_service.EventPublisherService",
            return_value=mock_event_publisher,
        ),
        patch(
            "app.agents.Feedback_Agent.invoke_llm_with_fallback",
            AsyncMock(return_value=_mock_feedback_llm_response(socratic_text)),
        ),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            initial_state = _make_initial_state(exercise, submission)
            await graph.ainvoke(initial_state, config=config)

            result = await graph.ainvoke(Command(resume="confirmed"), config=config)

    assert "__interrupt__" not in result

    stmt = select(StudentFeedbackReport).where(StudentFeedbackReport.submission_id == submission.id)
    report = (await db_session.execute(stmt)).scalar_one()

    assert report.student_id == submission.student_id
    assert report.module_id == exercise.module_id
    assert report.feedback_text == socratic_text
    assert "?" in report.feedback_text  # garde-fou socratique — pas de retry nécessaire ici
    assert report.competencies_addressed == [C2PCTSkillCode.DATA_AND_PLANNING.value]
