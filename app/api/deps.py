import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import oauth2_scheme
from app.auth.jwt_handler import TokenType, decode_token, TokenError
from app.core.database import get_db
from app.domain.models.identity.user import User, UserRole, Student, Professor, Admin
from app.domain.repositories.user_repository import SQLAlchemyUserRepository


async def get_current_user(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = await decode_token(token, expected_type=TokenType.ACCESS)
    except TokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("mfa_pending"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MFA pending. Veuillez compléter l'authentification MFA.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide : aucun sujet",
        )

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide : format de sujet incorrect",
        )

    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get_by_id(user_id)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utilisateur non trouvé",
        )

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)]
) -> User:
    """
    is_active câblé (gestion admin des comptes) — un token émis AVANT une
    désactivation reste signé valide jusqu'à son expiration naturelle
    (JWT stateless) ; cette vérification à CHAQUE requête authentifiée
    coupe l'accès immédiatement, pas seulement à la prochaine connexion
    (cf. UserService.authenticate, qui couvre le cas d'une NOUVELLE
    connexion sur un compte déjà désactivé).
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Compte désactivé",
        )
    return current_user


def require_role(*allowed_roles: UserRole):
    """
    Dependency factory pour vérifier si l'utilisateur possède l'un des rôles autorisés.
    """
    def role_checker(user: Annotated[User, Depends(get_current_active_user)]) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vous n'avez pas la permission d'accéder à cette ressource",
            )
        return user
    return role_checker


# Raccourcis pour les rôles fréquents
async def get_current_student(
    user: Annotated[User, Depends(require_role(UserRole.STUDENT))]
) -> Student:
    return user  # type: ignore


async def get_current_professor(
    user: Annotated[User, Depends(require_role(UserRole.PROFESSOR))]
) -> Professor:
    return user  # type: ignore


async def get_current_admin(
    user: Annotated[User, Depends(require_role(UserRole.ADMIN))]
) -> Admin:
    return user  # type: ignore


# --- Service Factories ---
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.repositories.audit_log_repository import SQLAlchemyAuditLogRepository
from app.domain.repositories.course_repository import SQLAlchemyCourseRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.enrollment_repository import SQLAlchemyEnrollmentRepository
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.feedback_repository import SQLAlchemyFeedbackRepository
from app.domain.repositories.grade_appeal_repository import SQLAlchemyGradeAppealRepository
from app.domain.repositories.correction_arbitration_repository import SQLAlchemyCorrectionArbitrationRepository
from app.domain.repositories.submission_incident_repository import SQLAlchemySubmissionIncidentRepository
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.reasoning_clarification_request_repository import SQLAlchemyReasoningClarificationRequestRepository
from app.domain.repositories.validated_alternative_answer_repository import SQLAlchemyValidatedAlternativeAnswerRepository
from app.domain.repositories.recommended_exercise_repository import SQLAlchemyRecommendedExerciseRepository
from app.domain.repositories.student_notebook_repository import SQLAlchemyStudentNotebookRepository
from app.domain.repositories.integrity_alert_repository import SQLAlchemyIntegrityAlertRepository
from app.domain.repositories.data_privacy_repository import SQLAlchemyDataPrivacyRepository
from app.domain.repositories.student_competency_profile_repository import SQLAlchemyStudentCompetencyProfileRepository
from app.domain.repositories.student_competency_observation_repository import SQLAlchemyStudentCompetencyObservationRepository
from app.domain.repositories.extraction_correction_repository import SQLAlchemyExtractionCorrectionRepository
from app.domain.repositories.agent_decision_log_repository import SQLAlchemyAgentDecisionLogRepository
from app.domain.repositories.student_feedback_report_repository import SQLAlchemyStudentFeedbackReportRepository

from app.services.user_service import UserService
from app.services.course_service import CourseService
from app.services.module_service import ModuleService
from app.services.program_service import ProgramService
from app.services.group_service import GroupService
from app.services.enrollment_service import EnrollmentService
from app.services.exercise_service import ExerciseService
from app.services.submission_service import SubmissionService
from app.services.evaluation_service import EvaluationService
from app.services.feedback_service import FeedbackService
from app.services.grade_appeal_service import GradeAppealService
from app.services.arbitration_service import ArbitrationService
from app.services.solution_variant_service import SolutionVariantService
from app.services.recommendation_service import RecommendationService
from app.services.integrity_service import IntegrityService
from app.services.data_privacy_service import DataPrivacyService
from app.services.audit_service import AuditService
from app.services.statistics_service import StatisticsService
from app.services.contestation_verification_service import ContestationVerificationService
from app.services.extraction_service import ExtractionService
from app.services.competency_assessment_service import CompetencyAssessmentService
from app.services.feedback_report_service import FeedbackReportService


def get_user_service(session: Annotated[AsyncSession, Depends(get_db)]) -> UserService:
    return UserService(
        user_repo=SQLAlchemyUserRepository(session),
        audit_repo=SQLAlchemyAuditLogRepository(session),
    )


def get_course_service(session: Annotated[AsyncSession, Depends(get_db)]) -> CourseService:
    return CourseService(
        course_repository=SQLAlchemyCourseRepository(session),
        module_repository=SQLAlchemyModuleRepository(session),
        user_repository=SQLAlchemyUserRepository(session),
        group_repository=SQLAlchemyGroupRepository(session),
        exercise_repository=SQLAlchemyExerciseRepository(session),
    )


def get_program_service(session: Annotated[AsyncSession, Depends(get_db)]) -> ProgramService:
    return ProgramService(
        program_repository=SQLAlchemyProgramRepository(session),
        module_repository=SQLAlchemyModuleRepository(session),
        group_repository=SQLAlchemyGroupRepository(session),
    )


def get_module_service(session: Annotated[AsyncSession, Depends(get_db)]) -> ModuleService:
    return ModuleService(
        module_repository=SQLAlchemyModuleRepository(session),
        enrollment_repository=SQLAlchemyEnrollmentRepository(session),
        program_repository=SQLAlchemyProgramRepository(session),
    )


def get_group_service(session: Annotated[AsyncSession, Depends(get_db)]) -> GroupService:
    return GroupService(
        group_repository=SQLAlchemyGroupRepository(session),
        user_repository=SQLAlchemyUserRepository(session),
        course_repository=SQLAlchemyCourseRepository(session),
        program_repository=SQLAlchemyProgramRepository(session),
    )


def get_enrollment_service(session: Annotated[AsyncSession, Depends(get_db)]) -> EnrollmentService:
    return EnrollmentService(
        enrollment_repository=SQLAlchemyEnrollmentRepository(session),
        user_repository=SQLAlchemyUserRepository(session),
        module_repository=SQLAlchemyModuleRepository(session),
        exercise_repository=SQLAlchemyExerciseRepository(session),
    )


def get_exercise_service(session: Annotated[AsyncSession, Depends(get_db)]) -> ExerciseService:
    return ExerciseService(
        exercise_repository=SQLAlchemyExerciseRepository(session),
        module_repository=SQLAlchemyModuleRepository(session),
        user_repository=SQLAlchemyUserRepository(session),
        clarification_repository=SQLAlchemyReasoningClarificationRequestRepository(session),
        solution_variant_repository=SQLAlchemySolutionVariantRepository(session),
        submission_repository=SQLAlchemySubmissionRepository(session),
    )


def get_submission_service(session: Annotated[AsyncSession, Depends(get_db)]) -> SubmissionService:
    return SubmissionService(
        submission_repo=SQLAlchemySubmissionRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
        course_repo=SQLAlchemyCourseRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
        enrollment_repo=SQLAlchemyEnrollmentRepository(session),
    )


def get_evaluation_service(session: Annotated[AsyncSession, Depends(get_db)]) -> EvaluationService:
    return EvaluationService(
        evaluation_repo=SQLAlchemyEvaluationRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
        extraction_correction_repo=SQLAlchemyExtractionCorrectionRepository(session),
        reasoning_clarification_repo=SQLAlchemyReasoningClarificationRequestRepository(session),
    )


def get_competency_assessment_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> CompetencyAssessmentService:
    return CompetencyAssessmentService(
        evaluation_repo=SQLAlchemyEvaluationRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
        observation_repo=SQLAlchemyStudentCompetencyObservationRepository(session),
        profile_repo=SQLAlchemyStudentCompetencyProfileRepository(session),
        module_repo=SQLAlchemyModuleRepository(session),
    )


def get_feedback_service(session: Annotated[AsyncSession, Depends(get_db)]) -> FeedbackService:
    return FeedbackService(
        feedback_repo=SQLAlchemyFeedbackRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
    )


def get_grade_appeal_service(session: Annotated[AsyncSession, Depends(get_db)]) -> GradeAppealService:
    return GradeAppealService(
        appeal_repo=SQLAlchemyGradeAppealRepository(session),
        evaluation_repo=SQLAlchemyEvaluationRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
    )


def get_arbitration_service(session: Annotated[AsyncSession, Depends(get_db)]) -> ArbitrationService:
    return ArbitrationService(
        arbitration_repo=SQLAlchemyCorrectionArbitrationRepository(session),
        incident_repo=SQLAlchemySubmissionIncidentRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
        integrity_repo=SQLAlchemyIntegrityAlertRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
        # Câblage teacher_arbitration_node (2026-08-18), cf. docstring
        # ArbitrationService.resolve_correction().
        extraction_correction_repo=SQLAlchemyExtractionCorrectionRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
    )


def get_solution_variant_service(session: Annotated[AsyncSession, Depends(get_db)]) -> SolutionVariantService:
    return SolutionVariantService(
        variant_repo=SQLAlchemySolutionVariantRepository(session),
        clarification_repo=SQLAlchemyReasoningClarificationRequestRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
        validated_answer_repo=SQLAlchemyValidatedAlternativeAnswerRepository(session),
    )


def get_recommendation_service(session: Annotated[AsyncSession, Depends(get_db)]) -> RecommendationService:
    return RecommendationService(
        recommendation_repo=SQLAlchemyRecommendedExerciseRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
        evaluation_repo=SQLAlchemyEvaluationRepository(session),
        student_notebook_repo=SQLAlchemyStudentNotebookRepository(session),
        profile_repo=SQLAlchemyStudentCompetencyProfileRepository(session),
        competency_assessment_service=get_competency_assessment_service(session),
    )


def get_feedback_report_service(session: Annotated[AsyncSession, Depends(get_db)]) -> FeedbackReportService:
    return FeedbackReportService(
        feedback_report_repo=SQLAlchemyStudentFeedbackReportRepository(session),
        competency_assessment_service=get_competency_assessment_service(session),
        recommendation_repo=SQLAlchemyRecommendedExerciseRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
    )


def get_integrity_service(session: Annotated[AsyncSession, Depends(get_db)]) -> IntegrityService:
    return IntegrityService(
        integrity_repo=SQLAlchemyIntegrityAlertRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
    )


def get_data_privacy_service(session: Annotated[AsyncSession, Depends(get_db)]) -> DataPrivacyService:
    from app.infra_services.storage_service import StorageService
    return DataPrivacyService(
        privacy_repo=SQLAlchemyDataPrivacyRepository(session),
        storage_service=StorageService(),
        user_repo=SQLAlchemyUserRepository(session),
    )


def get_audit_service(session: Annotated[AsyncSession, Depends(get_db)]) -> AuditService:
    return AuditService(
        audit_log_repo=SQLAlchemyAuditLogRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
    )


def get_statistics_service(session: Annotated[AsyncSession, Depends(get_db)]) -> StatisticsService:
    return StatisticsService(
        evaluation_repo=SQLAlchemyEvaluationRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
    )


def get_extraction_service(session: Annotated[AsyncSession, Depends(get_db)]) -> ExtractionService:
    return ExtractionService(
        extraction_repository=SQLAlchemyExtractionCorrectionRepository(session),
        submission_repository=SQLAlchemySubmissionRepository(session),
        correction_arbitration_repository=SQLAlchemyCorrectionArbitrationRepository(session),
    )


def get_contestation_verification_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> ContestationVerificationService:
    return ContestationVerificationService(
        extraction_correction_repo=SQLAlchemyExtractionCorrectionRepository(session),
        correction_arbitration_repo=SQLAlchemyCorrectionArbitrationRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
        solution_variant_repo=SQLAlchemySolutionVariantRepository(session),
        decision_log_repo=SQLAlchemyAgentDecisionLogRepository(session),
        integrity_alert_repo=SQLAlchemyIntegrityAlertRepository(session),
    )


from app.domain.repositories.teacher_correction_block_repository import SQLAlchemyTeacherCorrectionBlockRepository
from app.services.document_structuring_service import DocumentStructuringService
from app.services.decision_log_service import DecisionLogService


def get_document_structuring_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> DocumentStructuringService:
    return DocumentStructuringService(
        exercise_repository=SQLAlchemyExerciseRepository(session),
        teacher_correction_block_repository=SQLAlchemyTeacherCorrectionBlockRepository(session),
        agent_decision_log_repository=SQLAlchemyAgentDecisionLogRepository(session),
        job_repository=SQLAlchemyJobRepository(session),
    )


def get_decision_log_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> DecisionLogService:
    return DecisionLogService(
        agent_decision_log_repository=SQLAlchemyAgentDecisionLogRepository(session),
        exercise_repository=SQLAlchemyExerciseRepository(session),
        user_repository=SQLAlchemyUserRepository(session),
        session=session,
    )


from app.services.solution_variant_generation_service import SolutionVariantGenerationService


def get_solution_variant_generation_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> SolutionVariantGenerationService:
    # Session directe (pas de repository), même pattern que ReasoningGraphService
    # — cluster de services plus récents de ce projet, orchestration agent
    # directement sur AsyncSession plutôt que via une couche repository.
    return SolutionVariantGenerationService(session)


from app.domain.repositories.job_repository import SQLAlchemyJobRepository
from app.services.job_supervision_service import JobSupervisionService


def get_job_supervision_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> JobSupervisionService:
    return JobSupervisionService(
        job_repo=SQLAlchemyJobRepository(session),
        exercise_repo=SQLAlchemyExerciseRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
        user_repo=SQLAlchemyUserRepository(session),
    )


from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.services.job_retry_service import JobRetryService


def get_job_retry_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> JobRetryService:
    return JobRetryService(
        job_repo=SQLAlchemyJobRepository(session),
        submission_repo=SQLAlchemySubmissionRepository(session),
    )


from app.domain.repositories.model_configuration_repository import SQLAlchemyModelConfigurationRepository
from app.domain.repositories.provider_credential_repository import SQLAlchemyProviderCredentialRepository
from app.domain.repositories.system_config_override_repository import SQLAlchemySystemConfigOverrideRepository
from app.services.model_config_service import ModelConfigAdminService
from app.services.provider_credential_service import ProviderCredentialService
from app.services.system_config_service import SystemConfigService


def get_model_config_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> ModelConfigAdminService:
    return ModelConfigAdminService(model_config_repo=SQLAlchemyModelConfigurationRepository(session))


def get_system_config_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> SystemConfigService:
    return SystemConfigService(system_config_repo=SQLAlchemySystemConfigOverrideRepository(session))


def get_provider_credential_service(
    session: Annotated[AsyncSession, Depends(get_db)]
) -> ProviderCredentialService:
    return ProviderCredentialService(credential_repo=SQLAlchemyProviderCredentialRepository(session))


