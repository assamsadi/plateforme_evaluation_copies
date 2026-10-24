"""
Schemas Pydantic pour les 3 mécanismes d'arbitrage professoral :
CorrectionArbitration (cas AMBIGU du triage OCR), SubmissionIncident
(absence/incident technique), GradeAppeal (contestation de note).

Point commun de sécurité : les scores/verdicts "avant" (original_score,
etc.) ne sont JAMAIS fournis par le client dans les schemas *Create —
toujours dérivés côté service depuis l'état actuel en base, pour éviter
qu'un client falsifie la valeur de référence d'une contestation.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, model_validator

from app.domain.models.assessment.correction_arbitration import ArbitrationStatus, ArbitrationVerdict
from app.domain.models.assessment.extraction_correction import ContestationType
from app.domain.models.assessment.grade_appeal import AppealResolution
from app.domain.models.assessment.submission_incident import (
    IncidentCategory,
    IncidentResolution,
)
from app.domain.schemas.evaluation_schemas import ClassicCriterionObservedItem


# --- CorrectionArbitration ---

class CorrectionArbitrationCreate(BaseModel):
    verdict: ArbitrationVerdict
    comment: str | None = None
    # Ce que le professeur retient comme vérité — jamais limité aux deux
    # versions existantes, il peut saisir sa propre version (§9bis).
    claimed_correction: str | None = None


class CorrectionArbitrationRead(BaseModel):
    id: uuid.UUID
    extraction_correction_id: uuid.UUID
    status: ArbitrationStatus
    teacher_professor_id: uuid.UUID | None
    teacher_full_name: str | None  # aplati, None tant que PENDING
    verdict: ArbitrationVerdict | None
    comment: str | None
    claimed_correction: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class PendingCorrectionArbitrationRead(BaseModel):
    """
    File de découverte des corrections AMBIGUËS en attente d'un verdict
    (gap trouvé lors de l'audit arbitrage) — dénormalise le contexte
    nécessaire pour trancher sans requête supplémentaire côté client :
    ce que l'IA a lu (prediction_ocr) contre la correction humaine
    contestée (human_correction), avec l'image source.

    contestation_type + claimed_question_order (2026-09-05, gap réel trouvé
    en test) : le schéma ne portait QUE le cas CONTENT (transcription en
    cause) — pour une contestation ATTACHMENT (l'étudiant réclame que ce
    bloc appartient à telle question), human_correction est vide et le
    professeur ne voyait STRICTEMENT RIEN indiquant ce qui est réclamé, ni
    même quel type de contestation il devait trancher. claimed_question_order
    (pas l'UUID brut, jamais utile à l'affichage) résolu côté service.
    """
    arbitration_id: uuid.UUID
    extraction_correction_id: uuid.UUID
    submission_id: uuid.UUID
    student_id: uuid.UUID
    student_full_name: str
    exercise_id: uuid.UUID
    exercise_title: str
    question_id: uuid.UUID | None
    # ContestationType | None : la colonne DB est nullable (des lignes
    # antérieures à l'introduction de ce champ existent réellement, cf.
    # crash réel constaté 2026-09-05 — ValidationError sur une ligne legacy
    # à None). None traité côté UI comme le cas CONTENT par défaut.
    contestation_type: ContestationType | None
    claimed_question_order: int | None  # Cas ATTACHMENT uniquement
    prediction_ocr: str
    human_correction: str | None
    image_crop_url: str | None  # URL SAS résolue, jamais le blob_path brut
    # Copie complète de l'étudiant (PDF/image) — résolu depuis Submission.document_path
    # pour que le professeur puisse consulter la copie originale lors de l'arbitrage.
    document_url: str | None
    created_at: datetime
    # Traçabilité réelle (2026-09-06) : status/verdict/teacher_full_name
    # portent le VERDICT PERSISTÉ (jamais un état local frontend qui ne
    # survit pas à un rechargement de page) — status=RESOLVED + verdict
    # permettent d'afficher "Validé"/"Refusé" même après un refresh, sur
    # list_arbitrations_for_student (historique complet, cf. son docstring
    # service). Toujours PENDING/None sur list_pending_corrections_for_
    # professor (ne renvoie jamais que des PENDING).
    status: ArbitrationStatus
    verdict: ArbitrationVerdict | None
    teacher_full_name: str | None


class RetroactiveFairnessCandidate(BaseModel):
    """
    Un arbitrage AMBIGU encore en attente, sur la même question, avec un
    contenu très similaire à celui qui vient d'être tranché — proposé
    explicitement au professeur (§9quater), jamais appliqué à sa place.
    """
    arbitration_id: uuid.UUID
    extraction_correction_id: uuid.UUID
    similarity_score: float


# --- SubmissionIncident ---

class SubmissionIncidentCreate(BaseModel):
    exercise_id: uuid.UUID
    student_id: uuid.UUID  # explicite : un prof peut signaler pour un étudiant
    category: IncidentCategory
    incident_occurred_at: datetime | None = None
    reason: str
    attachment_path: str | None = None  # référence un blob déjà uploadé


class SubmissionIncidentResolutionRequest(BaseModel):
    resolution: IncidentResolution
    resolution_comment: str | None = None
    extended_deadline: datetime | None = None  # requis si resolution == DEADLINE_EXTENDED

    @model_validator(mode="after")
    def _require_extended_deadline_when_relevant(self) -> "SubmissionIncidentResolutionRequest":
        """
        Bug corrigé (audit espace professeur, même famille que
        GradeAppealResolutionRequest ci-dessus) : le commentaire annonçait
        déjà cette règle, jamais imposée — ArbitrationService.resolve_
        incident()/resolve_cluster() ne posent extended_deadline QUE s'il
        n'est pas None (`if extended_deadline is not None: ...`), donc une
        résolution DEADLINE_EXTENDED sans ce champ se persistait
        silencieusement SANS aucune date d'extension réelle.
        """
        if self.resolution == IncidentResolution.DEADLINE_EXTENDED and self.extended_deadline is None:
            raise ValueError(
                "extended_deadline est requis lorsque la résolution est DEADLINE_EXTENDED."
            )
        return self


class SubmissionIncidentRead(BaseModel):
    id: uuid.UUID
    exercise_id: uuid.UUID
    exercise_title: str  # aplati — nécessaire pour grouper les incidents par exercice côté UI (clustering)
    student_id: uuid.UUID
    student_full_name: str  # aplati
    reported_by_user_id: uuid.UUID
    parent_incident_id: uuid.UUID | None
    category: IncidentCategory
    incident_occurred_at: datetime | None
    reason: str
    attachment_url: str | None  # URL SAS résolue, jamais le blob_path brut
    status: str
    resolution: IncidentResolution | None
    resolution_comment: str | None
    resolved_by_professor_id: uuid.UUID | None
    resolved_at: datetime | None
    extended_deadline: datetime | None
    new_submission_id: uuid.UUID | None

    model_config = {"from_attributes": True}


# --- GradeAppeal ---

class GradeAppealCreate(BaseModel):
    """
    original_score n'est PAS fourni ici — le service le récupère depuis
    l'Evaluation actuelle au moment de la création, jamais depuis le
    client (sinon un étudiant pourrait prétendre à une note de départ
    fausse pour biaiser la contestation).
    """
    submission_id: uuid.UUID
    evaluation_id: uuid.UUID | None = None
    extraction_correction_id: uuid.UUID | None = None
    reason: str


class GradeAppealResolutionRequest(BaseModel):
    resolution: AppealResolution
    revised_score: Decimal | None = None  # requis si resolution != GRADE_UPHELD
    review_comment: str | None = None

    @model_validator(mode="after")
    def _require_revised_score_unless_upheld(self) -> "GradeAppealResolutionRequest":
        """
        Gap fermé (audit espace professeur) : le commentaire ci-dessus
        annonçait déjà cette règle, mais rien (schéma, service, repository)
        ne l'imposait réellement — une résolution GRADE_REVISED/PARTIAL_
        REVISION avec revised_score=None se persistait silencieusement.
        Le frontend bloquait déjà ce cas dans l'UI, mais aucune défense en
        profondeur n'existait côté API (appel direct, ou régression
        future du frontend).
        """
        if self.resolution != AppealResolution.GRADE_UPHELD and self.revised_score is None:
            raise ValueError(
                "revised_score est requis lorsque la résolution n'est pas GRADE_UPHELD."
            )
        return self


class GradeAppealRead(BaseModel):
    id: uuid.UUID
    submission_id: uuid.UUID
    evaluation_id: uuid.UUID | None
    extraction_correction_id: uuid.UUID | None
    student_id: uuid.UUID
    student_full_name: str  # aplati
    reason: str
    created_at: datetime
    original_score: Decimal
    status: str
    resolution: AppealResolution | None
    revised_score: Decimal | None
    resolved_by_professor_id: uuid.UUID | None
    resolved_by_professor_name: str | None  # aplati, None tant que non résolu
    review_comment: str | None
    resolved_at: datetime | None
    ai_reevaluation_score: Decimal | None
    ai_reevaluation_justification: str | None
    # Même structure que Evaluation.classic_criteria_observed — réutilise
    # ClassicCriterionObservedItem pour rester réellement comparable
    # critère par critère avec la notation initiale.
    ai_reevaluation_criteria: list[ClassicCriterionObservedItem] | None

    model_config = {"from_attributes": True}