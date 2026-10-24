"""
Pipeline OCR pour le document de référence professeur (énoncé + correction).

Orchestration end-to-end :
  1. Téléchargement du scan depuis Azure
  2. OCR_Extraction_Agent v3 (upload des crops Azure, flow exercise_setup)
  3. Document_Structuring_Agent (structuration logique)
  4. Persistance de la structure (sections, questions, TeacherCorrectionBlock)
  5. Verrou bloquant immédiat (StructuringIncompleteError) si l'agent a
     produit un rapport INCOMPLETE — premier des deux verrous du pipeline.
     Le second, IncompleteExerciseSetupError (barème + variante de
     référence manquants), n'intervient que plus tard, à publish().
"""
from __future__ import annotations

import logging
import uuid

from app.agents.context import AgentExecutionContext
from app.agents.Document_Structuring_Agent import DocumentStructuringAgent, StructuringReport
from app.agents.document_structuring_exceptions import StructuringIncompleteError
from app.agents.OCR_Extraction_Agent import OCRExtractionAgent
from app.core.exceptions import ExerciseNotFoundError, OCRExtractionError
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.repositories.agent_decision_log_repository import (
    SQLAlchemyAgentDecisionLogRepository,
)
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.teacher_correction_block_repository import (
    SQLAlchemyTeacherCorrectionBlockRepository,
)
from app.domain.schemas.submission_schemas import RawExtractedBlock
from app.infra_services.storage_service import StorageContainer, storage_service
from app.services.document_structuring_service import DocumentStructuringService

logger = logging.getLogger(__name__)


class ExerciseOCRPipelineService:
    def __init__(
        self,
        exercise_repo: SQLAlchemyExerciseRepository,
        teacher_block_repo: SQLAlchemyTeacherCorrectionBlockRepository,
        decision_log_repo: SQLAlchemyAgentDecisionLogRepository,
        ocr_agent: OCRExtractionAgent | None = None,
        structuring_agent: DocumentStructuringAgent | None = None,
        structuring_service: DocumentStructuringService | None = None,
    ) -> None:
        self._exercises = exercise_repo
        self._teacher_blocks = teacher_block_repo
        self._ocr_agent = ocr_agent or OCRExtractionAgent()
        self._structuring_agent = structuring_agent or DocumentStructuringAgent()
        self._structuring_service = structuring_service or DocumentStructuringService(
            exercise_repository=exercise_repo,
            teacher_correction_block_repository=teacher_block_repo,
            agent_decision_log_repository=decision_log_repo,
        )

    async def run(
        self,
        exercise_id: uuid.UUID,
        professor_id: uuid.UUID,
        document_path: str,
        mime_type: str,
        trace_id: str | None = None,
    ) -> tuple[list[RawExtractedBlock], StructuringReport]:
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != professor_id:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.status != ExerciseStatus.DRAFT:
            raise OCRExtractionError(
                f"L'exercice {exercise_id} doit être en DRAFT pour le traitement OCR"
            )

        document_bytes = await storage_service.download(
            StorageContainer.EXERCISES,
            document_path,
        )

        context = AgentExecutionContext(
            trace_id=trace_id or str(exercise_id),
            flow_type="exercise_setup",
            exercise_id=exercise_id,
            user_id=professor_id,
        )

        raw_blocks = await self._ocr_agent.execute(
            document_bytes=document_bytes,
            mime_type=mime_type,
            context=context,
        )

        report = await self._structuring_agent.execute(
            raw_blocks=raw_blocks,
            exercise_status=exercise.status,
            context=context,
        )

        # Persiste toujours ce que l'agent a déterminé (complet ou non) : le
        # professeur doit voir l'état réel en base pour le corriger dans la
        # même session (§13, HITL immédiat) — la structuration en base n'est
        # jamais conditionnée à report.status.
        await self._structuring_service.structure_exercise(
            exercise_id=exercise_id,
            report=report,
        )

        logger.info(
            "Pipeline OCR professeur terminé pour exercise_id=%s (%d blocs OCR, status=%s)",
            exercise_id,
            len(raw_blocks),
            report.status,
        )

        if report.status == "INCOMPLETE":
            raise StructuringIncompleteError(
                exercise_id=exercise_id,
                unresolved_blocks=report.unresolved_block_count,
                questions_without_correction=report.questions_without_correction_count,
                label_conflicts=report.label_conflict_count,
                empty_sections=report.empty_section_count,
            )

        return raw_blocks, report
