"""
Service — orchestrateur d'Extraction_Verification_Agent (Phase 6/6).

Contrairement à document_structuring_service.py (qui reçoit un rapport déjà
produit), ce service appelle lui-même l'agent — même principe que
contestation_verification_service.py : la précondition DRAFT doit être
vérifiée AVANT tout appel LLM, en défense en profondeur (l'agent la
revérifie aussi, cf. ExerciseAlreadyPublishedError).

Persiste, par question, dans l'ordre (l'agent calcule, le service persiste,
même principe que tous les services précédents) :
  1. Le Bareme (si produit) — validation_status=CONFIRMED (Cas 1) ou
     PENDING_REVIEW (Cas 2, répartition proposée jamais appliquée
     automatiquement).
  2. La SolutionVariant TEACHER_ORIGINAL (is_reference=True) + son graphe de
     ReasoningStep, via create_with_reasoning_graph — SEULEMENT si la
     décomposition a abouti (decomposition_error is None). Une liste steps
     vide EST un résultat valide (Phase 5B, correction en code pur) : la
     variante est créée sans étape, jamais un graphe fabriqué. Les signaux
     Phases 3a/3b sans colonne dédiée (anomaly_detected, case_group_id,
     recurrence_role, canonical_form, dimensional_check_result,
     numeric_tolerance, criticality, source_span) sont regroupés dans
     ReasoningStep.extraction_signals (JSONB), None si l'étape n'en a
     produit aucun.
     difficulty_level : l'agent n'évalue jamais la difficulté d'une
     correction professeur (hors périmètre de toutes les phases 1-5) —
     INTERMEDIAIRE par défaut, valeur neutre en attendant qu'un futur agent
     (ou le professeur) l'ajuste. Signalé comme hypothèse, pas une vérité
     calculée.
  3. mandated_method sur la Question (Phase 5A), toujours écrit (y compris
     None — idempotent, la colonne démarre déjà à None).
  3bis. covered_subquestions sur la Question (Phase 2/4) — même principe que
     mandated_method, toujours écrit (y compris liste vide). Ajouté lors du
     câblage de comparative_evaluation_node (workflow) : sans cette
     persistance, aucune sous-question n'était jamais récupérable après
     coup, ce qui aurait rendu tout le calcul par compétence de
     Pedagogical_Evaluation_Agent silencieusement inerte une fois câblé.
  4. Une AgentDecisionLog par question traitée (decomposition_error inclus :
     tracer même un échec fait partie de l'explicabilité).
  5. Une ReasoningClarificationRequest par ClarificationRequest produite par
     l'agent (Phase 4) — related_entity_type/id résolu depuis related_field
     ("bareme..." -> Bareme de la question ; "steps[...]" -> Question),
     severity/proposed_answer transmis tels quels, jamais réinterprétés ici.

Aucune donnée n'est jamais réinventée : un champ absent côté agent reste
absent côté persistance (mandated_method=None, bareme=None si bareme_error,
etc.) — ce service persiste EXACTEMENT ce que l'agent a déterminé, jamais
plus, jamais moins.
"""
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import (
    ClarificationRequest,
    CorrectionBlockInput,
    ExtractionVerificationAgent,
    QuestionInput,
    QuestionVerificationResult,
    ReasoningStepOutput,
)
from app.agents.extraction_verification_exceptions import ExerciseAlreadyPublishedError
from app.core.exceptions import ExerciseNotFoundError
from app.domain.models.assessment.bareme import BaremeValidationStatus
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.reasoning_clarification_request import ClarificationSeverity
from app.domain.models.assessment.solution_variant import VariantDifficulty, VariantSource
from app.domain.repositories.agent_decision_log_repository import AgentDecisionLogRepositoryProtocol
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.reasoning_clarification_request_repository import (
    ReasoningClarificationRequestRepositoryProtocol,
)
from app.domain.repositories.solution_variant_repository import SolutionVariantRepositoryProtocol
from app.domain.repositories.teacher_correction_block_repository import (
    TeacherCorrectionBlockRepositoryProtocol,
)
from app.domain.schemas.solution_schemas import ReasoningClarificationRequestRead

AGENT_NAME = "Extraction_Verification_Agent"

# cf. docstring module — l'agent ne produit aucune estimation de difficulté ;
# valeur neutre assumée, pas calculée.
_DEFAULT_DIFFICULTY = VariantDifficulty.INTERMEDIAIRE


@dataclass
class ExtractionVerificationResult:
    """Reflète ce qui a été persisté par verify_extraction()."""
    exercise_id: uuid.UUID
    questions_processed: int
    baremes_created: int
    baremes_pending_review: int
    reasoning_steps_created: int
    clarifications_created: int
    blocking_clarifications_created: int
    decomposition_failures: int
    bareme_failures: int


class ExtractionVerificationServiceProtocol(Protocol):
    async def verify_extraction(
        self, exercise_id: uuid.UUID, trace_id: str | None = None,
    ) -> ExtractionVerificationResult: ...
    async def get_pending_blocking_clarifications(
        self, exercise_id: uuid.UUID,
    ) -> list[ReasoningClarificationRequestRead]: ...


class ExtractionVerificationService:
    """
    Injection :
    - exercise_repository : charge l'exercice/questions, persiste Bareme + mandated_method
    - teacher_correction_block_repository : charge les blocs de correction (raw_text)
    - solution_variant_repository : persiste SolutionVariant + graphe ReasoningStep
    - decision_log_repository : trace chaque question traitée
    - clarification_repository : persiste + récupère les ClarificationRequest
    - agent : ExtractionVerificationAgent, injectable pour les tests
    """

    def __init__(
        self,
        exercise_repository: ExerciseRepositoryProtocol,
        teacher_correction_block_repository: TeacherCorrectionBlockRepositoryProtocol,
        solution_variant_repository: SolutionVariantRepositoryProtocol,
        decision_log_repository: AgentDecisionLogRepositoryProtocol,
        clarification_repository: ReasoningClarificationRequestRepositoryProtocol,
        agent: ExtractionVerificationAgent | None = None,
    ) -> None:
        self._exercises = exercise_repository
        self._blocks = teacher_correction_block_repository
        self._variants = solution_variant_repository
        self._decision_logs = decision_log_repository
        self._clarifications = clarification_repository
        self._agent = agent or ExtractionVerificationAgent()

    async def verify_extraction(
        self, exercise_id: uuid.UUID, trace_id: str | None = None,
    ) -> ExtractionVerificationResult:
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        # Défense en profondeur : l'agent revérifie la même condition, mais
        # ce service ne doit même pas construire les entrées LLM pour un
        # exercice déjà publié (même principe que exercise_ocr_pipeline_service).
        if exercise.status != ExerciseStatus.DRAFT:
            raise ExerciseAlreadyPublishedError(exercise_id, str(exercise.status))

        questions = exercise.questions or []
        section_order_by_id = {s.id: s.order for s in (exercise.sections or [])}

        question_inputs = [
            QuestionInput(
                question_id=q.id,
                order=q.order,
                statement=q.statement,
                section_order=section_order_by_id.get(q.section_id) if q.section_id else None,
            )
            for q in questions
        ]

        all_blocks = await self._blocks.list_by_exercise(exercise_id)
        blocks_by_question: dict[uuid.UUID, list[CorrectionBlockInput]] = {}
        for block in all_blocks:
            if block.question_id is None:
                continue
            blocks_by_question.setdefault(block.question_id, []).append(
                CorrectionBlockInput(
                    block_id=block.id,
                    content_type=block.content_type,
                    raw_text=block.raw_text,
                    structured_content=block.structured_content,
                    evidence_level=block.evidence_level,
                )
            )

        context = AgentExecutionContext(
            trace_id=trace_id or str(exercise_id),
            flow_type="exercise_setup",
            exercise_id=exercise_id,
        )
        report = await self._agent.execute(
            question_inputs, blocks_by_question, exercise.status, context,
        )

        baremes_created = 0
        baremes_pending_review = 0
        reasoning_steps_created = 0
        clarifications_created = 0
        blocking_clarifications_created = 0
        decomposition_failures = 0
        bareme_failures = 0

        for result in report.questions:
            if result.decomposition_error:
                decomposition_failures += 1
            if result.bareme_error:
                bareme_failures += 1

            bareme_id = await self._persist_bareme(result)
            if bareme_id is not None:
                baremes_created += 1
                if result.bareme.status == "PENDING_REVIEW":
                    baremes_pending_review += 1

            correction_text = self._combine_block_text(blocks_by_question.get(result.question_id, []))
            reasoning_steps_created += await self._persist_reasoning_graph(result, correction_text)

            await self._exercises.set_question_mandated_method(
                result.question_id, result.mandated_method,
            )
            # Câblage workflow (Priorité 1) — bloqueur découvert en câblant
            # comparative_evaluation_node : covered_subquestions (Phase 2)
            # n'était persisté nulle part, même principe que mandated_method
            # ci-dessus.
            await self._exercises.set_question_covered_subquestions(
                result.question_id, result.covered_subquestions,
            )
            # Chantier barème C2PCT natif (Cas 0) — même principe que
            # covered_subquestions ci-dessus : None si aucun barème détaillé
            # par sous-question n'a été trouvé pour cette question (repli
            # sur le calcul proportionnel côté Pedagogical_Evaluation_Agent).
            await self._exercises.set_question_subquestion_points(
                result.question_id, result.subquestion_points,
            )
            # 2026-08-29 (backlog_bugs_c2pct.md) — extraits verbatim par
            # sous-question, même principe additif que ci-dessus : None si
            # covered_subquestions était vide ou si l'extraction a échoué
            # (best-effort, cf. docstring de l'agent).
            await self._exercises.set_question_subquestions(
                result.question_id,
                [{"id": s.id, "content": s.content} for s in result.subquestion_segments]
                if result.subquestion_segments else None,
            )
            # 2026-08-18 — règles générales du barème, même principe que
            # covered_subquestions ci-dessus : jusqu'ici perdues après
            # extraction, désormais persistées pour être lues par
            # comparative_evaluation_node (EvaluationRequest.general_rules).
            await self._exercises.set_question_general_rules(
                result.question_id, result.general_rules,
            )

            await self._persist_decision_log(result)

            for clarification in result.clarifications:
                await self._persist_clarification(clarification, result.question_id, bareme_id)
                clarifications_created += 1
                if clarification.severity == ClarificationSeverity.BLOCKING:
                    blocking_clarifications_created += 1

        return ExtractionVerificationResult(
            exercise_id=exercise_id,
            questions_processed=len(report.questions),
            baremes_created=baremes_created,
            baremes_pending_review=baremes_pending_review,
            reasoning_steps_created=reasoning_steps_created,
            clarifications_created=clarifications_created,
            blocking_clarifications_created=blocking_clarifications_created,
            decomposition_failures=decomposition_failures,
            bareme_failures=bareme_failures,
        )

    async def get_pending_blocking_clarifications(
        self, exercise_id: uuid.UUID,
    ) -> list[ReasoningClarificationRequestRead]:
        """
        Présentation groupée (§ ticket) : toutes les clarifications BLOCKING
        encore en attente pour cet exercice, en un seul appel — pour un futur
        écran récapitulatif (hors périmètre ici, interface).
        """
        requests = await self._clarifications.list_pending_blocking_by_exercise(exercise_id)
        reads = []
        for request in requests:
            # Champ aplati requis par le schéma, jamais une colonne ORM (cf.
            # reasoning_clarification_request.py) — toujours None ici : ces
            # demandes sont PENDING par construction (list_pending_blocking_
            # by_exercise), donc jamais encore répondues.
            request.answered_by_professor_name = None
            reads.append(ReasoningClarificationRequestRead.model_validate(request))
        return reads

    # ------------------------------------------------------------------
    # Persistance par question
    # ------------------------------------------------------------------

    async def _persist_bareme(self, result: QuestionVerificationResult) -> uuid.UUID | None:
        if result.bareme is None:
            return None

        validation_status = (
            BaremeValidationStatus.CONFIRMED
            if result.bareme.status == "READY"
            else BaremeValidationStatus.PENDING_REVIEW
        )
        criteria = [
            {
                "id": c.id,
                "label": c.label,
                "points": str(c.points),
                "correction_mode": c.correction_mode.value,
                "verifiable_conditions": c.verifiable_conditions,
                "disqualifying": c.disqualifying,
                "test_cases": [
                    {
                        "input": tc.input,
                        "expected_output": tc.expected_output,
                        "visibility": tc.visibility,
                    }
                    for tc in c.test_cases
                ],
                "reference_code": c.reference_code,
                "expected_complexity": c.expected_complexity,
                # 2026-08-18 — même principe que general_rules : jusqu'ici
                # jamais extrait (BaremeCriterionProposal n'avait pas ces
                # champs), donc RUBRIC_LEVELS/PROCEDURAL_SEQUENCE recevaient
                # toujours une liste vide côté Comparative_Evaluation_Agent
                # peu importe le texte du barème.
                "rubric_levels": c.rubric_levels,
                "expected_steps": c.expected_steps,
            }
            for c in result.bareme.criteria
        ]
        bareme = await self._exercises.create_bareme_for_question(
            question_id=result.question_id,
            points=result.bareme.total_points,
            criteria=criteria,
            validation_status=validation_status,
        )
        return bareme.id

    async def _persist_reasoning_graph(
        self, result: QuestionVerificationResult, correction_text: str,
    ) -> int:
        # Décomposition en échec (schéma LLM non conforme) : rien de valide
        # à persister — pas de variante fabriquée à partir de données absentes.
        if result.decomposition_error is not None:
            return 0

        steps_data = [
            {
                "step_ref": step.step_ref,
                "order": step.order,
                "step_type": step.step_type,
                "description": step.description,
                "formula": step.formula,
                "depends_on_refs": step.depends_on_refs,
                "extraction_signals": self._build_extraction_signals(step),
            }
            for step in result.steps
        ]
        # Le texte source réel de la correction (même contenu que celui
        # transmis à Extraction_Verification_Agent) — jamais reconstruit à
        # partir des source_span par étape, qui ne sont que des extraits
        # ponctuels. Reasoning_Graph_Agent (Agent 5) ne lit plus ce champ du
        # tout (v2 : il enrichit les ReasoningStep déjà persistés ci-dessous,
        # jamais un second parseur de texte brut — cf. docstring module
        # Reasoning_Graph_Agent) ; `content` reste néanmoins l'archive brute
        # consultée directement par Comparative_Evaluation_Agent
        # (reference_solution_text = SolutionVariant.content).
        await self._variants.create_with_reasoning_graph(
            question_id=result.question_id,
            content=correction_text or "(aucun texte de correction)",
            source=VariantSource.TEACHER_ORIGINAL,
            difficulty_level=_DEFAULT_DIFFICULTY,
            is_reference=True,
            structured_content=None,
            steps_data=steps_data,
        )
        return len(steps_data)

    @staticmethod
    def _build_extraction_signals(step: ReasoningStepOutput) -> dict | None:
        signals = {
            "anomaly_detected": step.anomaly_detected,
            "anomaly_justification": step.anomaly_justification,
            "case_group_id": step.case_group_id,
            "recurrence_role": step.recurrence_role,
            "canonical_form": step.canonical_form,
            "dimensional_check_result": step.dimensional_check_result,
            "numeric_tolerance": step.numeric_tolerance,
            "criticality": step.criticality,
            "source_span": step.source_span,
        }
        # None si l'étape n'a produit aucun signal au-delà du strict
        # nécessaire (source_span est toujours présent — jamais le seul
        # motif de non-vide, cf. contrat de ReasoningStepOutput).
        meaningful = {k: v for k, v in signals.items() if k != "source_span" and v}
        return signals if meaningful else None

    @staticmethod
    def _combine_block_text(blocks: list[CorrectionBlockInput]) -> str:
        return "\n".join(b.raw_text for b in blocks if b.raw_text)

    async def _persist_decision_log(self, result: QuestionVerificationResult) -> None:
        parts = []
        if result.bareme and result.bareme.criteria:
            modes = [c.correction_mode.value for c in result.bareme.criteria]
            dominant_mode = Counter(modes).most_common(1)[0][0]
            parts.append(f"mode dominant : {dominant_mode}")
        anomaly_count = sum(1 for s in result.steps if s.anomaly_detected)
        if anomaly_count:
            parts.append(f"{anomaly_count} anomalie(s) de calcul détectée(s)")
        if result.mandated_method:
            parts.append(f"méthode imposée : {result.mandated_method}")
        if result.decomposition_error:
            parts.append(f"décomposition en échec : {result.decomposition_error}")
        if result.bareme_error:
            parts.append(f"barème en échec : {result.bareme_error}")
        justification = "; ".join(parts) or "Vérification d'extraction complétée sans signal particulier."

        await self._decision_logs.create(
            agent_name=AGENT_NAME,
            related_entity_type="Question",
            related_entity_id=result.question_id,
            justification=justification,
            model_version=result.model_version or "unknown",
        )

    async def _persist_clarification(
        self,
        clarification: ClarificationRequest,
        question_id: uuid.UUID,
        bareme_id: uuid.UUID | None,
    ) -> None:
        if clarification.related_field.startswith("bareme") and bareme_id is not None:
            related_entity_type, related_entity_id = "Bareme", bareme_id
        else:
            related_entity_type, related_entity_id = "Question", question_id

        await self._clarifications.create(
            agent_question=clarification.agent_question,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
            proposed_answer=clarification.proposed_answer,
            severity=clarification.severity,
        )
