"""
Pipeline OCR pour une soumission étudiante.

Orchestration end-to-end :
  1. Téléchargement du scan original depuis Azure
  2. OCR_Extraction_Agent v3 (upload des crops Azure)
  3. Persistance des blocs extraits (question_id=null)
  4. Question_Attachment_Agent (si variantes de référence disponibles)
  5. Publication extraction-ready.v1 par bloc rattaché
  6. Mise à jour du statut → PENDING_STUDENT_VERIFICATION
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.agents.context import AgentExecutionContext
from app.agents.ocr_block_utils import filter_consumer_block, to_decimal_confidence
from app.agents.OCR_Extraction_Agent import OCRExtractionAgent
from app.agents.Question_Attachment_Agent import (
    AttachmentDecision,
    AttachmentResult,
    QuestionAttachmentAgent,
    QuestionRef,
)
from app.core.exceptions import OCRExtractionError, SubmissionNotFoundError
from app.domain.models.assessment.exercise import Exercise
from app.domain.models.assessment.extraction_correction import ExtractionCorrection
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.repositories.agent_decision_log_repository import (
    SQLAlchemyAgentDecisionLogRepository,
)
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.extraction_correction_repository import (
    SQLAlchemyExtractionCorrectionRepository,
)
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.schemas.submission_schemas import AttachedExtractedBlock, RawExtractedBlock
from app.infra_services.storage_service import StorageContainer, storage_service
from app.services.event_publisher_service import EventPublisherService
from app.services.idempotency_service import IdempotencyService

logger = logging.getLogger(__name__)

# ProcessedEvent.event_id est un String(36) (dimensionné pour un event_id
# Kafka, un UUID brut) — un identifiant préfixé/namespacé plus long
# ("question_attachment:<uuid>") lève StringDataRightTruncationError
# (constaté). uuid5 dérive un UUID déterministe (36 caractères, tient dans
# la colonne) à partir de la clé namespacée, sans migration de schéma et
# sans risque de collision avec un vrai event_id Kafka (domaine de dérivation
# différent — un UUID Kafka brut n'est jamais un uuid5 de ce namespace).
_IDEMPOTENCY_NAMESPACE = uuid.UUID("6f2c9a3e-6b7f-4a3d-9d7a-9a2e6f9c9d1a")


def _question_attachment_idempotency_key(submission_id: uuid.UUID) -> str:
    return str(uuid.uuid5(_IDEMPOTENCY_NAMESPACE, f"question_attachment:{submission_id}"))


def _normalize_structured_output(value: dict | str | None) -> dict | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return {"latex": value}


def _raw_blocks_from_corrections(
    corrections: list[ExtractionCorrection],
) -> list[RawExtractedBlock]:
    """
    Reconstruction best-effort depuis des ExtractionCorrection déjà
    persistées — utilisée uniquement sur le chemin idempotent "soumission
    déjà traitée" (skip complet d'OCR_Extraction_Agent, cf. run()).

    Perte de fidélité assumée, documentée plutôt que cachée : plusieurs
    champs produits par l'agent 1 ne sont persistés sur aucune colonne
    (structure_type, reconstruction_confidence, student_label, origin,
    fused_crop_paths — même constat que le gap structure_type déjà
    documenté à l'audit précédent) et reviennent donc à None/valeur par
    défaut ici. block_order_index n'a pas non plus de colonne dédiée :
    resynthétisé par énumération triée (page_number, created_at) — un ordre
    stable, pas nécessairement identique à celui produit originellement par
    l'agent 1. Sans conséquence sur ce chemin précis : le skip complet ne
    rejoue ni OCR ni attachment pour cette soumission, ces champs ne sont
    plus consultés une fois qu'on sait qu'elle est déjà traitée.
    """
    ordered = sorted(corrections, key=lambda c: (c.page_number or 0, c.created_at))
    return [
        RawExtractedBlock(
            image_crop_path=c.image_crop_path,
            content_type=c.content_type,
            structure_type=None,
            prediction_ocr=c.prediction_ocr,
            structured_output=c.structured_output,
            confidence_score=c.confidence_score,
            reconstruction_confidence=None,
            bounding_box=c.bounding_box,
            page_number=c.page_number or 0,
            block_order_index=idx,
            student_label=None,
            origin=None,
            is_struck_through=False,
            evidence_level=c.evidence_level,
            fused_crop_paths=None,
        )
        for idx, c in enumerate(ordered)
    ]


def raw_blocks_to_persistence_dicts(
    blocks: list[RawExtractedBlock],
) -> list[dict[str, Any]]:
    return [
        {
            "image_crop_path": block.image_crop_path,
            "page_number": block.page_number,
            "content_type": block.content_type.value,
            "prediction_ocr": block.prediction_ocr,
            "structured_output": _normalize_structured_output(block.structured_output),
            "confidence_score": block.confidence_score,
            "bounding_box": block.bounding_box,
            "evidence_level": block.evidence_level.value,
            "question_id": None,
        }
        for block in blocks
    ]


async def build_question_refs(
    exercise: Exercise,
    variant_repo: SQLAlchemySolutionVariantRepository,
) -> list[QuestionRef]:
    """Construit les QuestionRef avec SolutionVariant de référence pour l'attachement."""
    if not exercise.questions:
        return []

    section_order_by_id = {section.id: section.order for section in (exercise.sections or [])}

    # position_in_section : rang 1-based parmi TOUTES les questions de la
    # même section (pas seulement celles qui survivront au filtre référence
    # ci-dessous) — la numérotation vue par l'étudiant ne doit jamais
    # dépendre de quelles variantes de référence existent.
    position_in_section_by_question_id: dict[uuid.UUID, int] = {}
    questions_by_section: dict[uuid.UUID | None, list] = {}
    for question in sorted(exercise.questions, key=lambda q: q.order):
        questions_by_section.setdefault(question.section_id, []).append(question)
    for section_id, section_questions in questions_by_section.items():
        if section_id is None:
            continue
        for rank, section_question in enumerate(section_questions, start=1):
            position_in_section_by_question_id[section_question.id] = rank

    refs: list[QuestionRef] = []

    for question in sorted(exercise.questions, key=lambda q: q.order):
        variants = await variant_repo.list_by_question(question.id)
        reference = next((v for v in variants if v.is_reference), None)
        if reference is None or not reference.content.strip():
            continue

        section_order = (
            section_order_by_id.get(question.section_id)
            if question.section_id is not None
            else None
        )
        refs.append(
            QuestionRef(
                question_id=question.id,
                exercise_id=exercise.id,
                order=question.order,
                statement=question.statement,
                section_order=section_order,
                position_in_section=position_in_section_by_question_id.get(question.id),
                reference_content=reference.content,
                reference_summary=reference.reasoning_summary,
            )
        )

    return refs


class SubmissionOCRPipelineService:
    def __init__(
        self,
        submission_repo: SQLAlchemySubmissionRepository,
        extraction_repo: SQLAlchemyExtractionCorrectionRepository,
        exercise_repo: SQLAlchemyExerciseRepository | None = None,
        variant_repo: SQLAlchemySolutionVariantRepository | None = None,
        event_publisher: EventPublisherService | None = None,
        ocr_agent: OCRExtractionAgent | None = None,
        attachment_agent: QuestionAttachmentAgent | None = None,
        decision_log_repo: SQLAlchemyAgentDecisionLogRepository | None = None,
        idempotency_service: IdempotencyService | None = None,
    ) -> None:
        self._submissions = submission_repo
        self._extractions = extraction_repo
        self._exercises = exercise_repo
        self._variants = variant_repo
        self._events = event_publisher or EventPublisherService()
        self._ocr_agent = ocr_agent or OCRExtractionAgent()
        self._attachment_agent = attachment_agent or QuestionAttachmentAgent()
        self._decision_logs = decision_log_repo
        self._idempotency = idempotency_service

    async def run(
        self,
        submission_id: uuid.UUID,
        exercise_id: uuid.UUID,
        student_id: uuid.UUID,
        document_path: str,
        mime_type: str,
        trace_id: str | None = None,
    ) -> list[RawExtractedBlock]:
        submission = await self._submissions.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)

        if submission.student_id != student_id:
            raise SubmissionNotFoundError(submission_id)

        if self._idempotency is not None:
            first_time = await self._idempotency.try_mark_processed(
                _question_attachment_idempotency_key(submission_id)
            )
            if not first_time:
                # Redéclenchement hors reprise de graph (retry Celery
                # classique, par ex. — le checkpointer LangGraph ne protège
                # que le scénario de reprise via Command(resume=...)) : skip
                # complet, ni OCR (coûteux en vision) ni attachment rejoués,
                # aucun événement extraction-ready republié, statut déjà
                # posé par le premier passage réussi.
                logger.info(
                    "Pipeline OCR déjà traité pour submission_id=%s — skip "
                    "idempotent, blocs reconstruits depuis l'existant.",
                    submission_id,
                )
                existing_corrections = await self._extractions.get_by_submission_id(
                    submission_id
                )
                return _raw_blocks_from_corrections(existing_corrections)

        resolved_path = document_path or submission.document_path
        resolved_mime = mime_type or submission.document_mime_type
        if not resolved_path or not resolved_mime:
            raise OCRExtractionError(
                f"Aucun document associé à la soumission {submission_id}"
            )

        document_bytes = await storage_service.download(
            StorageContainer.SUBMISSIONS,
            resolved_path,
        )

        context = AgentExecutionContext(
            trace_id=trace_id or str(submission_id),
            flow_type="student_evaluation",
            submission_id=submission_id,
            exercise_id=exercise_id,
            user_id=student_id,
        )

        raw_blocks = await self._ocr_agent.execute(
            document_bytes=document_bytes,
            mime_type=resolved_mime,
            context=context,
        )

        if not raw_blocks:
            logger.warning(
                "OCR n'a produit aucun bloc pour submission_id=%s", submission_id
            )

        # Bug corrigé (test réel, 2026-08-31) : filter_consumer_block existe
        # déjà et exclut bien is_struck_through (+ origin=PRINTED) des blocs
        # ATTACHÉS (Question_Attachment_Agent l'applique déjà en interne,
        # après fusion) — mais bulk_create_for_submission persistait encore
        # les blocs RAW, AVANT tout filtrage, donc un passage barré de la
        # copie finissait quand même en ExtractionCorrection bien réel
        # (visible à l'écran de vérification étudiante, contestable comme
        # n'importe quel contenu — constaté : un étudiant qui raye "le reste
        # ne compte pas" voit ce texte persisté et jugé "implausible" par
        # Contestation_Verification_Agent, qui vérifie fidèlement la
        # transcription mais n'a aucune notion d'exclusion sur rature).
        # Même principe que Document_Structuring_Agent côté professeur
        # (Étape 0, filtre AVANT toute persistance) — jamais un simple
        # marquage a posteriori. _try_attach_questions reçoit volontairement
        # raw_blocks NON filtré ci-dessous : sa propre fusion de continuité
        # a besoin de voir les blocs barrés pour ses frontières de fusion
        # (no_struck, cf. docstring _detect_and_fuse_continuity) — seul ce
        # qui est PERSISTÉ doit changer, jamais la logique de rattachement.
        persistable_blocks = [b for b in raw_blocks if filter_consumer_block(b) is not None]
        filtered_count = len(raw_blocks) - len(persistable_blocks)
        if filtered_count:
            logger.info(
                "%d bloc(s) barré(s)/imprimé(s) exclus de la persistance pour submission_id=%s",
                filtered_count, submission_id,
            )

        await self._extractions.bulk_create_for_submission(
            submission_id=submission_id,
            blocks=raw_blocks_to_persistence_dicts(persistable_blocks),
        )

        attached_blocks = await self._try_attach_questions(
            raw_blocks=raw_blocks,
            submission_id=submission_id,
            exercise_id=exercise_id,
            context=context,
        )

        # 2026-08-30 — publication extraction-ready.v1 supprimée (jamais
        # juste enveloppée en best-effort) : AUCUN consumer n'existe pour ce
        # topic (vérifié par grep sur tout app/), Kafka n'y apportait donc
        # aucun découplage réel. Constaté en test réel : un broker
        # indisponible (cas de cet environnement dev) faisait d'abord
        # échouer submission_evaluation_pipeline juste après
        # Question_Attachment_Agent (crash) ; une fois enveloppée en
        # best-effort, chaque tentative payait quand même ~4s de timeout de
        # connexion PAR bloc rattaché (boucle ci-dessous), ralentissant le
        # nœud de plusieurs minutes sur un document à nombreux blocs, pour
        # un événement que personne ne lit. Même pattern déjà appliqué à
        # SUBMISSION_CREATED (submission_service.py) — un futur consumer
        # réintroduirait cet appel via publish_notification_best_effort,
        # jamais un appel bloquant nu.

        await self._submissions.update_status(
            submission_id,
            SubmissionStatus.PENDING_STUDENT_VERIFICATION,
        )

        logger.info(
            "Pipeline OCR terminé pour submission_id=%s (%d blocs, %d rattachés)",
            submission_id,
            len(raw_blocks),
            sum(1 for b in attached_blocks if b.question_id is not None),
        )
        return raw_blocks

    async def _try_attach_questions(
        self,
        raw_blocks: list[RawExtractedBlock],
        submission_id: uuid.UUID,
        exercise_id: uuid.UUID,
        context: AgentExecutionContext,
    ) -> list[AttachedExtractedBlock]:
        if not raw_blocks or self._exercises is None or self._variants is None:
            return []

        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            return []

        question_refs = await build_question_refs(exercise, self._variants)
        if not question_refs:
            logger.info(
                "Aucune variante de référence pour exercise_id=%s — attachement ignoré",
                exercise_id,
            )
            return []

        result: AttachmentResult = await self._attachment_agent.execute(
            raw_blocks=raw_blocks,
            questions=question_refs,
            context=context,
        )
        attached = result.attached_blocks

        if attached:
            updated_corrections = await self._extractions.bulk_update_attachments(
                submission_id=submission_id,
                attachments=[
                    {
                        "image_crop_path": block.image_crop_path,
                        "question_id": block.question_id,
                        "evidence_level": block.evidence_level.value,
                        "fused_crop_paths": block.fused_crop_paths,
                    }
                    for block in attached
                ],
            )
            await self._record_attachment_decisions(result.decisions, updated_corrections)

        return attached

    async def _record_attachment_decisions(
        self,
        decisions: list[AttachmentDecision],
        updated_corrections: list,
    ) -> None:
        """
        Une AgentDecisionLog par bloc non filtré (cf. docstring Question_
        Attachment_Agent) — related_entity_type="ExtractionCorrection" avec
        un vrai UUID de bloc, disponible ici car bulk_create_for_submission
        a déjà persisté les ExtractionCorrection avant l'appel à l'agent
        (contrairement à l'agent 3, cf. docstring AttachmentDecision).
        """
        if self._decision_logs is None or not decisions:
            return

        correction_id_by_crop_path = {
            c.image_crop_path: c.id for c in updated_corrections
        }
        for decision in decisions:
            correction_id = correction_id_by_crop_path.get(decision.image_crop_path)
            if correction_id is None:
                continue
            await self._decision_logs.create(
                agent_name=QuestionAttachmentAgent.AGENT_NAME,
                related_entity_type="ExtractionCorrection",
                related_entity_id=correction_id,
                justification=decision.justification,
                model_version=decision.model_version,
                confidence_score=to_decimal_confidence(decision.confidence_score),
            )
