"""
Service Document_Structuring_Agent — orchestration de la persistance de la
structure d'un exercice (sections, questions) et du rattachement de sa
correction, à partir du StructuringReport produit par l'agent.

structure_exercise() :
  Point d'entrée unique appelé par le pipeline juste après
  Document_Structuring_Agent.execute(). Persiste, dans l'ordre (l'agent
  calcule, le service persiste) :
  1. Les ExerciseSection (report.sections_created) → UUID réels obtenus.
  2. Les Question (report.questions_created), sans Bareme à ce stade
     (bareme=None — produit plus tard par Extraction_Verification_Agent),
     chacune reliée à sa vraie ExerciseSection via section_id.
  3. Les TeacherCorrectionBlock (report.correction_blocks_created), dont
     le question_id est résolu via la clé composite (section_order,
     question_order) contre les Question réellement créées à l'étape 2 —
     jamais un identifiant fabriqué côté agent. Les blocs sans
     correspondance (UNRESOLVED_NO_LABEL) gardent question_id=None.

  Le verrou de complétude bloquant (StructuringIncompleteError si
  report.status == "INCOMPLETE") est levé par l'appelant
  (exercise_ocr_pipeline_service.run()) juste après l'appel à l'agent,
  pas ici — ce service persiste toujours ce que l'agent a déterminé,
  complet ou non, pour que le professeur voie l'état réel en base et
  puisse le corriger dans la même session (HITL immédiat, §13).

  4. Une AgentDecisionLog par bloc classifié (report.block_classifications
     — STATEMENT/CORRECTION/AUTRE confondus, §16). Aucun bloc n'a d'UUID
     propre au moment de la classification (RawExtractedBlock n'en porte
     pas), donc chaque ligne est rattachée à related_entity_type="Exercise"
     / related_entity_id=exercise_id — la seule référence réelle et stable
     disponible à ce stade du pipeline.
  5. Une AgentDecisionLog par appel LLM de regroupement en questions
     (report.question_grouping_decisions, cf. Document_Structuring_Agent.
     _partition_statement_blocks_into_questions) — jusqu'ici invisible a
     posteriori (contrairement à la classification bloc par bloc), rendant
     impossible de diagnostiquer une fusion à tort de plusieurs problèmes
     distincts en une seule Question sans relancer le document en test.
"""
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.agents.ocr_block_utils import to_decimal_confidence
from app.core.exceptions import (
    ExerciseNotFoundError,
    NotExerciseOwnerError,
    StructuringNotInterruptedError,
)
from app.domain.models.system_infrastructure.agent_decision_log import (
    ProfessorValidationStatus,
)
from app.domain.models.system_infrastructure.job import JobStatus
from app.domain.repositories.agent_decision_log_repository import (
    AgentDecisionLogRepositoryProtocol,
)
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.job_repository import JobRepositoryProtocol
from app.domain.repositories.teacher_correction_block_repository import (
    TeacherCorrectionBlockRepositoryProtocol,
)
from app.domain.models.assessment.teacher_correction_block import TeacherCorrectionBlock
from app.domain.schemas.teacher_correction_block_schemas import (
    BlockResolutionItem,
    TeacherCorrectionBlockRead,
)
from app.infra_services.storage_service import StorageContainer, StorageService

# process_job_resumed (app.tasks.job_tasks) est importé PAREsseusement, à
# l'intérieur des méthodes qui l'utilisent (jamais au niveau module) : un
# import direct ici crée un cycle réel — job_tasks.py -> pipeline_graph.py
# -> document_structuring_node.py -> exercise_ocr_pipeline_service.py ->
# CE module -> job_tasks.py (constaté à l'exécution : ImportError "partially
# initialized module"). Repoussé à l'appel, le cycle n'existe plus puisque
# tous les modules sont déjà pleinement chargés à ce moment.

# Valeur de reprise pour le pipeline exercise_setup en pause à
# await_structuring_resolution_node (cf. son docstring) — ce nœud ne fait
# qu'un interrupt() puis poursuit inconditionnellement une fois repris, la
# valeur elle-même n'est jamais interprétée mais NE DOIT JAMAIS être un dict
# (Command.resume traiterait alors ça comme un mapping id_interrupt->valeur,
# cf. job_tasks.py) — une chaîne simple suffit et documente l'origine dans
# les logs de reprise.
_STRUCTURING_RESUME_VALUE = "structuring_confirmed"

AGENT_NAME = "Document_Structuring_Agent"


@dataclass
class StructuringResult:
    """Résultat de structure_exercise() — reflète ce qui a été persisté."""
    exercise_id: uuid.UUID
    sections_created: int
    questions_created: int
    blocks_created: int
    complete: bool
    unresolved_block_ids: list[uuid.UUID]
    blocks: list[TeacherCorrectionBlockRead]


class StructuringReportLike(Protocol):
    """Sous-ensemble de StructuringReport réellement consommé par ce service."""
    status: str
    sections_created: list[dict]
    questions_created: list[dict]
    correction_blocks_created: list[dict]
    block_classifications: list[dict]
    question_grouping_decisions: list[dict]


class DocumentStructuringServiceProtocol(Protocol):
    async def structure_exercise(
        self,
        exercise_id: uuid.UUID,
        report: StructuringReportLike,
    ) -> StructuringResult: ...

    async def resolve_unresolved_blocks(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolutions: list[BlockResolutionItem],
    ) -> list[TeacherCorrectionBlockRead]: ...

    async def list_blocks_for_exercise(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
    ) -> list[TeacherCorrectionBlockRead]: ...

    async def confirm_structuring(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
    ) -> None: ...


class DocumentStructuringService:
    """
    Orchestrateur pour Document_Structuring_Agent.

    Injection :
    - exercise_repository : persiste ExerciseSection + Question sur l'exercice existant
    - teacher_correction_block_repository : persiste les blocs de correction rattachés
    - agent_decision_log_repository : trace chaque décision de classification
    - job_repository : lit/reprend le Job LangGraph en pause (confirm_structuring,
      et resolve_unresolved_blocks quand cette résolution suffit à débloquer) —
      optionnel (None) : l'instance interne construite par ExerciseOCRPipelineService
      n'appelle jamais ces deux méthodes (seule structure_exercise() lui sert),
      contrairement à l'instance exposée par l'API (app/api/deps.py), qui le
      fournit toujours. Garder ce paramètre requis aurait forcé à threader
      job_repository jusque dans ExerciseOCRPipelineService (et ses tests) pour
      un besoin qu'il n'a jamais.
    """

    def __init__(
        self,
        exercise_repository: ExerciseRepositoryProtocol,
        teacher_correction_block_repository: TeacherCorrectionBlockRepositoryProtocol,
        agent_decision_log_repository: AgentDecisionLogRepositoryProtocol,
        job_repository: JobRepositoryProtocol | None = None,
        storage_service: StorageService | None = None,
    ) -> None:
        self._exercises = exercise_repository
        self._blocks = teacher_correction_block_repository
        self._decision_logs = agent_decision_log_repository
        self._jobs = job_repository
        self._storage = storage_service or StorageService()

    def _to_block_read(self, block: TeacherCorrectionBlock) -> TeacherCorrectionBlockRead:
        """
        Résout image_crop_path (blob Azure) en URL SAS lisible — jamais le
        chemin brut exposé au client (même discipline que DataPrivacyService/
        export_file_url). Gap trouvé lors de l'audit authoring : la version
        précédente exposait directement le blob_path, inutilisable tel quel
        par un navigateur.
        """
        return TeacherCorrectionBlockRead(
            id=block.id,
            exercise_id=block.exercise_id,
            question_id=block.question_id,
            image_crop_url=(
                self._storage.generate_read_url(StorageContainer.EXERCISES, block.image_crop_path)
                if block.image_crop_path
                else None
            ),
            content_type=block.content_type,
            raw_text=block.raw_text,
            structured_content=block.structured_content,
            evidence_level=block.evidence_level,
            professor_resolution=block.professor_resolution,
            justification=block.justification,
            created_at=block.created_at,
            ocr_confidence=block.ocr_confidence,
        )

    async def structure_exercise(
        self,
        exercise_id: uuid.UUID,
        report: StructuringReportLike,
    ) -> StructuringResult:
        """
        Persiste la structure calculée par Document_Structuring_Agent :
        sections, questions, puis blocs de correction avec leur question_id
        réel (résolu via (section_order, question_order), jamais deviné).
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        _section_id_by_order, question_id_by_key = await self._exercises.add_structure(
            exercise_id=exercise_id,
            sections_data=report.sections_created,
            questions_data=report.questions_created,
        )

        blocks_data = []
        for item in report.correction_blocks_created:
            key = (item.get("section_order"), item.get("question_order"))
            question_id = question_id_by_key.get(key) if item.get("question_order") is not None else None
            blocks_data.append(
                {
                    "content_type": item["content_type"],
                    "evidence_level": item["evidence_level"],
                    "justification": item["justification"],
                    "question_id": question_id,
                    "image_crop_path": item.get("image_crop_path"),
                    "raw_text": item.get("raw_text"),
                    "structured_content": item.get("structured_content"),
                    "page_number": item.get("page_number"),
                    "block_order_index": item.get("block_order_index"),
                    "ocr_confidence": item.get("ocr_confidence"),
                }
            )

        created_blocks = await self._blocks.bulk_create_for_exercise(
            exercise_id=exercise_id,
            blocks=blocks_data,
        )

        unresolved = await self._blocks.list_unresolved_by_exercise(exercise_id)
        blocks_read = [self._to_block_read(b) for b in created_blocks]

        for block_classification in report.block_classifications:
            await self._decision_logs.create(
                agent_name=AGENT_NAME,
                related_entity_type="Exercise",
                related_entity_id=exercise_id,
                justification=block_classification["justification"],
                model_version=block_classification["model_used"] or "unknown",
                confidence_score=to_decimal_confidence(block_classification["confidence"]),
            )

        for grouping_decision in report.question_grouping_decisions:
            justification = (
                f"Regroupement en questions (section_order={grouping_decision['section_order']}, "
                f"C2PCT={grouping_decision['document_is_c2pct']}) : "
                f"{len(grouping_decision['representative_labels'])} bloc(s) représentant(s) envoyé(s) "
                f"au LLM, labels vus : {grouping_decision['representative_labels']}. "
                f"Appel LLM réussi : {grouping_decision['llm_call_succeeded']}. "
                f"Groupes RÉELLEMENT proposés par le LLM : {grouping_decision['llm_proposed_group_labels']}. "
                f"Nombre de groupes final (après filet de sécurité déterministe, "
                f"ne peut qu'augmenter) : {grouping_decision['final_group_count']}."
                + (
                    f" Erreur LLM (après retry) ayant déclenché le filet de sécurité : "
                    f"{grouping_decision['llm_error']}"
                    if grouping_decision.get("llm_error")
                    else ""
                )
            )
            await self._decision_logs.create(
                agent_name=AGENT_NAME,
                related_entity_type="Exercise",
                related_entity_id=exercise_id,
                justification=justification,
                model_version=grouping_decision["model_used"] or "unknown",
                confidence_score=None,
            )

        return StructuringResult(
            exercise_id=exercise_id,
            sections_created=len(report.sections_created),
            questions_created=len(report.questions_created),
            blocks_created=len(created_blocks),
            complete=(report.status == "COMPLETE"),
            unresolved_block_ids=[b.id for b in unresolved],
            blocks=blocks_read,
        )

    async def resolve_unresolved_blocks(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolutions: list[BlockResolutionItem],
    ) -> list[TeacherCorrectionBlockRead]:
        """
        Permet au professeur créateur d'associer manuellement un ou plusieurs blocs
        UNRESOLVED_NO_LABEL à une Question et de consigner professor_resolution.
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        updated_blocks = []
        for item in resolutions:
            block = await self._blocks.update_resolution(
                block_id=item.block_id,
                question_id=item.question_id,
                professor_resolution=item.professor_resolution,
            )
            if block is not None:
                updated_blocks.append(block)

                # Consigner la décision humaine
                await self._decision_logs.create(
                    agent_name=AGENT_NAME,
                    related_entity_type="TeacherCorrectionBlock",
                    related_entity_id=block.id,
                    justification=item.professor_resolution,
                    model_version="human_professor",
                )

        all_blocks = await self._blocks.list_by_exercise(exercise_id)

        # Débloque le pipeline exercise_setup en pause à await_structuring_
        # resolution_node (cf. son docstring) — sans cet appel, résoudre des
        # blocs ici met bien à jour la base mais ne le signale JAMAIS au
        # graph LangGraph, qui reste INTERRUPTED indéfiniment (gap trouvé en
        # test réel : aucun endpoint de ce routeur n'appelait process_job_
        # resumed, seuls les flux élève/contestation/arbitrage le font).
        # Best-effort : si aucun Job actif n'est en pause pour cet exercice
        # (ex. résolution proactive avant tout run, ou déjà repris), rien à
        # reprendre — jamais une erreur bloquante pour cette action déjà
        # persistée avec succès.
        await self._resume_if_interrupted(exercise_id)

        return [self._to_block_read(b) for b in all_blocks]

    async def confirm_structuring(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
    ) -> None:
        """
        Confirmation explicite par le professeur que la structuration
        (questions/sections/blocs déjà visibles en base) est correcte —
        reprend le pipeline en pause à await_structuring_resolution_node.

        Distinct de resolve_unresolved_blocks (qui reprend AUSSI le
        pipeline, cf. son docstring) : ce chemin couvre le cas où AUCUN
        bloc n'est UNRESOLVED_NO_LABEL (rien à corriger individuellement)
        mais le rapport de structuration a quand même été marqué INCOMPLETE
        pour une autre raison (conflit de label, section vide...) — sans
        cette méthode, ce cas n'avait strictement aucune action possible
        côté professeur (gap trouvé en test réel).
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        job = await self._jobs.get_active_job_for_thread(exercise_id) if self._jobs else None
        if job is None or job.status != JobStatus.INTERRUPTED:
            raise StructuringNotInterruptedError(exercise_id)

        from app.tasks.job_tasks import process_job_resumed

        process_job_resumed.delay(
            thread_id=str(exercise_id), resume_value=_STRUCTURING_RESUME_VALUE
        )

    async def _resume_if_interrupted(self, exercise_id: uuid.UUID) -> None:
        if self._jobs is None:
            return
        job = await self._jobs.get_active_job_for_thread(exercise_id)
        if job is not None and job.status == JobStatus.INTERRUPTED:
            from app.tasks.job_tasks import process_job_resumed

            process_job_resumed.delay(
                thread_id=str(exercise_id), resume_value=_STRUCTURING_RESUME_VALUE
            )

    async def list_blocks_for_exercise(
        self,
        exercise_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
    ) -> list[TeacherCorrectionBlockRead]:
        """
        Sans cet endpoint, le flux upload IA -> resolve-blocks est inutilisable :
        aucun client ne peut découvrir quels blocs existent ou nécessitent une
        résolution (list_by_exercise/list_unresolved_by_exercise n'étaient
        appelées qu'en interne par structure_exercise/resolve_unresolved_blocks,
        jamais exposées en lecture seule).
        """
        exercise = await self._exercises.get_by_id(exercise_id)
        if exercise is None:
            raise ExerciseNotFoundError(exercise_id)

        if exercise.created_by_professor_id != requesting_professor_id:
            raise NotExerciseOwnerError(exercise_id, requesting_professor_id)

        blocks = await self._blocks.list_by_exercise(exercise_id)
        return [self._to_block_read(b) for b in blocks]

