"""
Schemas Pydantic pour la couche système/infrastructure : Job,
Notification, AuditLog (lecture seule, jamais de Create exposé — la
création est interne uniquement, via le service concerné), IntegrityAlert,
DataPrivacyRequest.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.models.system_infrastructure.agent_decision_log import ProfessorValidationStatus
from app.domain.models.system_infrastructure.audit_log import AuditSeverity
from app.domain.models.system_infrastructure.data_privacy_request import (
    PrivacyRequestType,
    PrivacyResolutionDetail,
)
from app.domain.models.system_infrastructure.integrity_alert import (
    IntegrityActionTaken,
    IntegrityAlertStatus,
    IntegrityTriggerType,
)
from app.domain.models.system_infrastructure.job import JobFlowType, JobStatus
from app.domain.models.system_infrastructure.notification import (
    NotificationChannel,
    NotificationPriority,
)
from app.model_registry.models import ModelProvider, TaskType


# --- Job ---

class JobRead(BaseModel):
    id: uuid.UUID
    exercise_id: uuid.UUID | None
    submission_id: uuid.UUID | None
    flow_type: JobFlowType
    status: JobStatus
    current_node: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    # Positionnés dynamiquement en mémoire par JobSupervisionService.get_overview
    # (aucune relation ORM Job -> Submission/Exercise/Student, cf. son
    # docstring) — jamais des colonnes, même pattern que SubmissionRead.
    exercise_title: str | None = None
    student_full_name: str | None = None

    model_config = {"from_attributes": True}


class JobsOverview(BaseModel):
    """
    Câblage JobSupervisionService.get_overview (supervision admin).
    counts_by_status expose TOUJOURS les 7 valeurs de JobStatus, à 0 si
    absentes (même contrat que StatisticsService.get_platform_stats —
    jamais une clé manquante devinée côté client). problematic_jobs =
    INTERRUPTED + FAILED + RETRYING (les 3 états qui méritent l'attention
    d'un admin), jamais RUNNING/PENDING (normaux) ni COMPLETED/CANCELLED
    (terminaux non problématiques).
    """
    counts_by_status: dict[str, int]
    recent_jobs: list[JobRead]
    problematic_jobs: list[JobRead]


# --- Notification ---

class NotificationRead(BaseModel):
    id: uuid.UUID
    content: str
    type: str
    channel: NotificationChannel
    priority: NotificationPriority
    related_entity_type: str | None
    related_entity_id: uuid.UUID | None
    action_url: str | None
    read_at: datetime | None
    expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationMarkReadRequest(BaseModel):
    read: bool = True


# --- AuditLog (lecture seule, jamais de Create exposé via API) ---

class AuditLogRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_full_name: str  # aplati
    entity_type: str
    entity_id: uuid.UUID
    # Nom/email lisible de l'entité visée, positionné dynamiquement en mémoire
    # par AuditService.list_logs — uniquement résolu pour entity_type="User"
    # à ce jour (aucune relation ORM générique entity_type -> table pour
    # résoudre les autres types sans un dispatch dédié par type).
    entity_label: str | None = None
    action: str
    diff: dict | None
    success: bool
    severity: AuditSeverity
    created_at: datetime

    # entry_hash volontairement PAS exposé côté API : c'est un mécanisme
    # interne de vérification d'intégrité, pas une donnée métier utile
    # au consommateur de l'API.

    model_config = {"from_attributes": True}


# --- IntegrityAlert ---

class IntegrityAlertRead(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    student_full_name: str  # aplati
    trigger_type: str
    auto_generated: bool
    evidence: dict
    reason: str
    status: IntegrityAlertStatus
    action_taken: IntegrityActionTaken | None
    reviewed_by_user_id: uuid.UUID | None
    review_notes: str | None
    reviewed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class IntegrityAlertReviewRequest(BaseModel):
    status: IntegrityAlertStatus
    action_taken: IntegrityActionTaken | None = None
    review_notes: str | None = None


class IntegrityManualFlagCreate(BaseModel):
    """
    Gap fermé (audit espace admin) : IntegrityService.flag_student()
    existait déjà, complète, mais aucun endpoint ne l'exposait — un
    professeur ou admin remarquant un comportement suspect n'avait aucun
    moyen de le signaler (cf. docstring module integrity_service.py,
    "signalement direct"). trigger_type restreint aux 3 déclencheurs
    manuels documentés (HIGH_REJECTION_RATE et SYSTEMATIC_CONTESTATION
    restent réservés à la génération automatique, cf. ArbitrationService.
    check_integrity / contestation_verification_service.py).
    """
    student_id: uuid.UUID
    trigger_type: IntegrityTriggerType
    reason: str
    evidence: dict | None = None

    @model_validator(mode="after")
    def _reject_auto_only_triggers(self) -> "IntegrityManualFlagCreate":
        if self.trigger_type in (
            IntegrityTriggerType.HIGH_REJECTION_RATE,
            IntegrityTriggerType.SYSTEMATIC_CONTESTATION,
        ):
            raise ValueError(
                f"{self.trigger_type.value} est réservé à la génération automatique, "
                "jamais un signalement manuel."
            )
        return self


# --- DataPrivacyRequest ---

class DataPrivacyRequestCreate(BaseModel):
    """user_id vient du contexte d'authentification, jamais du body."""
    request_type: PrivacyRequestType


class DataPrivacyRequestProcessRequest(BaseModel):
    """Traitement par un admin — identity_verified doit être True avant
    tout traitement (vérifié côté service, pas juste ce schema)."""
    resolution_detail: PrivacyResolutionDetail
    retention_or_rejection_reason: str | None = None


class DataPrivacyVerifyIdentityRequest(BaseModel):
    verification_method: str


class DataPrivacyCompleteErasureRequest(BaseModel):
    """resolution_detail EXPORTED est hors périmètre ici (aucun mécanisme
    de génération de fichier — cf. complete_export, non exposé côté admin)."""
    resolution_detail: PrivacyResolutionDetail
    reason: str | None = None


class DataPrivacyRejectRequest(BaseModel):
    reason: str


class DataPrivacyRequestRead(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_full_name: str
    request_type: PrivacyRequestType
    status: str
    legal_deadline: datetime
    identity_verified: bool
    processed_by_user_id: uuid.UUID | None
    processed_at: datetime | None
    resolution_detail: PrivacyResolutionDetail | None
    retention_or_rejection_reason: str | None
    export_file_url: str | None  # URL SAS résolue, jamais le blob_path brut
    export_file_expires_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- AgentDecisionLog ---

class AgentDecisionLogRead(BaseModel):
    id: uuid.UUID
    agent_name: str
    related_entity_type: str
    related_entity_id: uuid.UUID
    # Libellé lisible de l'entité visée, positionné dynamiquement en mémoire
    # par DecisionLogService.get_platform_decision_logs — couvre les 5 types
    # de related_entity_type existants (Exercise, Question, SolutionVariant,
    # TeacherCorrectionBlock, ExtractionCorrection).
    entity_label: str | None = None
    # Exercice parent, résolu séparément du libellé complet pour permettre un
    # regroupement par exercice côté écran "Décisions des agents IA" (gap
    # relevé en test réel : liste plate difficile à lire avec plusieurs
    # exercices mêlés). None si l'exercice référencé n'existe plus.
    exercise_id: uuid.UUID | None = None
    exercise_title: str | None = None
    input_summary: str | None = None
    output_summary: str | None = None
    justification: str
    confidence_score: Decimal | None = None
    model_version: str
    professor_validation_status: ProfessorValidationStatus
    professor_correction: str | None = None
    validated_by_professor_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- ModelConfiguration (chantier "Configuration des modèles IA") ---

class ModelConfigurationRead(BaseModel):
    """
    Configuration EFFECTIVE d'une tâche (base si surchargée, sinon repli
    _DEFAULT_REGISTRY_CONFIG) — jamais une vue partielle, toujours les 11
    TaskType présents (cf. ModelConfigAdminService.get_effective_config).
    temperature/max_tokens/supports_vision reflètent toujours l'entrée
    d'origine (jamais surchargeables, cf. docstring ModelRegistry).
    """
    task_type: TaskType
    provider: ModelProvider
    model_name: str
    timeout_seconds: int
    temperature: float
    max_tokens: int | None
    supports_vision: bool
    is_overridden: bool
    updated_at: datetime | None


class ModelConfigurationUpdate(BaseModel):
    provider: ModelProvider
    model_name: str = Field(min_length=1)
    timeout_seconds: int = Field(gt=0)


# --- SystemConfigOverride (seuils Settings, stockage/lecture — cf. docstring modèle) ---

class SettingOverrideRead(BaseModel):
    key: str
    value_type: str
    default_value: str
    override_value: str | None
    effective_value: str
    updated_at: datetime | None


class SettingOverrideUpdate(BaseModel):
    value: str = Field(min_length=1)


# --- ProviderCredential (secrets fournisseurs IA — clé/valeur libre, cf. docstring modèle) ---

class ProviderCredentialRead(BaseModel):
    """`value` volontairement ABSENT — jamais renvoyé par l'API une fois enregistré (cf. docstring modèle)."""
    key: str
    source: Literal["database", "environment", "unset"]
    is_wired: bool
    updated_at: datetime | None


class ProviderCredentialCreate(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1)


class ProviderCredentialUpdate(BaseModel):
    value: str = Field(min_length=1)