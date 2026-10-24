"""
Nœud LangGraph — contestation_verification_node.

À écrire à l'identique des 4 agents avant leurs nœuds : une fonction
correcte, typée, testable en isolation. `pipeline_graph.py`/`checkpointer.py`/
`routing.py` sont vides (0 octet) — aucune edge conditionnelle n'existe
encore pour lire le résultat posé ici, et `correction_triage_node.py`/
`teacher_arbitration_node.py`/`assembly_node.py` sont eux aussi vides : ce
nœud n'est donc appelé par rien de réel aujourd'hui. Le chemin réellement
fonctionnel de bout en bout est l'endpoint HTTP -> tâche Celery
(`app/tasks/contestation_tasks.py::process_contestation_verification`) ->
même service. Ce nœud et cette tâche appellent délibérément le même
`ContestationVerificationService.process_pending_contestations` par deux
points d'entrée distincts (duplication assumée, pas accidentelle) : l'un
fonctionne déjà via Celery, l'autre attend `pipeline_graph.py` pour être
réellement invoqué dans un run LangGraph.

Ce nœud pose l'état (status/pending_action/arbitration_required) pour
qu'une future edge conditionnelle route vers teacher_arbitration_node ou
assembly_node — il ne route vers rien lui-même, aucune edge n'existant à
router aujourd'hui.
"""
import uuid
from datetime import datetime, timezone

from app.agents.context import AgentExecutionContext
from app.core.database import get_db_context
from app.domain.repositories.agent_decision_log_repository import (
    SQLAlchemyAgentDecisionLogRepository,
)
from app.domain.repositories.correction_arbitration_repository import (
    SQLAlchemyCorrectionArbitrationRepository,
)
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.extraction_correction_repository import (
    SQLAlchemyExtractionCorrectionRepository,
)
from app.domain.repositories.integrity_alert_repository import SQLAlchemyIntegrityAlertRepository
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.graph.state import PipelineState
from app.services.contestation_verification_service import ContestationVerificationService


async def contestation_verification_node(state: PipelineState) -> PipelineState:
    """
    Appelé (en théorie, cf. docstring du module) depuis correction_triage_node
    uniquement si au moins une contestation est en attente sur la soumission.
    """
    submission_id = uuid.UUID(state.submission_id)

    async with get_db_context() as db:
        submission_repo = SQLAlchemySubmissionRepository(db)
        service = ContestationVerificationService(
            extraction_correction_repo=SQLAlchemyExtractionCorrectionRepository(db),
            correction_arbitration_repo=SQLAlchemyCorrectionArbitrationRepository(db),
            submission_repo=submission_repo,
            exercise_repo=SQLAlchemyExerciseRepository(db),
            solution_variant_repo=SQLAlchemySolutionVariantRepository(db),
            decision_log_repo=SQLAlchemyAgentDecisionLogRepository(db),
            integrity_alert_repo=SQLAlchemyIntegrityAlertRepository(db),
        )
        context = AgentExecutionContext(
            trace_id=state.trace_id,
            flow_type=state.flow_type,
            submission_id=submission_id,
            exercise_id=uuid.UUID(state.exercise_id) if state.exercise_id else None,
        )
        result = await service.process_pending_contestations(submission_id, context)

    needs_arbitration = result.flagged_for_manual_review or any(
        verdict.verdict == "AMBIGU" for verdict in result.verdicts
    )

    if needs_arbitration:
        # Champs déjà existants sur PipelineState (app/graph/state.py),
        # prévus pour exactement ce signal (§2 étape 6 du doc de référence agent).
        state.status = "PAUSED"
        state.pending_action = "teacher_arbitration"
        state.arbitration_required = True
    else:
        state.pending_action = None

    state.updated_at = datetime.now(timezone.utc)
    return state
