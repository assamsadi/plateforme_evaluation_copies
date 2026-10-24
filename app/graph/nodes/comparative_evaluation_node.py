"""
Nœud LangGraph — comparative_evaluation_node (câblage workflow, Priorité 1).

Appelé après contestation_verification_node dans la branche student_evaluation,
UNIQUEMENT si aucune contestation ne nécessite un arbitrage professeur
(cf. route_after_contestation_verification, routing.py — state.arbitration_
required, déjà posé par contestation_verification_node, jamais exploité
avant ce câblage).

Boucle sur les Question de l'exercice (une question sans Bareme, ou sans
aucun texte de réponse étudiante, est sautée — rien à évaluer, jamais un
verdict inventé) et appelle Comparative_Evaluation_Agent question par
question, construisant EvaluationRequest à partir de ce qui est déjà
persisté :
  - criteria : depuis Bareme.criteria (JSON, Extraction_Verification_Agent).
  - student_response : depuis ExtractionCorrection (submission_id,
    question_id), précédence verified_content > human_correction >
    prediction_ocr (cf. docstring ExtractionCorrection — verified_content
    porte la vérité tranchée, human_correction la réclamation originale si
    aucune contestation ne l'a supplantée, prediction_ocr le repli brut).
  - reference_solution_text/reasoning_graph_steps : depuis la SolutionVariant
    de référence (is_reference=True) + ses ReasoningStep NON supersédés
    (superseded_by is None — get_reasoning_steps_ordered() ne filtre pas
    lui-même, cf. reasoning_graph_service.py pour le même principe de
    versionnement). step_ref synthétisé depuis l'UUID de la ligne
    (ReasoningStep n'a pas de colonne step_ref stable — connu, cf. diagnostic
    Comparative_Evaluation_Agent). canonical_form lu défensivement depuis
    extraction_signals — PAS garanti présent (reasoning_graph_service.py
    persiste une nouvelle ligne dont extraction_signals ne porte que
    competency_weights/is_core_step/downstream_step_refs/source_span ;
    trou de pipeline déjà documenté, hors périmètre de ce ticket — câblage
    uniquement, ne touche à aucune logique interne déjà validée).
  - mandated_method/covered_subquestions : Question.mandated_method/
    covered_subquestions (Phase 5A / Phase 2/4, persistés par
    extraction_verification_service.py).

Précondition PENDING_ARBITRATION vérifiée ICI en défense en profondeur, en
plus de la vérification déjà faite au niveau service (EvaluationService.
record_evaluation, chantier C2PCT Phase 4) : ce nœud ne passe PAS par
EvaluationService (Comparative_Evaluation_Agent n'a aucune persistance
propre), donc la vérification de service seule ne suffit pas à couvrir ce
point d'entrée.

Ne persiste RIEN directement (Comparative_Evaluation_Agent n'a toujours
aucun service de persistance dédié, cf. diagnostic) — transmet une
PROJECTION MINIMALE (bareme_id/bareme_points/covered_subquestions/
subquestion_judgments/decision_entries/consigne_respected) via
state.comparison_results, consommée par evaluation_node juste après. Le
détail complet du rapport (condition_evaluations, clarifications,
decision_logs) n'est PAS conservé au-delà de ce nœud — limite assumée,
construire une persistance dédiée dépasse le mandat "câblage" de ce ticket.

Câblage copy_report (§0, ticket dédié) — decision_entries (produites par
Comparative_Evaluation_Agent._build_decision_entries, cf. DecisionEntry)
et consigne_respected (agrégé ici depuis CriterionEvaluationResult,
jusqu'ici jamais transmis au-delà de l'agent) transitent désormais par
cette projection pour permettre à evaluation_node d'assembler un
QuestionReport lisible via Pedagogical_Evaluation_Agent.build_question_
report.

Une question dont AU MOINS UN critère porte une ClarificationRequest
BLOCKING est marquée "blocking": true dans sa projection — evaluation_node
l'exclut alors de la notation (jamais un verdict tranché en zone
d'incertitude, §0), quelle que soit la sous-nature du blocage.

Calcul de note classique (ticket dédié, suite directe du chantier
general_rules) — "criteria" (id/label/points/correction_mode/disqualifying,
lu directement depuis bareme.criteria) et "criterion_results"
(criterion_id/score_ratio/is_satisfied/justification, depuis
report.criterion_results) transitent désormais eux aussi par cette
projection, à joindre par id/criterion_id côté evaluation_node.py pour
Pedagogical_Evaluation_Agent.evaluate_question_classic — le mécanisme de
notation classique (barème à critères, jamais transformé en points nulle
part jusqu'ici malgré des verdicts déjà correctement calculés critère par
critère).

Câblage pause HITL (correctif découvertes annexes, priorité 1, ÉTENDU par
le correctif AMBIGUOUS_COHERENCE) : DEUX sous-cas de BLOCKING existent en
réalité (MULTIPLE_DISTINCT_ANSWERS uniquement, cf. Comparative_Evaluation_
Agent), TOUS DEUX désormais résolvables et TOUS DEUX déclenchent la pause
réelle du graph (state.blocking_clarification_count, cf. pipeline_graph.py/
routing.py — même mécanisme que extraction_verification_node/
reasoning_graph_node, jamais un nouveau inventé) —
  1. COHERENT + aucun match RAG ("réponse alternative inédite") : persistée
     comme ReasoningClarificationRequest(comparative_clarification_kind=
     ALTERNATIVE_ANSWER), résolvable via POST /clarifications/{id}/
     validate-alternative-answer.
  2. AMBIGUOUS_COHERENCE ("effort réel ou hors-sujet ?") : persistée comme
     ReasoningClarificationRequest(comparative_clarification_kind=
     COHERENCE_AMBIGUITY), résolvable via POST /clarifications/{id}/
     resolve-coherence-ambiguity (correctif dédié — "coherent"/"incoherent"
     réinjectés à la reprise via EvaluationRequest.coherence_ambiguity_
     resolutions, bypass du SEUL appel LLM de classification, cf.
     Comparative_Evaluation_Agent._eval_multiple_distinct_answers ; la
     suite de la méthode, y compris la recherche RAG, tourne ensuite
     inchangée — résoudre "coherent" sans match RAG derrière RE-DÉCLENCHE
     le sous-cas 1 pour ce même critère, comportement attendu de la
     branche réutilisée, pas un bug).

Dans les deux cas, dédupliqué contre les clarifications déjà PENDING pour
cet exercice (list_pending_blocking_by_exercise, clé (question_id,
criterion_id) commune aux deux sous-types) : une reprise partielle (le prof
résout une clarification mais pas toutes) re-exécute ce nœud (cf.
CLARIFICATION_RESOLUTION_ROUTING_TABLE, resume sur lui-même) et ne doit
jamais recréer de doublon pour celles encore en attente.

Portée d'une résolution — related_entity_id=question.id (PAS submission_id) :
une résolution (des deux sous-types) s'applique à TOUTES les soumissions
futures pour cette question/ce critère, pas seulement celle qui l'a
déclenchée. Caractéristique HÉRITÉE du mécanisme alternative_answer déjà
existant (RAG cross-soumissions par construction), gardée identique pour
la cohérence — pas une portée nouvellement introduite ici.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.agents.comparative_evaluation_exceptions import UnknownCorrectionModeError
from app.agents.Comparative_Evaluation_Agent import (
    CoherenceStatus,
    ComparativeEvaluationAgent,
    CriterionEvaluationInput,
    EvaluationRequest,
    StudentResponseInput,
)
from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import ClarificationSeverity, CorrectionMode
from app.core.database import get_db_context
from app.core.exceptions import ExerciseNotFoundError, SubmissionNotFoundError, SubmissionPendingArbitrationError
from app.domain.models.assessment.reasoning_clarification_request import ComparativeClarificationKind
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.extraction_correction_repository import (
    SQLAlchemyExtractionCorrectionRepository,
)
from app.domain.repositories.reasoning_clarification_request_repository import (
    SQLAlchemyReasoningClarificationRequestRepository,
)
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.graph.state import PipelineState


def _resolve_student_text(correction) -> str:
    """
    Précédence documentée sur ExtractionCorrection : verified_content porte
    la vérité tranchée (post-contestation), human_correction la réclamation
    de l'étudiant si aucune contestation ne l'a supplantée, prediction_ocr
    le repli brut OCR.
    """
    return correction.verified_content or correction.human_correction or correction.prediction_ocr or ""


async def comparative_evaluation_node(state: PipelineState) -> PipelineState:
    submission_id = uuid.UUID(state.submission_id)
    exercise_id = uuid.UUID(state.exercise_id)

    async with get_db_context() as db:
        submission_repo = SQLAlchemySubmissionRepository(db)
        exercise_repo = SQLAlchemyExerciseRepository(db)
        correction_repo = SQLAlchemyExtractionCorrectionRepository(db)
        variant_repo = SQLAlchemySolutionVariantRepository(db)
        clarification_repo = SQLAlchemyReasoningClarificationRequestRepository(db)

        submission = await submission_repo.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)

        # Défense en profondeur (cf. docstring module) — la vérification de
        # EvaluationService.record_evaluation ne couvre pas ce point d'entrée.
        if submission.status == SubmissionStatus.PENDING_ARBITRATION:
            raise SubmissionPendingArbitrationError(submission_id)

        exercise = await exercise_repo.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        corrections = await correction_repo.get_by_submission_id(submission_id)
        corrections_by_question: dict[uuid.UUID, list] = {}
        for correction in corrections:
            if correction.question_id is not None:
                corrections_by_question.setdefault(correction.question_id, []).append(correction)

        # Câblage pause HITL — clarifications déjà PENDING pour cet exercice
        # (toutes sévérités/origines confondues, cf. list_pending_blocking_
        # by_exercise), pour dédupliquer une reprise partielle (cf. docstring
        # module). Clé = (submission_id, question_id, criterion_id).
        #
        # Bug réel corrigé (2026-09-06, ajout de submission_id) : la clé
        # était (question_id, criterion_id) SEULE — "portée cross-soumissions
        # héritée" documentée comme limitation acceptée jusqu'ici. Deux
        # étudiants heurtant le même critère de la même question ne
        # produisaient alors qu'UNE SEULE ligne PENDING partagée : le second
        # à passer ici la voyait déjà "already_pending" et ne créait jamais
        # la sienne — sa propre clarification disparaissait silencieusement,
        # jamais posée nulle part. submission_id désormais disponible sur le
        # modèle (cf. son docstring) rend cette dédup correctement scoping
        # par soumission, plus seulement par exercice.
        already_pending = {
            (r.submission_id, r.related_entity_id, r.criterion_id)
            for r in await clarification_repo.list_pending_blocking_by_exercise(exercise_id)
            if r.related_entity_type == "Question" and r.criterion_id is not None
        }
        resolvable_blocking_count = 0

        # Correctif AMBIGUOUS_COHERENCE — relu à CHAQUE exécution (pas
        # seulement à la reprise, cf. docstring module : portée cross-
        # soumissions héritée) : dict[question_id][criterion_id] -> "coherent"
        # | "incoherent", injecté dans EvaluationRequest.coherence_ambiguity_
        # resolutions ci-dessous.
        resolutions_by_question: dict[uuid.UUID, dict[str, str]] = {}
        for r in await clarification_repo.list_resolved_coherence_ambiguities_by_exercise(exercise_id):
            if r.criterion_id is None or r.resolved_as_coherent is None:
                continue
            resolutions_by_question.setdefault(r.related_entity_id, {})[r.criterion_id] = (
                "coherent" if r.resolved_as_coherent else "incoherent"
            )

        agent = ComparativeEvaluationAgent()
        context = AgentExecutionContext(
            trace_id=state.trace_id,
            flow_type=state.flow_type,
            submission_id=submission_id,
            exercise_id=exercise_id,
            db_session=db,
        )

        projections: list[dict] = []

        for question in sorted(exercise.questions, key=lambda q: q.order):
            bareme = question.bareme
            # Bug réel corrigé (2026-09-06) : ce garde ne vérifiait QUE le
            # barème classique (q.bareme) — un exercice C2PCT natif (barème
            # TOUJOURS None par conception, cf. commentaire covered_
            # subquestions_for_scoring plus bas) faisait sauter la question
            # ENTIÈREMENT ici, avant même d'atteindre la logique qui sait
            # pourtant déjà gérer ce cas. Résultat constaté en test réel :
            # 0 evaluations, 0 log de décision, quelle que soit la qualité
            # du rattachement des blocs — même bug déjà corrigé une fois
            # dans ExerciseService._check_completeness() (2026-09-03), pas
            # répercuté ici. Symétrique exact de cette condition.
            if bareme is None and not question.subquestion_points:
                continue  # rien à évaluer, ni classique ni C2PCT natif

            question_corrections = corrections_by_question.get(question.id, [])
            student_answer_text = "\n".join(
                t for t in (_resolve_student_text(c) for c in question_corrections) if t
            ).strip()
            if not student_answer_text:
                continue  # aucune réponse étudiante pour cette question — rien à juger

            # bareme peut être None ici (question C2PCT native, cf. garde
            # ci-dessus) — aucun critère classique à juger dans ce cas,
            # criteria=[] : Comparative_Evaluation_Agent.execute() gère déjà
            # une liste vide (la boucle sur request.criteria ne produit
            # simplement aucun criterion_results), _judge_subquestions()
            # tourne ensuite indépendamment sur covered_subquestions_for_
            # scoring, seul signal dont a besoin le barème C2PCT natif.
            criteria = [
                CriterionEvaluationInput(
                    criterion_id=c["id"],
                    label=c["label"],
                    points=Decimal(str(c["points"])),
                    # .get() avec repli (test réel 2026-08-31) : un barème
                    # saisi manuellement (set_bareme_for_question) pouvait
                    # jusqu'ici ne jamais porter correction_mode du tout —
                    # KeyError garanti ici sinon. CRITERIA_BASED = même repli
                    # que le mécanisme d'extraction pour tout cas ambigu.
                    correction_mode=c.get("correction_mode", "criteria_based"),
                    verifiable_conditions=c.get("verifiable_conditions") or [],
                    rubric_levels=c.get("rubric_levels") or [],
                    expected_steps=c.get("expected_steps") or [],
                    test_cases=c.get("test_cases") or [],
                    reference_code=c.get("reference_code"),
                    expected_complexity=c.get("expected_complexity"),
                )
                for c in (bareme.criteria if bareme is not None else [])
            ]

            variants = await variant_repo.list_by_question(question.id)
            reference_variant = next((v for v in variants if v.is_reference), None)
            reference_solution_text: str | None = None
            reasoning_graph_steps: list[dict] = []
            if reference_variant is not None:
                reference_solution_text = reference_variant.content
                all_steps = await variant_repo.get_reasoning_steps_ordered(reference_variant.id)
                # Non supersédées uniquement — get_reasoning_steps_ordered()
                # ne filtre pas lui-même (cf. docstring module).
                active_steps = [s for s in all_steps if s.superseded_by is None]
                reasoning_graph_steps = [
                    {
                        "step_ref": str(s.id),
                        "order": s.order,
                        "step_type": s.step_type.value,
                        "description": s.description,
                        "formula": s.formula,
                        "canonical_form": (s.extraction_signals or {}).get("canonical_form"),
                    }
                    for s in active_steps
                ]

            try:
                # Calcul de note classique (ticket dédié) — covered_
                # subquestions n'est transmis à Comparative_Evaluation_Agent
                # QUE si cette question est réellement notée en C2PCT natif
                # (subquestion_points renseigné, même discriminant que le
                # routage evaluation_node.py). Sinon (mécanisme classique),
                # _judge_subquestions serait exécuté pour RIEN : ses
                # subquestion_judgments/decision_entries ne sont jamais lus
                # par evaluate_question_classic/build_question_report_classic
                # — un vrai coût LLM (jugement narratif batché + parfois 15
                # sous-questions) jeté à la notation, constaté sur un run réel
                # (barème classique à 4 critères, covered_subquestions=15/15
                # malgré tout, cf. Extraction_Verification_Agent qui extrait
                # ce signal de couverture sémantique indépendamment du
                # mécanisme de barème réellement utilisé). question.covered_
                # subquestions lui-même n'est PAS modifié (juste ce qui
                # transite dans CETTE requête).
                covered_subquestions_for_scoring = (
                    question.covered_subquestions or []
                ) if question.subquestion_points else []

                request = EvaluationRequest(
                    question_id=question.id,
                    question_statement=question.statement,
                    student_response=StudentResponseInput(
                        question_id=question.id,
                        student_answer_text=student_answer_text,
                    ),
                    criteria=criteria,
                    reference_solution_text=reference_solution_text,
                    reasoning_graph_steps=reasoning_graph_steps,
                    mandated_method=question.mandated_method,
                    covered_subquestions=covered_subquestions_for_scoring,
                    coherence_ambiguity_resolutions=resolutions_by_question.get(question.id, {}),
                    general_rules=question.general_rules or [],
                )
                report = await agent.execute(request, context)
            except UnknownCorrectionModeError:
                # Barème mal formé (mode hors des 7 valeurs) : question sautée,
                # jamais une exception qui ferait échouer tout l'exercice.
                continue

            blocking = any(
                cr.clarification_request is not None
                and cr.clarification_request.severity == ClarificationSeverity.BLOCKING
                for cr in report.criterion_results
            )

            # Câblage HITL indexation RAG (Priorité 1) + correctif
            # AMBIGUOUS_COHERENCE — cf. docstring module : les DEUX sous-cas
            # MULTIPLE_DISTINCT_ANSWERS sont désormais persistés, distingués
            # par comparative_clarification_kind (seul discriminant fiable,
            # les deux partagent related_entity_type/criterion_id).
            for cr in report.criterion_results:
                if cr.correction_mode != CorrectionMode.MULTIPLE_DISTINCT_ANSWERS or cr.clarification_request is None:
                    continue

                if cr.coherence_status == CoherenceStatus.COHERENT:
                    kind = ComparativeClarificationKind.ALTERNATIVE_ANSWER
                elif cr.coherence_status == CoherenceStatus.AMBIGUOUS_COHERENCE:
                    kind = ComparativeClarificationKind.COHERENCE_AMBIGUITY
                else:
                    continue  # INCOHERENT ne produit jamais de clarification (cf. agent)

                # Compte pour la pause qu'elle soit nouvellement créée ici ou
                # déjà PENDING d'une exécution précédente (reprise partielle,
                # jamais un doublon créé).
                resolvable_blocking_count += 1
                if (submission_id, question.id, cr.criterion_id) not in already_pending:
                    await clarification_repo.create(
                        agent_question=cr.clarification_request.agent_question,
                        unclear_content=student_answer_text,
                        related_entity_type="Question",
                        related_entity_id=question.id,
                        proposed_answer=cr.clarification_request.proposed_answer,
                        severity=cr.clarification_request.severity,
                        criterion_id=cr.criterion_id,
                        comparative_clarification_kind=kind,
                        submission_id=submission_id,
                    )

            # Câblage copy_report — consigne_respected (SOLUTION_WORKED
            # uniquement, cf. CriterionEvaluationResult) agrégé au niveau
            # question : False si AU MOINS UN critère de cette question
            # signale le non-respect de la méthode imposée, True si tous les
            # critères applicables la respectent, None si mandated_method
            # n'était pas renseigné pour cette question (rien à vérifier,
            # jamais déduit). Champ jusqu'ici jamais transmis au-delà de
            # l'agent (confirmé) — simple relais, aucun recalcul.
            consigne_flags = [
                cr.consigne_respected for cr in report.criterion_results
                if cr.consigne_respected is not None
            ]
            consigne_respected = all(consigne_flags) if consigne_flags else None

            projections.append({
                "question_id": str(question.id),
                # bareme peut être None (question C2PCT native) — jamais
                # d'AttributeError ici, cf. garde plus haut sur ce même
                # bareme. bareme_points reste TOUJOURS un nombre réel (lu
                # inconditionnellement par evaluation_node.py AVANT même son
                # propre branchement classique/natif) : pour le cas natif,
                # c'est la somme des points par sous-question (question.
                # subquestion_points), jamais None — sinon Decimal(None)
                # plante evaluation_node.py pour CETTE question précise.
                "bareme_id": str(bareme.id) if bareme is not None else None,
                "bareme_points": (
                    str(bareme.points) if bareme is not None
                    else str(sum(Decimal(v) for v in question.subquestion_points.values()))
                ),
                "covered_subquestions": list(question.covered_subquestions or []),
                # Chantier barème C2PCT natif (Cas 0) — relayé tel quel
                # (déjà sérialisé en texte par set_question_subquestion_points,
                # cf. exercise_repository.py), jamais recalculé ici. Ne
                # transite JAMAIS par Comparative_Evaluation_Agent/
                # EvaluationRequest (qui ne juge que des ratios, jamais des
                # points) — relais direct Question -> projection ->
                # evaluation_node.py -> Pedagogical_Evaluation_Agent.
                "subquestion_points": dict(question.subquestion_points) if question.subquestion_points else None,
                "subquestion_judgments": [
                    {
                        "subquestion_id": j.subquestion_id,
                        "addressed": j.addressed,
                        "is_correct": j.is_correct,
                        "source": j.source,
                        # Chantier notation graduée (Partie 2/3) — sans ce
                        # champ, Pedagogical_Evaluation_Agent.evaluate_
                        # question() (relit via evaluation_node.py de
                        # l'autre côté de cette frontière JSON) retomberait
                        # sur completion_ratio=None partout -> taux de
                        # réussite à 0.0 pour toute la question (constaté).
                        "completion_ratio": str(j.completion_ratio) if j.completion_ratio is not None else None,
                    }
                    for j in report.subquestion_judgments
                ],
                "blocking": blocking,
                # Câblage copy_report (§0) — relayé tel quel, construit par
                # Comparative_Evaluation_Agent (cf. DecisionEntry.to_dict).
                "decision_entries": [e.to_dict() for e in report.decision_entries],
                "consigne_respected": consigne_respected,
                # Calcul de note classique — lu DIRECTEMENT depuis
                # bareme.criteria (même source que criteria ci-dessus),
                # jamais via CriterionEvaluationInput/CriterionEvaluationResult
                # (Comparative_Evaluation_Agent n'a structurellement pas
                # besoin de disqualifying pour juger un critère, cf. le
                # précédent déjà établi pour subquestion_points ci-dessus).
                # Jointe à criterion_results par "id"/criterion_id côté
                # evaluation_node.py pour le calcul de note classique.
                "criteria": [
                    {
                        "id": c["id"],
                        "label": c["label"],
                        "points": str(c["points"]),
                        # Même repli que ci-dessus (test réel 2026-08-31).
                        "correction_mode": c.get("correction_mode", "criteria_based"),
                        "disqualifying": bool(c.get("disqualifying", False)),
                    }
                    for c in (bareme.criteria if bareme is not None else [])
                ],
                "criterion_results": [
                    {
                        "criterion_id": cr.criterion_id,
                        "score_ratio": cr.score_ratio,
                        "is_satisfied": cr.is_satisfied,
                        "justification": cr.justification,
                    }
                    for cr in report.criterion_results
                ],
            })

    state.comparison_results = projections

    # Câblage pause HITL (correctif découvertes annexes, priorité 1) — même
    # pattern que extraction_verification_node/reasoning_graph_node : le
    # nœud producteur pose paused_at_node avant que l'edge conditionnelle
    # (route_after_comparative_evaluation, routing.py) ne route vers
    # await_clarification_resolution_node.
    state.blocking_clarification_count = resolvable_blocking_count
    if resolvable_blocking_count > 0:
        state.status = "PAUSED"
        state.pending_action = "clarification_review"
        state.paused_at_node = "comparative_evaluation_node"
    else:
        state.status = "RUNNING"
        state.pending_action = None
        state.paused_at_node = None

    state.updated_at = datetime.now(timezone.utc)
    return state
