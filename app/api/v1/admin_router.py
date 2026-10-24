import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    get_audit_service,
    get_current_admin,
    get_decision_log_service,
    get_job_retry_service,
    get_job_supervision_service,
    get_model_config_service,
    get_provider_credential_service,
    get_statistics_service,
    get_system_config_service,
    get_user_service,
)
from app.domain.models.identity.user import Admin, UserRole
from app.domain.models.system_infrastructure.agent_decision_log import ProfessorValidationStatus
from app.domain.models.system_infrastructure.audit_log import AuditSeverity
from app.domain.repositories.pagination import CursorPage
from app.domain.schemas.auth_schemas import (
    AdminCreate,
    AdminUpdate,
    ProfessorCreate,
    ProfessorPublic,
    ProfessorUpdate,
    StudentCreate,
    StudentPublic,
    StudentUpdate,
    UserPublic,
)
from app.domain.schemas.system_schemas import (
    AgentDecisionLogRead,
    AuditLogRead,
    JobRead,
    JobsOverview,
    ModelConfigurationRead,
    ModelConfigurationUpdate,
    ProviderCredentialCreate,
    ProviderCredentialRead,
    ProviderCredentialUpdate,
    SettingOverrideRead,
    SettingOverrideUpdate,
)
from app.model_registry.models import TaskType
from app.services.audit_service import AuditService
from app.services.decision_log_service import DecisionLogService
from app.services.job_retry_service import JobRetryService
from app.services.job_supervision_service import JobSupervisionService
from app.services.model_config_service import ModelConfigAdminService
from app.services.provider_credential_service import ProviderCredentialService
from app.services.statistics_service import StatisticsService
from app.services.system_config_service import SystemConfigService
from app.services.user_service import UserService

# The get_current_admin dependency already enforces that the user has the ADMIN role
router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/users/admins", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def create_admin(
    schema: AdminCreate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    Crée un nouvel administrateur. Accessible uniquement aux administrateurs existants.
    """
    try:
        return await user_service.register_admin(schema)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/users/professors", response_model=ProfessorPublic, status_code=status.HTTP_201_CREATED)
async def create_professor(
    schema: ProfessorCreate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    Crée un compte professeur. Accessible uniquement aux administrateurs.
    """
    try:
        return await user_service.register_professor(schema)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/users/students", response_model=StudentPublic, status_code=status.HTTP_201_CREATED)
async def create_student_as_admin(
    schema: StudentCreate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    Crée un compte étudiant depuis l'admin (même logique que l'auto-
    inscription publique /auth/register/student, réutilisée telle quelle
    — aucune différence de création entre les deux chemins). Nécessaire
    pour le workflow "changement de rôle" (désactiver l'ancien compte +
    créer le nouveau avec le bon rôle, cf. plan) : sans cet endpoint,
    un admin ne pouvait créer que des professeurs/admins, jamais un
    étudiant, rendant "changer vers étudiant" impossible côté admin.
    """
    try:
        return await user_service.register_student(schema)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/users", response_model=CursorPage[UserPublic])
async def list_users(
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
    cursor: str | None = None,
    limit: int = 50,
    role: UserRole | None = None,
):
    """Liste paginée de tous les utilisateurs (tous rôles), filtrable par rôle."""
    return await user_service.list_users(cursor=cursor, limit=limit, role=role)


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: uuid.UUID,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> UserPublic | ProfessorPublic | StudentPublic:
    """
    Détail d'un utilisateur avec les champs spécifiques à son rôle
    (department/title pour un professeur, student_number/group_id pour un
    étudiant) — GET /admin/users renvoie UserPublic (champs de base
    uniquement) pour rester léger sur la liste ; ce endpoint complète pour
    les besoins d'édition.
    """
    try:
        return await user_service.get_user_detail(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/users/admins/{user_id}", response_model=UserPublic)
async def update_admin(
    user_id: uuid.UUID,
    schema: AdminUpdate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        return await user_service.update_admin(user_id, schema)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/users/professors/{user_id}", response_model=ProfessorPublic)
async def update_professor(
    user_id: uuid.UUID,
    schema: ProfessorUpdate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        return await user_service.update_professor(user_id, schema)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/users/students/{user_id}", response_model=StudentPublic)
async def update_student(
    user_id: uuid.UUID,
    schema: StudentUpdate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        return await user_service.update_student(user_id, schema)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/users/{user_id}/deactivate", response_model=UserPublic)
async def deactivate_user(
    user_id: uuid.UUID,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    """
    Bloque l'authentification du compte (nouvelles connexions ET tokens
    déjà émis, cf. UserService.authenticate/get_current_active_user).
    Garde-fou : un admin ne peut jamais se désactiver lui-même (vérifié
    dans le service).
    """
    try:
        return await user_service.deactivate_account(user_id, acting_admin_id=current_admin.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/users/{user_id}/reactivate", response_model=UserPublic)
async def reactivate_user(
    user_id: uuid.UUID,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    user_service: Annotated[UserService, Depends(get_user_service)],
):
    try:
        return await user_service.reactivate_account(user_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/statistics/platform")
async def get_platform_statistics(
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    stats_service: Annotated[StatisticsService, Depends(get_statistics_service)],
) -> dict[str, Any]:
    """
    Statistiques à l'échelle de toute la plateforme — utilisateurs par
    rôle, exercices par statut, soumissions par statut, taux de réussite
    moyen (cf. docstring StatisticsService.get_platform_stats).
    """
    return await stats_service.get_platform_stats()


@router.get("/jobs/overview", response_model=JobsOverview)
async def get_jobs_overview(
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    job_supervision_service: Annotated[JobSupervisionService, Depends(get_job_supervision_service)],
):
    """
    Vue d'ensemble des Job — comptage par statut (7 valeurs, toujours
    présentes, 0 si absentes) + activité récente + jobs problématiques
    (INTERRUPTED/FAILED/RETRYING). Lecture seule — pour relancer un Job
    FAILED, cf. POST /jobs/{job_id}/retry (job_retry_service.py, jamais
    exposé ici — cf. son docstring pour le pourquoi de la séparation).
    """
    return await job_supervision_service.get_overview()


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job_detail(
    job_id: uuid.UUID,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    job_supervision_service: Annotated[JobSupervisionService, Depends(get_job_supervision_service)],
):
    """Détail d'un Job précis — distinct de GET /jobs/submission/{id} (accessible à tout utilisateur authentifié, retourne SubmissionRead, pas Job)."""
    return await job_supervision_service.get_job_detail(job_id)


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
async def retry_job(
    job_id: uuid.UUID,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    job_retry_service: Annotated[JobRetryService, Depends(get_job_retry_service)],
):
    """
    Relance manuelle d'un Job FAILED — gap trouvé en test réel (2026-08-30) :
    Celery épuise déjà 5 retries automatiques avant de marquer FAILED, mais
    au-delà, rien ne relançait jamais la soumission sans intervention d'un
    développeur. Uniquement STUDENT_EVALUATION pour l'instant (cf. docstring
    job_retry_service.py) — 409 explicite pour EXERCISE_SETUP ou tout Job
    pas en statut FAILED, jamais une relance silencieusement incorrecte.
    """
    return await job_retry_service.retry_job(job_id)


@router.get("/agent-decisions", response_model=CursorPage[AgentDecisionLogRead])
async def list_agent_decisions(
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    decision_log_service: Annotated[DecisionLogService, Depends(get_decision_log_service)],
    cursor: str | None = None,
    limit: int = 50,
    agent_name: str | None = None,
    professor_validation_status: ProfessorValidationStatus | None = None,
):
    """
    Vue transverse des décisions IA (pas scopée par exercice, contrairement
    à GET /exercises/{id}/decision-logs). Pas de filtre "severity" : ce
    champ n'existe pas sur AgentDecisionLog (vérifié) — professor_
    validation_status est le proxy le plus proche d'un type de décision à
    surveiller (CORRECTED = le professeur a dû rectifier la décision).
    """
    return await decision_log_service.get_platform_decision_logs(
        agent_name=agent_name,
        professor_validation_status=professor_validation_status,
        cursor=cursor,
        limit=limit,
    )


@router.get("/audit-logs", response_model=CursorPage[AuditLogRead])
async def list_audit_logs(
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    audit_service: Annotated[AuditService, Depends(get_audit_service)],
    cursor: str | None = None,
    limit: int = 50,
    entity_type: str | None = None,
    user_id: uuid.UUID | None = None,
    severity: AuditSeverity | None = None,
    action: str | None = None,
):
    """
    Journal d'audit des actions humaines (créations, modifications,
    désactivations...), distinct de /admin/agent-decisions qui trace les
    décisions de l'IA. Trié du plus récent au plus ancien.
    """
    return await audit_service.list_logs(
        cursor=cursor,
        limit=limit,
        entity_type=entity_type,
        user_id=user_id,
        severity=severity,
        action=action,
    )


@router.get("/config/models", response_model=list[ModelConfigurationRead])
async def get_model_configurations(
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    model_config_service: Annotated[ModelConfigAdminService, Depends(get_model_config_service)],
):
    """
    Configuration EFFECTIVE actuelle par TaskType (base si surchargée,
    sinon repli sur _DEFAULT_REGISTRY_CONFIG codé en dur) — lecture
    toujours fraîche, jamais via le cache TTL utilisé par le chemin
    d'appel LLM (cf. docstring ModelConfigAdminService).
    """
    return await model_config_service.get_effective_config()


@router.put("/config/models/{task_type}", response_model=ModelConfigurationRead)
async def update_model_configuration(
    task_type: TaskType,
    schema: ModelConfigurationUpdate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    model_config_service: Annotated[ModelConfigAdminService, Depends(get_model_config_service)],
):
    """
    Surcharge l'entrée PRIMAIRE de la chaîne pour cette tâche (le repli
    reste inchangé, jamais retiré). task_type/provider invalides sont déjà
    rejetés en 422 par la validation Pydantic (enums) avant d'atteindre ce
    routeur — jamais une valeur hors énumération acceptée silencieusement.
    Effet pris en compte au prochain appel LLM sous _DEFAULT_CACHE_TTL_
    SECONDS (30s), immédiatement dans CE processus (invalidate_cache()).
    """
    return await model_config_service.update_model_config(
        task_type=task_type, provider=schema.provider,
        model_name=schema.model_name, timeout_seconds=schema.timeout_seconds,
    )


@router.get("/config/settings", response_model=list[SettingOverrideRead])
async def get_system_config_settings(
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    system_config_service: Annotated[SystemConfigService, Depends(get_system_config_service)],
):
    """
    Seuils Settings configurables (allowlist codée en dur, cf.
    app/services/system_config_service.py) — stockage/lecture SEULEMENT,
    PAS câblé dans les agents/services qui lisent settings.X aujourd'hui
    (limite documentée, décision actée : seul model_registry a un effet
    vivant sur le prochain appel LLM).
    """
    return await system_config_service.get_all_settings()


@router.put("/config/settings/{key}", response_model=SettingOverrideRead)
async def update_system_config_setting(
    key: str,
    schema: SettingOverrideUpdate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    system_config_service: Annotated[SystemConfigService, Depends(get_system_config_service)],
):
    """Clé hors allowlist ou valeur invalide (échec de cast, négative) -> 400 explicite, jamais persisté silencieusement."""
    try:
        return await system_config_service.update_setting(key, schema.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/config/credentials", response_model=list[ProviderCredentialRead])
async def get_provider_credentials(
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    provider_credential_service: Annotated[ProviderCredentialService, Depends(get_provider_credential_service)],
):
    """
    Secrets fournisseurs IA (clé API, config Langfuse) — jamais `value`
    dans la réponse (cf. docstring ProviderCredentialRead). SANS
    allowlist fermée (contrairement à /config/settings) : la liste
    inclut les clés déjà en base ET quelques clés connues de .env même
    non surchargées, mais l'admin peut en ajouter d'autres via POST.
    """
    return await provider_credential_service.list_credentials()


@router.post("/config/credentials", response_model=ProviderCredentialRead, status_code=status.HTTP_201_CREATED)
async def create_provider_credential(
    schema: ProviderCredentialCreate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    provider_credential_service: Annotated[ProviderCredentialService, Depends(get_provider_credential_service)],
):
    """Nom de clé déjà existant -> 400 explicite (utiliser PUT pour remplacer une valeur)."""
    try:
        return await provider_credential_service.create_credential(schema.key, schema.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/config/credentials/{key}", response_model=ProviderCredentialRead)
async def update_provider_credential(
    key: str,
    schema: ProviderCredentialUpdate,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    provider_credential_service: Annotated[ProviderCredentialService, Depends(get_provider_credential_service)],
):
    return await provider_credential_service.set_credential(key, schema.value)


@router.delete("/config/credentials/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_credential(
    key: str,
    current_admin: Annotated[Admin, Depends(get_current_admin)],
    provider_credential_service: Annotated[ProviderCredentialService, Depends(get_provider_credential_service)],
):
    """Efface la surcharge DB — retombe sur .env si présent, sinon "non configuré"."""
    await provider_credential_service.clear_credential(key)

