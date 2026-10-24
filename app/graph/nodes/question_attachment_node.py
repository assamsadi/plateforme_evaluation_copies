"""
Nœud LangGraph — question_attachment_node.

Couvre volontairement les DEUX étapes du pipeline OCR étudiant
(OCR_Extraction_Agent PUIS Question_Attachment_Agent), pas seulement le
rattachement : SubmissionOCRPipelineService.run() les enchaîne déjà en un
seul appel Python (téléchargement -> OCR -> persistance -> rattachement,
cf. submission_ocr_pipeline_service.py) — même décision que
document_structuring_node côté exercise_setup (garder le service intact
plutôt que le scinder en 2 frontières pour gagner un checkpoint
intermédiaire, cf. son docstring pour l'argumentaire complet).

ocr_student_node.py reste donc vide, délibérément — même raison exacte que
ocr_teacher_correction_node.py côté exercise_setup.

Aucune exception à traduire en pause ici (contrairement à
document_structuring_node/StructuringIncompleteError) : ce service n'a pas
d'équivalent "résultat incomplet mais persisté" — soit il lève une erreur
réelle (propagée telle quelle, gérée par la tâche Celery), soit il aboutit.
La pause (attente de vérification étudiant / contestation éventuelle) vit
dans le nœud suivant, await_student_verification_node — jamais ici.
"""
import uuid
from datetime import datetime, timezone

from app.core.database import get_db_context
from app.domain.repositories.agent_decision_log_repository import (
    SQLAlchemyAgentDecisionLogRepository,
)
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.extraction_correction_repository import (
    SQLAlchemyExtractionCorrectionRepository,
)
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.graph.state import PipelineState
from app.services.idempotency_service import IdempotencyService
from app.services.submission_ocr_pipeline_service import SubmissionOCRPipelineService


async def question_attachment_node(state: PipelineState) -> PipelineState:
    submission_id = uuid.UUID(state.submission_id)
    exercise_id = uuid.UUID(state.exercise_id)
    student_id = uuid.UUID(state.student_id)

    async with get_db_context() as db:
        pipeline = SubmissionOCRPipelineService(
            submission_repo=SQLAlchemySubmissionRepository(db),
            extraction_repo=SQLAlchemyExtractionCorrectionRepository(db),
            exercise_repo=SQLAlchemyExerciseRepository(db),
            variant_repo=SQLAlchemySolutionVariantRepository(db),
            decision_log_repo=SQLAlchemyAgentDecisionLogRepository(db),
            idempotency_service=IdempotencyService(db),
        )
        raw_blocks = await pipeline.run(
            submission_id=submission_id,
            exercise_id=exercise_id,
            student_id=student_id,
            document_path=state.raw_file_path,
            mime_type=state.mime_type,
            trace_id=state.trace_id,
        )

    state.raw_extracted_blocks = [b.model_dump(mode="json") for b in raw_blocks]
    state.status = "RUNNING"
    state.updated_at = datetime.now(timezone.utc)
    return state
