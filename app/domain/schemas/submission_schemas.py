"""
Schemas Pydantic pour Submission/ExtractionCorrection.

image_url (ExtractionCorrectionRead) : URL SAS déjà résolue par le
service (storage_service.generate_read_url()) avant la réponse — jamais
le chemin blob brut exposé à l'API. Une seule requête suffit pour que le
frontend affiche l'image, pas d'aller-retour supplémentaire.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator

from app.core.config import settings
from app.domain.models.assessment.correction_arbitration import ArbitrationVerdict
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ExtractionContentType,
    ExtractionEvidenceLevel,
    ExtractionOrigin,
    StructureType,
)
from app.domain.models.assessment.submission import SubmissionStatus


# --- Submission ---

class SubmissionCreate(BaseModel):
    """student_id vient du contexte d'authentification (token JWT), pas du body."""
    exercise_id: uuid.UUID


class SubmissionRead(BaseModel):
    id: uuid.UUID  # == thread_id LangGraph
    exercise_id: uuid.UUID
    exercise_title: str  # aplati
    student_id: uuid.UUID
    student_full_name: str  # aplati
    attempt_number: int
    status: SubmissionStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmissionSummaryRead(BaseModel):
    """
    Ligne de liste pour GET /exercises/{exercise_id}/submissions — gap
    trouvé lors de l'audit résultats professeur : SubmissionRepository.
    list_by_exercise existait déjà mais n'était exposé par AUCUN endpoint,
    un professeur n'avait aucun moyen de voir les copies déposées sur un
    de ses exercices. total_score=None tant que status != EVALUATED
    (jamais un 0 ambigu entre "pas encore noté" et "noté zéro" — la
    requête d'agrégation SQL renvoie 0 par COALESCE dans les deux cas,
    la distinction se fait ici via le statut, jamais deviné côté client).
    """
    id: uuid.UUID
    student_id: uuid.UUID
    student_full_name: str  # aplati
    attempt_number: int
    status: SubmissionStatus
    total_score: Decimal | None
    # Écran de détail de notation refondu (chantier "notation vivante") —
    # nécessaire pour un seuil de couleur PROPORTIONNEL (le barème total
    # varie par exercice, jamais une valeur absolue fixe type "/10").
    # Même repli que total_score : None tant que status != EVALUATED.
    max_score: Decimal | None = None
    created_at: datetime
    # Gap fermé (test réel 2026-08-31) : aucun écran professeur ne donnait
    # accès au document original déposé par l'étudiant (uniquement des
    # crops par bloc ailleurs, jamais le PDF/image complet). URL SAS
    # résolue par le service (storage_service.generate_read_url()) avant
    # la réponse, même convention que image_url ci-dessus — jamais le
    # blob_path brut exposé. None si aucun document (submission jamais
    # complétée) ou submission.document_path absent.
    document_url: str | None = None

    model_config = {"from_attributes": True}


# --- ExtractionCorrection ---

class RawExtractedBlock(BaseModel):
    """
    Bloc brut produit par OCR_Extraction_Agent v3 — pas encore rattaché à une question.
    Unité d'échange entre l'OCR Pipeline et les agents consommateurs.

    Pour content_type=STRUCTURE, origin/is_struck_through au niveau bloc sont des
    agrégats indicatifs ; la source de vérité est dans structured_output (par élément).
    """
    image_crop_path: str
    content_type: ExtractionContentType
    structure_type: StructureType | None = None
    prediction_ocr: str
    structured_output: dict | str | None = None
    confidence_score: Decimal
    reconstruction_confidence: Decimal | None = None
    bounding_box: dict
    page_number: int
    block_order_index: int
    student_label: str | None = None
    origin: ExtractionOrigin | None = None
    is_struck_through: bool = False
    evidence_level: ExtractionEvidenceLevel
    # Renseigné uniquement sur le bloc survivant d'une fusion de continuité
    # (Question_Attachment_Agent, étape -1) : image_crop_path des blocs
    # consommés par la fusion — nécessaire pour que Contestation_Verification_Agent
    # puisse retrouver et défusionner (Cas D), et pour ne plus laisser le
    # bloc consommé orphelin (question_id=None) en base.
    fused_crop_paths: list[str] | None = None


class AttachedExtractedBlock(RawExtractedBlock):
    """
    Bloc OCR après rattachement à une question par le Document_Structuring_Agent.
    Ajoute question_id (nullable si bloc ORPHELIN) et submission_id.
    """
    submission_id: uuid.UUID
    question_id: uuid.UUID | None = None  # None si evidence_level == ORPHELIN


class ExtractionCorrectionRead(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    question_id: uuid.UUID | None  # nullable : bloc peut être orphelin
    question_order: int | None  # None si question_id est None
    image_url: str  # URL SAS résolue, cf. docstring — PAS image_crop_path brut
    content_type: ExtractionContentType
    prediction_ocr: str
    structured_output: dict | None
    human_correction: str | None
    confidence_score: Decimal
    bounding_box: dict
    evidence_level: ExtractionEvidenceLevel
    # Ajouté pour GET .../corrections (vue étudiante, cf. ExtractionService.
    # list_corrections_for_submission) : sans ce champ, le frontend ne peut
    # pas distinguer un bloc jamais contesté d'un bloc déjà en cours de
    # vérification — nécessaire pour ne jamais permettre une confirmation
    # pendant qu'une contestation est encore en traitement (course possible :
    # filer une contestation ne change PAS submission.status tant qu'elle
    # n'escalade pas en arbitrage, cf. ExtractionService.contest_extraction).
    contestation_status: ContestationStatus | None = None
    # Traçabilité réelle (2026-09-06, bug signalé) : contestation_status=
    # RESOLVED est posé À L'IDENTIQUE que le professeur ait accepté ou
    # rejeté la réclamation (cf. commentaire create_and_apply_verdict,
    # correction_arbitration_repository.py — "confidence_score relevé et
    # contestation_status marqué RESOLVED dans les deux cas") : le frontend
    # affichait donc TOUJOURS le même badge générique "Signalement tranché
    # par l'enseignant", même sur un rejet. Le vrai verdict vit sur
    # CorrectionArbitration, jamais sur ExtractionCorrection — relayé ici.
    arbitration_verdict: ArbitrationVerdict | None = None
    # Bug trouvé en test réel (2026-08-30) : Contestation_Verification_Agent
    # écrit déjà verified_content sur verdict PLAUSIBLE (cf.
    # apply_contestation_verdict), mais ce champ n'était jamais exposé ici —
    # l'étudiant n'avait donc AUCUN moyen de voir le contenu corrigé, et le
    # badge frontend affichait "en cours de traitement" indéfiniment même
    # une fois le verdict rendu (cf. verify-extraction-dialog.tsx).
    verified_content: str | None = None
    # Même pattern que TeacherCorrectionBlockRead.is_low_ocr_confidence (B11)
    # — calculé ici (jamais stocké), même seuil settings.OCR_CONFIDENCE_
    # THRESHOLD, pour que la vue étudiante (verify-extraction) affiche un
    # badge cohérent avec le reste de l'app plutôt qu'un pourcentage brut.
    is_low_ocr_confidence: bool = False

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _compute_is_low_ocr_confidence(self) -> "ExtractionCorrectionRead":
        self.is_low_ocr_confidence = self.confidence_score < Decimal(str(settings.OCR_CONFIDENCE_THRESHOLD))
        return self


class SubmissionConfirmationRead(BaseModel):
    """
    Réponse de POST /submissions/{id}/confirm — la reprise du thread
    LangGraph (job_tasks.py::resume_thread) est déclenchée en Celery, donc
    asynchrone : status reste PENDING_STUDENT_VERIFICATION à l'instant de
    cette réponse, jamais un statut post-reprise deviné ici.
    """
    submission_id: uuid.UUID
    status: SubmissionStatus


class ExtractionCorrectionContestRequest(BaseModel):
    """
    HITL étudiant : signale une erreur d'extraction sur UNE correction
    précise. Déclenche correction_triage_node -> vlm_verification_agent
    (§4 du résumé — modèle indépendant de l'OCR initial).
    """
    claimed_correction: str