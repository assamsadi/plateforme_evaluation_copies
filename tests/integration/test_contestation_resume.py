"""
Test d'intégration — process_contestation_verification (contestation_tasks.py)
déclenche réellement la reprise du thread LangGraph en pause (job_tasks.py::
process_job_resumed), quand un Job actif existe exactement à
await_student_verification_node pour cette soumission. Chemin direct
(ContestationVerificationService) inchangé, testé ailleurs — ici seul
l'AJOUT (câblage de la reprise) est couvert.

process_contestation_verification est un vrai callable Celery
(asyncio.run() interne) : impossible à appeler directement depuis un test
async (RuntimeError, constaté) — appelé ici via asyncio.to_thread(), exactement
comme un worker Celery l'exécuterait (thread séparé, jamais imbriqué dans la
boucle asyncio de l'appelant). Conséquence directe : ce thread ouvre ses
PROPRES sessions DB (get_db_context réel, pas la session du test réutilisée
comme dans les autres tests d'intégration) — la donnée seedée est donc
committée explicitement (pas seulement flush) pour lui être visible, puis
nettoyée manuellement en fin de test (pas de rollback automatique possible
sur une transaction déjà committée).
"""
import asyncio
import uuid
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest
from sqlalchemy import delete

from app.agents.OCR_Extraction_Agent import OCRExtractionAgent
from app.core.database import get_db_context
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionCorrection
from app.domain.models.assessment.recommended_exercise import RecommendedExercise
from app.domain.models.assessment.student_feedback_report import StudentFeedbackReport
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.identity.user import Professor, Student
from app.domain.models.system_infrastructure.job import Job, JobStatus
from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.schemas.submission_schemas import RawExtractedBlock
from app.graph.checkpointer import get_checkpointer, setup_checkpointer_tables
from app.graph.job_sync import sync_job_after_graph_run
from app.graph.pipeline_graph import compile_pipeline_graph
from app.graph.state import PipelineState
from app.tasks.contestation_tasks import process_contestation_verification


async def _seed_submission(db_session) -> tuple[Exercise, Submission, uuid.UUID, uuid.UUID]:
    """Retourne aussi (group_id, program_id) — nécessaires au nettoyage complet en fin de test."""
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
        first_name="Prof", last_name="Resume", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Student", student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id, enrollment_year=2024, level="L3",
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice reprise", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.PENDING_OCR,
        document_path="submissions/doc.pdf", document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    return exercise, submission, group.id, prog.id


def _make_valid_scan_bytes() -> bytes:
    """PNG net/contrasté réel : scan_quality_control_node effectue un vrai
    contrôle qualité déterministe (non mocké) avant OCR_Extraction_Agent."""
    arr = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.putText(arr, "Copie", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.rectangle(arr, (10, 10), (390, 390), (0, 0, 0), 2)
    _, buffer = cv2.imencode(".png", arr)
    return buffer.tobytes()


def _make_raw_block() -> RawExtractedBlock:
    return RawExtractedBlock(
        image_crop_path="crops/block1.png", content_type="TEXT",
        prediction_ocr="Réponse.", confidence_score=Decimal("0.9"),
        bounding_box={"x": 0, "y": 0, "w": 1, "h": 1}, page_number=1,
        block_order_index=0, evidence_level="label_explicite",
    )


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


def _patch_db_sessions(db_session) -> ExitStack:
    stack = ExitStack()
    for target in (
        "app.graph.nodes.entry_router_node.get_db_context",
        "app.graph.nodes.question_attachment_node.get_db_context",
        "app.graph.job_sync.get_db_context",
    ):
        stack.enter_context(patch(target, lambda: _reuse_session(db_session)))
    return stack


@pytest.mark.anyio
async def test_process_contestation_verification_resumes_paused_thread(db_session):
    exercise, submission, group_id, program_id = await _seed_submission(db_session)
    await setup_checkpointer_tables()
    config = {"configurable": {"thread_id": str(submission.id)}}

    with (
        _patch_db_sessions(db_session),
        patch(
            "app.services.submission_ocr_pipeline_service.storage_service.download",
            new_callable=AsyncMock, return_value=_make_valid_scan_bytes(),
        ),
        patch.object(OCRExtractionAgent, "execute", AsyncMock(return_value=[_make_raw_block()])),
        patch("app.observability.langfuse.langfuse", MagicMock()),
    ):
        now = datetime.now(timezone.utc)
        initial_state = PipelineState(
            thread_id=str(submission.id), flow_type="student_evaluation",
            trace_id=str(submission.id), exercise_id=str(exercise.id),
            submission_id=str(submission.id), module_id=str(exercise.module_id),
            student_id=str(submission.student_id), raw_file_path=submission.document_path,
            mime_type="image/png", created_at=now, updated_at=now,
        )
        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            result = await graph.ainvoke(initial_state, config=config)
            snapshot = await graph.aget_state(config)
        next_node = snapshot.next[0] if snapshot.next else None
        await sync_job_after_graph_run(submission.id, result, next_node)

    job_repo = SQLAlchemyJobRepository(db_session)
    job_before = await job_repo.get_active_job_for_thread(submission.id)
    assert job_before is not None
    assert job_before.status == JobStatus.INTERRUPTED
    assert job_before.current_node == "await_student_verification_node"

    # Rend la donnée visible à un thread séparé (process_contestation_verification
    # ouvre ses propres sessions, cf. docstring du module) — nettoyé en fin de test.
    await db_session.commit()

    # Le run peut atteindre feedback_node (chantier Feedback_Agent, câblé
    # après recommendation_node, en bout de la branche student_evaluation) —
    # sans ce mock, le SEUL appel LLM du pipeline tenterait un vrai appel
    # réseau ici, hors du périmètre de ce test (reprise de contestation, pas
    # Feedback_Agent).
    feedback_response = MagicMock()
    feedback_response.content = "Continue ainsi, comment pourrais-tu vérifier ton résultat ?"
    feedback_spec = MagicMock(provider="groq", model_name="llama-3.3-70b-versatile")

    try:
        with (
            patch("app.observability.langfuse.langfuse", MagicMock()),
            patch(
                "app.agents.Feedback_Agent.invoke_llm_with_fallback",
                AsyncMock(return_value=(feedback_response, feedback_spec, False, {})),
            ),
        ):
            await asyncio.to_thread(
                process_contestation_verification, submission_id=str(submission.id),
            )

        # Session fraîche plutôt que réutiliser db_session ici : un autre
        # thread/greenlet a fait des E/S concurrentes entre-temps
        # (asyncio.to_thread), réutiliser le contexte greenlet de db_session
        # après coup lève MissingGreenlet (constaté) — pas grave en soi, la
        # bonne pratique est justement de ne pas mélanger les deux.
        async with get_db_context() as fresh_db:
            job_after = await SQLAlchemyJobRepository(fresh_db).get_active_job_for_thread(
                submission.id
            )
        # Aucune contestation PENDING_VERIFICATION réelle : contestation_
        # verification_node no-op, le thread atteint __end__, Job -> COMPLETED
        # (donc plus "actif" au sens de get_active_job_for_thread).
        assert job_after is None

        async with get_checkpointer() as checkpointer:
            graph = compile_pipeline_graph(checkpointer)
            final_snapshot = await graph.aget_state(config)
        assert final_snapshot.next == ()
    finally:
        # Ordre FK-safe complet (constaté à l'usage : student_feedback_
        # reports/recommended_exercises (chantier Feedback_Agent, le run
        # traverse désormais feedback_node) -> extraction_corrections ->
        # submissions -> exercises -> students -> modules/groups -> program).
        await db_session.execute(delete(Job).where(Job.submission_id == submission.id))
        await db_session.execute(
            delete(StudentFeedbackReport).where(StudentFeedbackReport.submission_id == submission.id)
        )
        await db_session.execute(
            delete(RecommendedExercise).where(RecommendedExercise.submission_id == submission.id)
        )
        await db_session.execute(
            delete(ExtractionCorrection).where(ExtractionCorrection.submission_id == submission.id)
        )
        await db_session.execute(delete(Submission).where(Submission.id == submission.id))
        await db_session.execute(delete(Exercise).where(Exercise.id == exercise.id))
        await db_session.execute(delete(Student).where(Student.id == submission.student_id))
        await db_session.execute(delete(Professor).where(Professor.id == exercise.created_by_professor_id))
        await db_session.execute(delete(Module).where(Module.id == exercise.module_id))
        await db_session.execute(delete(Group).where(Group.id == group_id))
        await db_session.execute(delete(Program).where(Program.id == program_id))
        await db_session.commit()
