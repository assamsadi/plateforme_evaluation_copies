"""
Nœud LangGraph — competency_assessment_node (câblage Partie 2/2, chantier C2PCT).

Dernier nœud réel de la branche student_evaluation — appelé APRÈS
evaluation_node, une fois SA boucle entièrement terminée (toutes les
questions de la soumission notées, cf. son docstring) : Competency_
Assessment_Agent.compute_submission_observations (Niveau 2, agrégation par
COPIE ENTIÈRE) serait calculé sur des données partielles si ce nœud
s'exécutait à l'intérieur de cette boucle plutôt qu'après — décision
positionnement vérifiée contre le code réel d'evaluation_node.py, pas
devinée (cf. rapport de câblage).

Relaie vers CompetencyAssessmentService.assess_submission (calcul
déterministe pur, aucun appel LLM, cf. Competency_Assessment_Agent) —
persiste StudentCompetencyObservation (Niveau 2) et met à jour le cache
StudentCompetencyProfile (Niveau 3). Précondition PENDING_ARBITRATION déjà
vérifiée par assess_submission lui-même — pas une deuxième fois ici, ce
nœud ne fait que relayer (même principe qu'evaluation_node, cf. son
docstring "pas une troisième fois ici"). Le graph lui-même ne peut de toute
façon jamais atteindre ce nœud pour une soumission en arbitrage
(route_after_contestation_verification route vers END dans ce cas).

Aucune pause n'existe pour une ClarificationRequest BLOCKING de Comparative_
Evaluation_Agent (gap documenté, hors périmètre — cf. evaluation_node.py) :
ce nœud agrège donc uniquement les compétences des questions RÉELLEMENT
notées par evaluation_node, jamais devinées pour les questions restées sans
Evaluation — comportement hérité, pas nouveau à ce câblage.

N'expose ni ne consomme le profil pour une quelconque recommandation —
ce nœud calcule et persiste, rien de plus (cf. mandat explicite de ce
ticket : rien construit ici pour un futur Feedback_Agent/Recommendation_
Agent).
"""
import uuid
from datetime import datetime, timezone

from app.core.database import get_db_context
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.student_competency_observation_repository import (
    SQLAlchemyStudentCompetencyObservationRepository,
)
from app.domain.repositories.student_competency_profile_repository import (
    SQLAlchemyStudentCompetencyProfileRepository,
)
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.graph.state import PipelineState
from app.services.competency_assessment_service import CompetencyAssessmentService


async def competency_assessment_node(state: PipelineState) -> PipelineState:
    submission_id = uuid.UUID(state.submission_id)

    async with get_db_context() as db:
        service = CompetencyAssessmentService(
            evaluation_repo=SQLAlchemyEvaluationRepository(db),
            exercise_repo=SQLAlchemyExerciseRepository(db),
            submission_repo=SQLAlchemySubmissionRepository(db),
            observation_repo=SQLAlchemyStudentCompetencyObservationRepository(db),
            profile_repo=SQLAlchemyStudentCompetencyProfileRepository(db),
            module_repo=SQLAlchemyModuleRepository(db),
        )
        await service.assess_submission(submission_id)

    state.updated_at = datetime.now(timezone.utc)
    return state
