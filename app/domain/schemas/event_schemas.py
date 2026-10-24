"""
Schemas Pydantic des payloads d'événements Kafka — un schema par topic
défini dans app/core/kafka_client.py::KafkaTopic (aligné sur vos 12
fichiers docs/event-schema/*.json — à vérifier champ par champ contre
ces fichiers existants au moment de l'intégration, non lus ici).

L'enveloppe {"event_id": ..., "payload": ...} reste générique (gérée
dans kafka_client.py) — ici on type uniquement le contenu de "payload"
pour chaque type d'événement, validé avant publication et après
consommation.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.correction_arbitration import ArbitrationVerdict


class ExerciseCreatedPayload(BaseModel):
    exercise_id: uuid.UUID
    module_id: uuid.UUID
    created_by_professor_id: uuid.UUID


class ExercisePublishedPayload(BaseModel):
    exercise_id: uuid.UUID
    status: ExerciseStatus
    course_id: uuid.UUID | None
    deadline: datetime | None


class ExerciseArchivedToLibraryPayload(BaseModel):
    exercise_id: uuid.UUID
    module_id: uuid.UUID


class SubmissionCreatedPayload(BaseModel):
    submission_id: uuid.UUID
    exercise_id: uuid.UUID
    student_id: uuid.UUID
    attempt_number: int
    document_path: str
    mime_type: str


class ExtractionReadyPayload(BaseModel):
    submission_id: uuid.UUID
    question_id: uuid.UUID
    extraction_correction_id: uuid.UUID


class VariantsReadyPayload(BaseModel):
    question_id: uuid.UUID
    variant_ids: list[uuid.UUID]


class CorrectionTriagedPayload(BaseModel):
    extraction_correction_id: uuid.UUID
    verdict: str  # "plausible" | "implausible" | "ambigu" (triage, distinct d'ArbitrationVerdict)


class ArbitrationRequiredPayload(BaseModel):
    extraction_correction_id: uuid.UUID
    submission_id: uuid.UUID


class EvaluationCompletedPayload(BaseModel):
    submission_id: uuid.UUID
    question_id: uuid.UUID
    evaluation_id: uuid.UUID
    score: Decimal


class FeedbackRecordedPayload(BaseModel):
    feedback_id: uuid.UUID
    submission_id: uuid.UUID
    question_id: uuid.UUID


class RecommendationGeneratedPayload(BaseModel):
    """
    Câblage Recommendation_Agent (Kafka en notification pure, même décision
    actée que EvaluationCompletedPayload — jamais un déclencheur du
    pipeline). submission_id nullable : une génération peut ne pas être
    liée à UNE soumission précise (cf. docstring modèle RecommendedExercise),
    même principe que RecommendedExerciseRead.submission_id.
    """
    student_id: uuid.UUID
    module_id: uuid.UUID
    submission_id: uuid.UUID | None
    recommendation_count: int


class NotebookLMEnrichmentCompletedPayload(BaseModel):
    """
    Câblage NotebookLM (§7, Partie 2/2) — événement SÉPARÉ de
    RecommendationGeneratedPayload, jamais une extension de celui-ci :
    recommendation-generated.v1 se publie de façon synchrone au moment où
    les recommandations sont calculées (recommendation_node.py) ;
    l'enrichissement NotebookLM se termine minutes plus tard, de façon
    asynchrone (tâche Celery dédiée), avec un succès/échec indépendant par
    format — retarder ou republier l'événement existant casserait sa
    sémantique déjà testée. Publié une fois que l'audio et les flashcards
    ont chacun été TENTÉS (succès ou échec, cf. notebooklm_tasks.py) —
    jamais avant, jamais si le notebook lui-même n'a pas été créé (dans ce
    cas, aucun événement n'est publié du tout, cf. docstring tâche).
    """
    student_id: uuid.UUID
    module_id: uuid.UUID
    submission_id: uuid.UUID | None
    notebook_id: str
    audio_generated: bool
    flashcards_generated: bool


class JobFailedPayload(BaseModel):
    job_id: uuid.UUID
    thread_id: uuid.UUID
    error_message: str


class JobResumedPayload(BaseModel):
    job_id: uuid.UUID
    thread_id: uuid.UUID
    current_node: str