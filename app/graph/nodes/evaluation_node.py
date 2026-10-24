"""
Nœud LangGraph — evaluation_node (câblage workflow, Priorité 1).

Appelé après comparative_evaluation_node, suivi désormais de competency_
assessment_node (câblage Partie 2/2, chantier C2PCT — jamais À L'INTÉRIEUR
de la boucle ci-dessous : Competency_Assessment_Agent a besoin de TOUTES
les questions notées pour son agrégation Niveau 2, cf. docstring
competency_assessment_node.py). Reconstruit QuestionEvaluationInput par
question depuis la projection minimale posée dans state.comparison_results,
appelle Pedagogical_Evaluation_Agent (calcul déterministe pur, aucun appel
LLM) puis EvaluationService.record_question_score (persistance réelle,
Evaluation + une EvaluationCriteria par compétence — chantier C2PCT Phase 4).

Une question dont la projection porte "blocking": true (au moins une
ClarificationRequest BLOCKING produite par Comparative_Evaluation_Agent,
cf. comparative_evaluation_node) est EXCLUE de la notation — aucune note
n'est persistée pour elle. Jamais un verdict tranché en zone d'incertitude
(§0) ; construire ici la reprise HITL correspondante dépasse le mandat
"câblage" de ce ticket (aucun mécanisme de persistance/pause n'existe pour
les ClarificationRequest de Comparative_Evaluation_Agent, cf. docstring
comparative_evaluation_node).

La précondition PENDING_ARBITRATION est déjà vérifiée deux fois en amont
(comparative_evaluation_node, EvaluationService.record_evaluation appelé
ci-dessous) — pas une troisième fois ici, ce nœud ne fait que relayer.

Câblage copy_report — reconstruit decision_entries/consigne_respected
depuis la projection (posés par comparative_evaluation_node), appelle
Pedagogical_Evaluation_Agent.build_question_report (assemblage pur, aucun
recalcul) et transmet le QuestionReport résultant à record_question_score
pour persistance (Evaluation.copy_report_detail). Une question "blocking"
(cf. ci-dessus) n'a ni note ni QuestionReport — absente du CopyReport final
(limite déjà documentée, pas nouvelle à ce câblage).

Câblage Kafka en notification pure (correctif découvertes annexes) — APRÈS
chaque record_question_score() réussi, publie evaluation-completed.v1
(EvaluationCompletedPayload : submission_id/question_id/evaluation_id/score,
lus directement sur l'EvaluationRead retourné, jamais recalculés). Décision
actée : Kafka ne déclenche jamais rien dans ce pipeline synchrone LangGraph
— publish_notification_best_effort (event_publisher_service.py) absorbe
tout échec de publication (broker indisponible, etc.), jamais propagé, la
boucle de notation continue normalement. Aucun consumer construit pour ce
topic ici (hors mandat, cf. plan).

Calcul de note classique (ticket dédié) — routage par question, cf.
Pedagogical_Evaluation_Agent (discriminant validé : présence de
subquestion_points POUR CETTE question, jamais covered_subquestions) :
non vide/non-None -> QuestionEvaluationInput/evaluate_question() (branche
déjà existante, inchangée) ; sinon -> ClassicQuestionEvaluationInput/
evaluate_question_classic() (nouvelle branche, barème à critères). Les deux
branches convergent sur le même record_question_score() (persistance
UNIQUE, cf. docstring evaluation_service.py).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.agents.Comparative_Evaluation_Agent import DecisionEntry, SubquestionJudgment
from app.agents.Pedagogical_Evaluation_Agent import (
    ClassicCriterionJoinedInput,
    ClassicQuestionEvaluationInput,
    PedagogicalEvaluationAgent,
    QuestionEvaluationInput,
)
from app.core.database import get_db_context
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.schemas.event_schemas import EvaluationCompletedPayload
from app.graph.state import PipelineState
from app.services.event_publisher_service import EventPublisherService, publish_notification_best_effort
from app.services.evaluation_service import EvaluationService


async def evaluation_node(state: PipelineState) -> PipelineState:
    submission_id = uuid.UUID(state.submission_id)
    projections = state.comparison_results or []

    async with get_db_context() as db:
        service = EvaluationService(
            evaluation_repo=SQLAlchemyEvaluationRepository(db),
            submission_repo=SQLAlchemySubmissionRepository(db),
            exercise_repo=SQLAlchemyExerciseRepository(db),
            user_repo=SQLAlchemyUserRepository(db),
        )
        agent = PedagogicalEvaluationAgent()
        events = EventPublisherService()

        for proj in projections:
            if proj.get("blocking"):
                continue  # cf. docstring module — jamais un verdict tranché en zone d'incertitude

            question_id = uuid.UUID(proj["question_id"])
            bareme_points = Decimal(proj["bareme_points"])
            raw_subquestion_points = proj.get("subquestion_points")

            # Discriminant de routage (calcul de note classique, ticket
            # dédié) — présence de subquestion_points POUR CETTE question
            # précise, jamais covered_subquestions (extrait pour TOUTE
            # question, signal de couverture sémantique indépendant du
            # mécanisme de barème réellement utilisé, cf. docstring
            # comparative_evaluation_node.py). Non vide/non-None -> mécanisme
            # C2PCT natif (inchangé, branche déjà existante) ; sinon ->
            # mécanisme classique (barème à critères, nouvelle branche).
            if raw_subquestion_points:
                judgments = [
                    SubquestionJudgment(
                        subquestion_id=j["subquestion_id"],
                        addressed=j["addressed"],
                        is_correct=j["is_correct"],
                        evidence_reference=None,
                        source=j["source"],
                        # Chantier notation graduée (Partie 2/3) — requis par
                        # Pedagogical_Evaluation_Agent.evaluate_question()
                        # (success_rate = somme des completion_ratio), cf.
                        # docstring comparative_evaluation_node.py.
                        completion_ratio=(
                            Decimal(j["completion_ratio"]) if j.get("completion_ratio") is not None else None
                        ),
                    )
                    for j in proj["subquestion_judgments"]
                ]
                question_input = QuestionEvaluationInput(
                    question_id=question_id,
                    bareme_points=bareme_points,
                    covered_subquestions=proj["covered_subquestions"],
                    subquestion_judgments=judgments,
                    # Chantier barème C2PCT natif (Cas 0) — cf. docstring
                    # comparative_evaluation_node.py, jamais transité par
                    # Comparative_Evaluation_Agent.
                    subquestion_points={sq_id: Decimal(v) for sq_id, v in raw_subquestion_points.items()},
                )
                result = agent.evaluate_question(question_input)

                decision_entries = [
                    DecisionEntry.from_dict(e) for e in proj.get("decision_entries", [])
                ]
                question_report = agent.build_question_report(
                    question_id=question_id,
                    bareme_points=bareme_points,
                    score_result=result,
                    decision_entries=decision_entries,
                    consigne_respected=proj.get("consigne_respected"),
                )
            else:
                # Jointure criteria (bareme.criteria) x criterion_results
                # (verdicts Comparative_Evaluation_Agent) par id/criterion_id
                # — pur assemblage de données, cf. docstring
                # ClassicCriterionJoinedInput. KeyError volontairement non
                # rattrapé : un criterion_id de bareme.criteria sans verdict
                # correspondant serait une anomalie de câblage amont, jamais
                # un critère silencieusement ignoré.
                results_by_id = {r["criterion_id"]: r for r in proj.get("criterion_results", [])}
                classic_criteria = [
                    ClassicCriterionJoinedInput(
                        criterion_id=c["id"],
                        label=c["label"],
                        # .get() avec repli (test réel 2026-08-31) : une
                        # projection persistée AVANT ce correctif peut encore
                        # manquer ce champ (barème saisi manuellement, jamais
                        # de correction_mode avant set_bareme_for_question).
                        correction_mode=c.get("correction_mode", "criteria_based"),
                        points=Decimal(c["points"]),
                        disqualifying=c["disqualifying"],
                        score_ratio=results_by_id[c["id"]]["score_ratio"],
                        is_satisfied=results_by_id[c["id"]]["is_satisfied"],
                        justification=results_by_id[c["id"]]["justification"],
                    )
                    for c in proj.get("criteria", [])
                ]
                classic_input = ClassicQuestionEvaluationInput(
                    question_id=question_id,
                    criteria=classic_criteria,
                )
                result = agent.evaluate_question_classic(classic_input)
                question_report = agent.build_question_report_classic(
                    question_id=question_id,
                    bareme_points=bareme_points,
                    score_result=result,
                    consigne_respected=proj.get("consigne_respected"),
                )

            evaluation_read = await service.record_question_score(
                submission_id=submission_id,
                # Bug réel corrigé (2026-09-06, test réel — question C2PCT-
                # native sans ligne Bareme) : uuid.UUID(None) plantait ici
                # dès que comparative_evaluation_node posait bareme_id=None
                # (cf. son correctif "subquestion_points"). EvaluationCriteria.
                # bareme_id est désormais nullable pour ce cas exact.
                bareme_id=uuid.UUID(proj["bareme_id"]) if proj["bareme_id"] is not None else None,
                result=result,
                question_report=question_report,
            )

            await publish_notification_best_effort(
                events.publish_evaluation_completed(
                    EvaluationCompletedPayload(
                        submission_id=evaluation_read.submission_id,
                        question_id=evaluation_read.question_id,
                        evaluation_id=evaluation_read.id,
                        score=evaluation_read.score,
                    )
                )
            )

    state.status = "RUNNING"
    state.updated_at = datetime.now(timezone.utc)
    return state
