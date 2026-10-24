"""
Service — orchestrateur de Contestation_Verification_Agent.

Contrairement à document_structuring_service.py (qui reçoit un rapport déjà
produit par son agent), ce service appelle lui-même l'agent — nécessaire
pour que exceeds_abuse_threshold (§8) et sort_cases_by_priority (§9ter)
s'appliquent réellement AVANT l'invocation de l'agent, comme demandé.

Prérequis hors périmètre de ce fichier : une étape d'intake (endpoint/service
"l'étudiant conteste ce bloc", pas encore écrite) doit avoir déjà posé
contestation_type/contestation_status=PENDING_VERIFICATION/contested_element_id/
claimed_question_id/claimed_section_id/human_correction sur la ligne
ExtractionCorrection avant que process_pending_contestations() ne la trouve.

Deux inférences documentées, nécessaires car deux informations ne sont pas
persistées séparément sur ExtractionCorrection :
- fusion_claim (Cas D) : aucune colonne dédiée. Entièrement déterminé par
  l'état de fusion du bloc au moment de la contestation — un bloc déjà
  fusionné (survivant ou consommé) ne peut être contesté que comme
  'wrongly_merged', un bloc non fusionné que comme 'should_have_merged'
  (cf. _infer_fusion_claim).
- structure_type (Cas C-entier) : ExtractionCorrection n'a pas de colonne
  structure_type (absente du modèle et de bulk_create_for_submission) —
  déduite de la forme de structured_output (cf. _infer_structure_type).
"""
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.agents.context import AgentExecutionContext
from app.agents.Contestation_Verification_Agent import (
    ContestationCaseInput,
    ContestationVerificationAgent,
    ExtractionCorrectionSnapshot,
    QuestionCandidate,
)
from app.agents.ocr_block_utils import to_decimal_confidence
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
    ExtractionCorrection,
    StructureType,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.system_infrastructure.integrity_alert import IntegrityTriggerType
from app.domain.repositories.agent_decision_log_repository import AgentDecisionLogRepositoryProtocol
from app.domain.repositories.correction_arbitration_repository import (
    CorrectionArbitrationRepositoryProtocol,
)
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.extraction_correction_repository import (
    ExtractionCorrectionRepositoryProtocol,
)
from app.domain.repositories.integrity_alert_repository import IntegrityAlertRepositoryProtocol
from app.domain.repositories.solution_variant_repository import SolutionVariantRepositoryProtocol
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.schemas.contestation_schemas import ContestationVerdict, ContestExtractionRequest
from app.infra_services.storage_service import StorageContainer, storage_service

AGENT_NAME = "Contestation_Verification_Agent"

_VERDICT_TO_STATUS: dict[str, ContestationStatus] = {
    "PLAUSIBLE": ContestationStatus.PLAUSIBLE,
    "IMPLAUSIBLE": ContestationStatus.IMPLAUSIBLE,
    "AMBIGU": ContestationStatus.AMBIGU,
}


@dataclass
class ContestationProcessingResult:
    """
    Distingue explicitement "rien n'était en attente" de "signalé pour
    examen manuel (§8)" — les deux se traduisaient auparavant par une même
    liste vide, ce qu'un appelant (ex. contestation_verification_node) ne
    peut pas distinguer alors que §8 exige une mise en pause dans le second
    cas seulement.
    """
    verdicts: list[ContestationVerdict] = field(default_factory=list)
    flagged_for_manual_review: bool = False


class ContestationVerificationService:
    def __init__(
        self,
        extraction_correction_repo: ExtractionCorrectionRepositoryProtocol,
        correction_arbitration_repo: CorrectionArbitrationRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        exercise_repo: ExerciseRepositoryProtocol,
        solution_variant_repo: SolutionVariantRepositoryProtocol,
        decision_log_repo: AgentDecisionLogRepositoryProtocol,
        integrity_alert_repo: IntegrityAlertRepositoryProtocol,
        agent: ContestationVerificationAgent | None = None,
    ) -> None:
        self._extraction_correction_repo = extraction_correction_repo
        self._correction_arbitration_repo = correction_arbitration_repo
        self._submission_repo = submission_repo
        self._exercise_repo = exercise_repo
        self._solution_variant_repo = solution_variant_repo
        self._decision_log_repo = decision_log_repo
        self._integrity_alert_repo = integrity_alert_repo
        self._agent = agent or ContestationVerificationAgent()

    async def process_pending_contestations(
        self,
        submission_id: uuid.UUID,
        context: AgentExecutionContext,
    ) -> ContestationProcessingResult:
        """
        Point d'entrée unique : charge l'état réel de la soumission (§2),
        applique §8 puis §9ter, exécute l'agent bloc par bloc, persiste
        chaque verdict immédiatement (§2 étape 7 — jamais une écriture
        groupée qui attendrait tous les blocs contestés).
        """
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission is None:
            return ContestationProcessingResult()

        blocks = await self._extraction_correction_repo.get_by_submission_id(submission_id)
        pending = [
            b for b in blocks if b.contestation_status == ContestationStatus.PENDING_VERIFICATION
        ]
        if not pending:
            return ContestationProcessingResult()

        # §8 — garde-fou anti-abus : un signal, jamais un blocage. Si
        # dépassé, l'agent n'est appelé sur AUCUN bloc de cette soumission.
        if ContestationVerificationAgent.exceeds_abuse_threshold(len(pending), len(blocks)):
            await self._integrity_alert_repo.create(
                student_id=submission.student_id,
                trigger_type=IntegrityTriggerType.SYSTEMATIC_CONTESTATION,
                auto_generated=True,
                evidence={
                    "submission_id": str(submission_id),
                    "contested_block_count": len(pending),
                    "total_block_count": len(blocks),
                },
                reason=(
                    f"{len(pending)}/{len(blocks)} blocs contestés sur cette soumission — "
                    "signalé au professeur pour examen manuel plutôt que traité bloc par bloc."
                ),
            )
            return ContestationProcessingResult(flagged_for_manual_review=True)

        document_bytes: bytes | None = None
        if submission.document_path and submission.document_mime_type:
            document_bytes = await storage_service.download(
                StorageContainer.SUBMISSIONS, submission.document_path
            )

        cases = [
            await self._build_case(block, blocks, submission, document_bytes)
            for block in pending
        ]
        # §9ter, niveau lot — cf. docstring de sort_cases_by_priority : ordonne
        # les blocs FUSION avant le reste quand plusieurs blocs distincts
        # d'une même soumission sont en attente (pas le vrai scénario "même
        # bloc, deux fronts", non représentable par le schéma actuel).
        cases = ContestationVerificationAgent.sort_cases_by_priority(cases)

        verdicts: list[ContestationVerdict] = []
        for case in cases:
            verdict = await self._agent.execute(case, context)
            await self._persist_verdict(verdict, submission_id)
            verdicts.append(verdict)

        return ContestationProcessingResult(verdicts=verdicts)

    # ------------------------------------------------------------------
    # Construction du ContestationCaseInput
    # ------------------------------------------------------------------

    async def _build_case(
        self,
        block: ExtractionCorrection,
        all_blocks: list[ExtractionCorrection],
        submission: Submission,
        document_bytes: bytes | None,
    ) -> ContestationCaseInput:
        request = ContestExtractionRequest(
            contestation_type=block.contestation_type,
            claimed_content=block.human_correction,
            contested_element_id=block.contested_element_id,
            claimed_question_id=block.claimed_question_id,
            claimed_section_id=block.claimed_section_id,
            fusion_claim=(
                self._infer_fusion_claim(block, all_blocks)
                if block.contestation_type == ContestationType.FUSION
                else None
            ),
        )

        candidate_questions: list[QuestionCandidate] = []
        fusion_group: list[ExtractionCorrectionSnapshot] = []
        submission_blocks: list[ExtractionCorrectionSnapshot] = []

        if block.contestation_type == ContestationType.ATTACHMENT:
            candidate_questions = await self._build_question_candidates(submission.exercise_id)
        elif block.contestation_type == ContestationType.FUSION:
            fusion_group = self._build_fusion_group(block, all_blocks)
            submission_blocks = [self._to_snapshot(b) for b in all_blocks]

        return ContestationCaseInput(
            contested=self._to_snapshot(block),
            request=request,
            document_bytes=document_bytes,
            document_mime_type=submission.document_mime_type,
            candidate_questions=candidate_questions,
            fusion_group=fusion_group,
            submission_blocks=submission_blocks,
        )

    @staticmethod
    def _to_snapshot(block: ExtractionCorrection) -> ExtractionCorrectionSnapshot:
        return ExtractionCorrectionSnapshot(
            id=block.id,
            submission_id=block.submission_id,
            image_crop_path=block.image_crop_path,
            content_type=block.content_type,
            prediction_ocr=block.prediction_ocr,
            bounding_box=block.bounding_box,
            evidence_level=block.evidence_level,
            question_id=block.question_id,
            page_number=block.page_number,
            structure_type=ContestationVerificationService._infer_structure_type(
                block.structured_output
            ),
            structured_output=block.structured_output,
            human_correction=block.human_correction,
            contestation_status=block.contestation_status,
            fused_extraction_correction_ids=(
                [uuid.UUID(x) for x in block.fused_extraction_correction_ids]
                if block.fused_extraction_correction_ids
                else None
            ),
        )

    @staticmethod
    def _infer_structure_type(structured_output: dict | None) -> StructureType | None:
        """ExtractionCorrection ne persiste pas structure_type — déduit de la forme de structured_output."""
        if not isinstance(structured_output, dict):
            return None
        if "rows" in structured_output:
            return StructureType.TABLE
        if "fields" in structured_output:
            return StructureType.FORM
        if "elements" in structured_output:
            return StructureType.ANNOTATED_DIAGRAM
        if "columns" in structured_output:
            return StructureType.MULTI_COLUMN_LIST
        return None

    @staticmethod
    def _infer_fusion_claim(
        block: ExtractionCorrection, all_blocks: list[ExtractionCorrection],
    ) -> Literal["wrongly_merged", "should_have_merged"]:
        if block.fused_extraction_correction_ids:
            return "wrongly_merged"
        block_id_str = str(block.id)
        is_consumed_member = any(
            b.fused_extraction_correction_ids and block_id_str in b.fused_extraction_correction_ids
            for b in all_blocks
        )
        return "wrongly_merged" if is_consumed_member else "should_have_merged"

    def _build_fusion_group(
        self, block: ExtractionCorrection, all_blocks: list[ExtractionCorrection],
    ) -> list[ExtractionCorrectionSnapshot]:
        by_id = {b.id: b for b in all_blocks}

        if block.fused_extraction_correction_ids:
            member_ids = [block.id] + [
                uuid.UUID(x) for x in block.fused_extraction_correction_ids
            ]
        else:
            survivor = next(
                (
                    b for b in all_blocks
                    if b.fused_extraction_correction_ids
                    and str(block.id) in b.fused_extraction_correction_ids
                ),
                None,
            )
            if survivor is None:
                member_ids = [block.id]
            else:
                member_ids = [survivor.id] + [
                    uuid.UUID(x) for x in survivor.fused_extraction_correction_ids
                ]

        return [self._to_snapshot(by_id[mid]) for mid in member_ids if mid in by_id]

    async def _build_question_candidates(self, exercise_id: uuid.UUID) -> list[QuestionCandidate]:
        exercise = await self._exercise_repo.get_by_id(exercise_id)
        if exercise is None:
            return []

        section_by_id = {section.id: section for section in exercise.sections}

        # position_in_section : rang 1-based parmi TOUTES les questions de la
        # même section, trié par order — même calcul que build_question_refs
        # (submission_ocr_pipeline_service.py), nécessaire pour que le
        # matching de label (Cas B, Niveau 1) utilise ce que l'étudiant voit
        # réellement, jamais Question.order (global à l'exercice).
        position_in_section_by_question_id: dict[uuid.UUID, int] = {}
        questions_by_section: dict[uuid.UUID | None, list] = {}
        for question in sorted(exercise.questions, key=lambda q: q.order):
            questions_by_section.setdefault(question.section_id, []).append(question)
        for section_id, section_questions in questions_by_section.items():
            if section_id is None:
                continue
            for rank, section_question in enumerate(section_questions, start=1):
                position_in_section_by_question_id[section_question.id] = rank

        candidates: list[QuestionCandidate] = []
        for question in exercise.questions:
            variants = await self._solution_variant_repo.list_by_question(question.id)
            reference = next((v for v in variants if v.is_reference), None)
            section = section_by_id.get(question.section_id) if question.section_id else None
            candidates.append(
                QuestionCandidate(
                    question_id=question.id,
                    exercise_id=exercise_id,
                    order=question.order,
                    reference_content=reference.content if reference else "",
                    section_id=question.section_id,
                    section_order=section.order if section else None,
                    section_title=section.title if section else None,
                    reference_summary=reference.reasoning_summary if reference else None,
                    position_in_section=position_in_section_by_question_id.get(question.id),
                )
            )
        return candidates

    # ------------------------------------------------------------------
    # Persistance du verdict
    # ------------------------------------------------------------------

    async def _persist_verdict(self, verdict: ContestationVerdict, submission_id: uuid.UUID) -> None:
        confidence_decimal: Decimal | None = (
            to_decimal_confidence(verdict.confidence_score)
            if verdict.confidence_score is not None
            else None
        )
        contestation_status = _VERDICT_TO_STATUS[verdict.verdict]

        if verdict.fused_correction_ids:
            await self._extraction_correction_repo.apply_fusion_verdict(
                group_ids=verdict.fused_correction_ids,
                defusion_applied=verdict.defusion_applied,
                contestation_status=contestation_status,
                confidence_score=confidence_decimal,
            )
        else:
            await self._extraction_correction_repo.apply_contestation_verdict(
                correction_id=verdict.extraction_correction_id,
                contestation_status=contestation_status,
                verified_content=verdict.verified_content,
                confidence_score=confidence_decimal,
                # Cas B (ATTACHMENT) PLAUSIBLE uniquement — cf. docstring du
                # correctif dans extraction_correction_repository.py. Un
                # verdict AMBIGU laisse resolved_question_id de côté à
                # dessein : la décision revient au professeur (arbitrage
                # ci-dessus), jamais appliquée directement ici.
                resolved_question_id=(
                    verdict.resolved_question_id if verdict.verdict == "PLAUSIBLE" else None
                ),
            )

        if verdict.verdict == "AMBIGU":
            # §2 étape 6 — création de la CorrectionArbitration PENDING et
            # mise en pause de TOUTE la soumission (pas seulement ce bloc).
            await self._correction_arbitration_repo.create_pending(verdict.extraction_correction_id)
            await self._submission_repo.update_status(
                submission_id, SubmissionStatus.PENDING_ARBITRATION
            )

        # §7 — une trace par verdict, même pattern que document_structuring_service.py.
        await self._decision_log_repo.create(
            agent_name=AGENT_NAME,
            related_entity_type="ExtractionCorrection",
            related_entity_id=verdict.extraction_correction_id,
            justification=verdict.justification,
            model_version=verdict.model_version,
            confidence_score=confidence_decimal,
        )
