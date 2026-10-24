"""
Nœud LangGraph — feedback_node (câblage pipeline, §7 cahier des charges
"Feedback Intelligent" — chantier Feedback_Agent).

Dernier nœud réel de la branche student_evaluation — appelé APRÈS
recommendation_node, une fois les recommandations de CETTE soumission déjà
persistées (submission_id posé sur chaque RecommendedExercise, cf.
RecommendedExerciseRepository.list_by_submission) : Feedback_Agent doit
pouvoir les mentionner en conclusion de son texte socratique.

Relaie vers FeedbackReportService.generate_feedback (SEUL appel LLM student-
facing de tout le pipeline, cf. docstring Feedback_Agent.py) — persiste le
StudentFeedbackReport. Précondition PENDING_ARBITRATION vérifiée par le
service lui-même (même principe défensif que competency_assessment_node/
evaluation_node — pas une deuxième fois ici), même si le graph ne peut de
toute façon jamais atteindre ce nœud pour une soumission en arbitrage
(cf. routing.py).

Câblage NotebookLM (§7, Partie 1/2 + Partie 2/2) — DÉPLACÉ ici depuis
recommendation_node.py (cf. son docstring, "Câblage NotebookLM" retiré) :
désormais déclenché APRÈS la génération du feedback socratique réel, pour
que generate_notebook_for_recommendations_task puisse recevoir feedback_
text et l'utiliser comme source PRINCIPALE (NotebookLMService retombe sur
_build_source_content si feedback_text est None — best-effort préservé,
cf. docstring NotebookLMService). Même enveloppe défensive que l'ancien
emplacement : un broker Celery injoignable ne doit jamais faire échouer ce
nœud.
"""
import logging
import uuid
from datetime import datetime, timezone

from app.agents.context import AgentExecutionContext
from app.core.database import get_db_context
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.recommended_exercise_repository import (
    SQLAlchemyRecommendedExerciseRepository,
)
from app.domain.repositories.student_competency_observation_repository import (
    SQLAlchemyStudentCompetencyObservationRepository,
)
from app.domain.repositories.student_competency_profile_repository import (
    SQLAlchemyStudentCompetencyProfileRepository,
)
from app.domain.repositories.student_feedback_report_repository import (
    SQLAlchemyStudentFeedbackReportRepository,
)
from app.domain.repositories.student_notebook_repository import (
    SQLAlchemyStudentNotebookRepository,
)
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.graph.state import PipelineState
from app.services.competency_assessment_service import CompetencyAssessmentService
from app.services.feedback_report_service import FeedbackReportService
from app.services.recommendation_service import RecommendationService
from app.tasks.notebooklm_tasks import generate_notebook_for_recommendations_task

logger = logging.getLogger(__name__)


def _serialize_competency_lines(lines) -> list[dict]:
    """StudentCompetencyReport.lines -> dicts JSON-safe pour la frontière Celery (même helper que recommendation_node.py)."""
    return [
        {
            "competency": line.competency.value,
            "mastery_level": str(line.mastery_level),
            "confidence_level": str(line.confidence_level),
            "is_persistent_weakness": line.is_persistent_weakness,
            "identified_difficulties": line.identified_difficulties,
            "weaknesses": line.weaknesses,
            "strengths": line.strengths,
        }
        for line in lines
    ]


def _serialize_recommendations(recommendations) -> list[dict]:
    """list[RecommendedExerciseRead] -> dicts JSON-safe pour la frontière Celery (même helper que recommendation_node.py)."""
    return [
        {
            "exercise_title": r.exercise_title,
            "competency_code": r.competency_code,
            "category": r.category,
            "reason": r.reason,
            "difficulty_level": r.difficulty_level,
        }
        for r in recommendations
    ]


async def feedback_node(state: PipelineState) -> PipelineState:
    submission_id = uuid.UUID(state.submission_id)
    student_id = uuid.UUID(state.student_id)
    module_id = uuid.UUID(state.module_id)

    async with get_db_context() as db:
        competency_service = CompetencyAssessmentService(
            evaluation_repo=SQLAlchemyEvaluationRepository(db),
            exercise_repo=SQLAlchemyExerciseRepository(db),
            submission_repo=SQLAlchemySubmissionRepository(db),
            observation_repo=SQLAlchemyStudentCompetencyObservationRepository(db),
            profile_repo=SQLAlchemyStudentCompetencyProfileRepository(db),
            module_repo=SQLAlchemyModuleRepository(db),
        )
        exercise_repo = SQLAlchemyExerciseRepository(db)
        recommendation_repo = SQLAlchemyRecommendedExerciseRepository(db)

        feedback_service = FeedbackReportService(
            feedback_report_repo=SQLAlchemyStudentFeedbackReportRepository(db),
            competency_assessment_service=competency_service,
            recommendation_repo=recommendation_repo,
            exercise_repo=exercise_repo,
            submission_repo=SQLAlchemySubmissionRepository(db),
        )

        context = AgentExecutionContext(
            trace_id=state.trace_id,
            flow_type=state.flow_type,
            submission_id=submission_id,
            exercise_id=None,
            db_session=db,
        )

        feedback_report = await feedback_service.generate_feedback(
            submission_id=submission_id, student_id=student_id, module_id=module_id, ctx=context,
        )

        # Câblage NotebookLM (déplacé depuis recommendation_node.py, cf.
        # docstring module) — relit le profil + les recommandations de
        # CETTE soumission plutôt que de les faire transiter depuis
        # recommendation_node (chaque nœud LangGraph ne partage d'état que
        # via PipelineState, jamais d'objets Python directs entre nœuds),
        # même principe déjà établi que recommendation_node relit le
        # profil via get_report() plutôt que de le recevoir en paramètre.
        report = await competency_service.get_report(student_id=student_id, module_id=module_id)
        recommendation_service = RecommendationService(
            recommendation_repo=recommendation_repo,
            exercise_repo=exercise_repo,
            submission_repo=SQLAlchemySubmissionRepository(db),
            evaluation_repo=SQLAlchemyEvaluationRepository(db),
            student_notebook_repo=SQLAlchemyStudentNotebookRepository(db),
            profile_repo=SQLAlchemyStudentCompetencyProfileRepository(db),
            competency_assessment_service=competency_service,
        )
        recommendations = await recommendation_service.list_by_submission(submission_id)

        try:
            generate_notebook_for_recommendations_task.delay(
                student_id=str(student_id), module_id=str(module_id),
                submission_id=str(submission_id) if submission_id else None,
                competency_lines_data=_serialize_competency_lines(report.lines),
                recommendations_data=_serialize_recommendations(recommendations),
                feedback_text=feedback_report.feedback_text,
            )
        except Exception:
            logger.warning(
                "Échec du déclenchement de la tâche NotebookLM pour student_id=%s "
                "— best-effort, pipeline non affecté.", student_id, exc_info=True,
            )

    state.updated_at = datetime.now(timezone.utc)
    return state
