"""
Nœud LangGraph — document_structuring_node.

Couvre volontairement les DEUX premières étapes du pipeline OCR professeur
(OCR_Extraction_Agent PUIS Document_Structuring_Agent), pas seulement la
structuration : ExerciseOCRPipelineService.run() les enchaîne déjà en un
seul appel Python (téléchargement -> OCR -> structuration -> persistance,
cf. exercise_ocr_pipeline_service.py). Le plan validé garde ce service
intact plutôt que de le scinder en 2 frontières de service pour gagner un
checkpoint intermédiaire entre OCR et structuration — un vrai gain futur,
mais un changement de service, pas une simple orchestration.

ocr_teacher_correction_node.py reste donc vide, délibérément : il n'y a pas
de round-trip d'état entre "OCR fini" et "structuration commence" qui
justifierait un deuxième nœud sans réécrire ExerciseOCRPipelineService.

Edge conditionnelle en aval (pipeline_graph.py) : lit state.structuring_status
pour brancher vers extraction_verification_node (COMPLETE) ou vers une pause
(INCOMPLETE) — ce nœud pose le signal et gère lui-même StructuringIncompleteError
(seule exception que ExerciseOCRPipelineService.run() peut lever en régime
attendu, cf. son docstring), il ne route jamais lui-même.
"""
import uuid
from datetime import datetime, timezone

from app.agents.document_structuring_exceptions import StructuringIncompleteError
from app.core.database import get_db_context
from app.domain.repositories.agent_decision_log_repository import (
    SQLAlchemyAgentDecisionLogRepository,
)
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.teacher_correction_block_repository import (
    SQLAlchemyTeacherCorrectionBlockRepository,
)
from app.graph.state import PipelineState
from app.services.exercise_ocr_pipeline_service import ExerciseOCRPipelineService


async def document_structuring_node(state: PipelineState) -> PipelineState:
    exercise_id = uuid.UUID(state.exercise_id)
    professor_id = uuid.UUID(state.professor_id)

    async with get_db_context() as db:
        pipeline = ExerciseOCRPipelineService(
            exercise_repo=SQLAlchemyExerciseRepository(db),
            teacher_block_repo=SQLAlchemyTeacherCorrectionBlockRepository(db),
            decision_log_repo=SQLAlchemyAgentDecisionLogRepository(db),
        )
        try:
            raw_blocks, report = await pipeline.run(
                exercise_id=exercise_id,
                professor_id=professor_id,
                document_path=state.raw_file_path,
                mime_type=state.mime_type,
                trace_id=state.trace_id,
            )
        except StructuringIncompleteError:
            # Verrou bloquant immédiat (§ docstring ExerciseOCRPipelineService) :
            # la structuration a quand même été persistée telle quelle (HITL
            # immédiat), seul le graph doit s'arrêter ici tant que le prof n'a
            # pas résolu les blocs/sections en attente.
            state.structuring_status = "INCOMPLETE"
            state.status = "PAUSED"
            state.pending_action = "structuring_incomplete"
            state.updated_at = datetime.now(timezone.utc)
            return state

    state.raw_extracted_blocks = [b.model_dump(mode="json") for b in raw_blocks]
    state.structuring_status = report.status
    state.status = "RUNNING"
    state.pending_action = None
    state.updated_at = datetime.now(timezone.utc)
    return state
