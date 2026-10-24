# Academic
from app.domain.models.academic.course import Course
from app.domain.models.academic.enrollment import Enrollment
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program

# Assessment
from app.domain.models.assessment.bareme import Bareme
from app.domain.models.assessment.correction_arbitration import CorrectionArbitration
from app.domain.models.assessment.evaluated_variant_candidate import EvaluatedVariantCandidate
from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.evaluation_criteria import EvaluationCriteria
from app.domain.models.assessment.exercise import Exercise
from app.domain.models.assessment.exercise_section import ExerciseSection
from app.domain.models.assessment.extraction_correction import ExtractionCorrection
from app.domain.models.assessment.feedback import Feedback
from app.domain.models.assessment.feedback_version import FeedbackVersion
from app.domain.models.assessment.grade_appeal import GradeAppeal
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import ReasoningClarificationRequest
from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepDependency
from app.domain.models.assessment.recommended_exercise import RecommendedExercise
from app.domain.models.assessment.solution_variant import SolutionVariant
from app.domain.models.assessment.student_notebook import StudentNotebook
from app.domain.models.assessment.submission import Submission
from app.domain.models.assessment.submission_incident import SubmissionIncident
from app.domain.models.assessment.teacher_correction_block import TeacherCorrectionBlock
from app.domain.models.assessment.validated_alternative_answer import ValidatedAlternativeAnswer

# Competency
from app.domain.models.competency.student_competency_observation import StudentCompetencyObservation
from app.domain.models.competency.student_competency_profile import StudentCompetencyProfile

# Identity
from app.domain.models.identity.user import User, Student, Professor, Admin
from app.domain.models.identity.mfa_device import MFADevice

# System Infrastructure
from app.domain.models.system_infrastructure.agent_decision_log import AgentDecisionLog
from app.domain.models.system_infrastructure.audit_log import AuditLog
from app.domain.models.system_infrastructure.data_privacy_request import DataPrivacyRequest
from app.domain.models.system_infrastructure.integrity_alert import IntegrityAlert
from app.domain.models.system_infrastructure.job import Job
from app.domain.models.system_infrastructure.model_configuration import ModelConfiguration
from app.domain.models.system_infrastructure.notification import Notification
from app.domain.models.system_infrastructure.processed_event import ProcessedEvent
from app.domain.models.system_infrastructure.provider_credential import ProviderCredential
from app.domain.models.system_infrastructure.system_config_override import SystemConfigOverride

__all__ = [
    # Academic
    "Course",
    "Enrollment",
    "Group",
    "Module",
    "Program",
    # Assessment
    "Bareme",
    "CorrectionArbitration",
    "EvaluatedVariantCandidate",
    "Evaluation",
    "EvaluationCriteria",
    "Exercise",
    "ExerciseSection",
    "ExtractionCorrection",
    "Feedback",
    "FeedbackVersion",
    "GradeAppeal",
    "Question",
    "ReasoningClarificationRequest",
    "ReasoningStep",
    "ReasoningStepDependency",
    "RecommendedExercise",
    "SolutionVariant",
    "Submission",
    "SubmissionIncident",
    "TeacherCorrectionBlock",
    "ValidatedAlternativeAnswer",
    # Competency
    "StudentCompetencyObservation",
    "StudentCompetencyProfile",
    # Identity
    "User",
    "Student",
    "Professor",
    "Admin",
    "MFADevice",
    # System Infrastructure
    "AgentDecisionLog",
    "AuditLog",
    "DataPrivacyRequest",
    "IntegrityAlert",
    "Job",
    "ModelConfiguration",
    "Notification",
    "ProcessedEvent",
    "ProviderCredential",
    "SystemConfigOverride",
]
