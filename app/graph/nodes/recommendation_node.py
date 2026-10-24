"""
Nœud LangGraph — recommendation_node (câblage pipeline, Phase 2 du chantier
Recommendation_Agent).

Dernier nœud réel de la branche student_evaluation — appelé APRÈS
competency_assessment_node, une fois le profil de compétences (Niveau 2 +
Niveau 3) entièrement à jour pour cette soumission : recalculer les
recommandations sur un profil partiel donnerait des priorités fausses (une
compétence encore en cours d'agrégation pourrait sembler faible ou forte à
tort).

N'appelle JAMAIS CompetencyAssessmentService.assess_submission() (déjà fait
par competency_assessment_node juste avant, dans la même exécution de
run) — recalculer ici dupliquerait les StudentCompetencyObservation
persistées. Relit plutôt le profil déjà à jour via get_report() (agrégation
en LECTURE depuis l'historique, jamais un document dupliqué stocké
séparément — même principe que get_report lui-même, cf. son docstring).

Relaie vers RecommendationService.generate_recommendations (calcul déterministe
pur par Recommendation_Agent, aucun appel LLM) — persiste les nouvelles
RecommendedExercise ACTIVE et supersède les anciennes du même (student,
module, competency), cf. docstring service.

student_id/module_id lus directement depuis PipelineState (déjà renseignés
en student_evaluation, cf. state.py) — jamais redérivés via une requête
Submission/Exercise supplémentaire, contrairement à create_recommendation
(CRUD hérité) qui n'a pas cette information disponible.

Câblage Kafka en notification pure — APRÈS generate_recommendations()
réussi, publie recommendation-generated.v1 (RecommendationGeneratedPayload :
student_id/module_id/submission_id/recommendation_count). Strictement le
même pattern non-bloquant qu'evaluation_node.py pour evaluation-completed.v1
(décision actée : Kafka ne déclenche jamais rien dans ce pipeline synchrone
LangGraph) — publish_notification_best_effort absorbe tout échec de
publication (broker indisponible, etc.), jamais propagé, la génération/
persistance des recommandations doit toujours aboutir. Publié même quand
recommendation_count == 0 (aucune recommandation générée à ce passage est un
résultat légitime, cf. RecommendationAgent — pas une raison de sauter la
notification).

Câblage NotebookLM (§7, "Feedback Intelligent") — RETIRÉ d'ici (chantier
Feedback_Agent) : le déclenchement de generate_notebook_for_recommendations_
task est désormais dans feedback_node.py, APRÈS la génération du feedback
socratique réel, pour que la tâche Celery puisse recevoir feedback_text et
l'utiliser comme source principale du notebook (cf. docstring feedback_
node.py) — plus possible depuis ce nœud-ci, exécuté AVANT Feedback_Agent.
"""
import logging
import uuid
from datetime import datetime, timezone

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
from app.domain.repositories.student_notebook_repository import (
    SQLAlchemyStudentNotebookRepository,
)
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.schemas.event_schemas import RecommendationGeneratedPayload
from app.graph.state import PipelineState
from app.services.competency_assessment_service import CompetencyAssessmentService
from app.services.event_publisher_service import EventPublisherService, publish_notification_best_effort
from app.services.recommendation_service import RecommendationService

logger = logging.getLogger(__name__)


async def recommendation_node(state: PipelineState) -> PipelineState:
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
        report = await competency_service.get_report(student_id=student_id, module_id=module_id)

        recommendation_service = RecommendationService(
            recommendation_repo=SQLAlchemyRecommendedExerciseRepository(db),
            exercise_repo=SQLAlchemyExerciseRepository(db),
            submission_repo=SQLAlchemySubmissionRepository(db),
            evaluation_repo=SQLAlchemyEvaluationRepository(db),
            student_notebook_repo=SQLAlchemyStudentNotebookRepository(db),
            profile_repo=SQLAlchemyStudentCompetencyProfileRepository(db),
            competency_assessment_service=competency_service,
        )
        recommendations = await recommendation_service.generate_recommendations(
            student_id=student_id, module_id=module_id,
            competency_lines=report.lines, submission_id=submission_id,
        )

        events = EventPublisherService()
        await publish_notification_best_effort(
            events.publish_recommendation_generated(
                RecommendationGeneratedPayload(
                    student_id=student_id, module_id=module_id, submission_id=submission_id,
                    recommendation_count=len(recommendations),
                )
            )
        )

    state.recommended_exercise_ids = [str(r.exercise_id) for r in recommendations]
    state.updated_at = datetime.now(timezone.utc)
    return state
