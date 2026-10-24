"""
Nœud LangGraph — extraction_verification_node.

Ferme le trou identifié au diagnostic (conversation) : ExtractionVerificationService
n'avait jusqu'ici aucun appelant hors des tests — aucune tâche Celery, aucun
consumer Kafka. Appelé (edge posée dans pipeline_graph.py) après
document_structuring_node, seulement quand state.structuring_status == "COMPLETE".

Ne prend aucune décision de routage lui-même : il calcule
blocking_clarification_count (nombre de ClarificationRequest BLOCKING produites
par Extraction_Verification_Agent, cf. Phase 4/6) et pose pending_action en
conséquence — la edge conditionnelle qui lit ce signal vit dans
pipeline_graph.py, même séparation que document_structuring_node/
structuring_status.
"""
import uuid
from datetime import datetime, timezone

from app.core.database import get_db_context
from app.domain.repositories.agent_decision_log_repository import (
    SQLAlchemyAgentDecisionLogRepository,
)
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.reasoning_clarification_request_repository import (
    SQLAlchemyReasoningClarificationRequestRepository,
)
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.teacher_correction_block_repository import (
    SQLAlchemyTeacherCorrectionBlockRepository,
)
from app.graph.state import PipelineState
from app.services.extraction_verification_service import ExtractionVerificationService


async def extraction_verification_node(state: PipelineState) -> PipelineState:
    exercise_id = uuid.UUID(state.exercise_id)

    async with get_db_context() as db:
        service = ExtractionVerificationService(
            exercise_repository=SQLAlchemyExerciseRepository(db),
            teacher_correction_block_repository=SQLAlchemyTeacherCorrectionBlockRepository(db),
            solution_variant_repository=SQLAlchemySolutionVariantRepository(db),
            decision_log_repository=SQLAlchemyAgentDecisionLogRepository(db),
            clarification_repository=SQLAlchemyReasoningClarificationRequestRepository(db),
        )
        result = await service.verify_extraction(exercise_id, trace_id=state.trace_id)

    state.blocking_clarification_count = result.blocking_clarifications_created

    if result.blocking_clarifications_created > 0:
        # Au moins une répartition Cas 2 non confirmée ou une récurrence
        # incomplète (§ Phase 4/6) — jamais consommé en aval sans validation
        # professeur explicite, donc pause ici, pas de continuation silencieuse.
        state.status = "PAUSED"
        state.pending_action = "clarification_review"
        state.paused_at_node = "extraction_verification_node"
    else:
        state.status = "RUNNING"
        state.pending_action = None
        state.paused_at_node = None

    state.updated_at = datetime.now(timezone.utc)
    return state
