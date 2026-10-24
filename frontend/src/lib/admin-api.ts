import { AuthApiError, type UserPublic } from "@/lib/auth-api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // réponse non-JSON — laisse le message générique ci-dessous
  }
  return `Erreur ${response.status}`;
}

function authHeaders(accessToken: string): HeadersInit {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${accessToken}`,
  };
}

export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

export type UserRole = "student" | "professor" | "admin";

export async function listUsers(
  accessToken: string,
  options: { cursor?: string; limit?: number; role?: UserRole } = {},
): Promise<CursorPage<UserPublic>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.role) params.set("role", options.role);

  const response = await fetch(`${API_URL}/admin/users?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function deactivateUser(accessToken: string, userId: string): Promise<UserPublic> {
  const response = await fetch(`${API_URL}/admin/users/${userId}/deactivate`, {
    method: "PATCH",
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function reactivateUser(accessToken: string, userId: string): Promise<UserPublic> {
  const response = await fetch(`${API_URL}/admin/users/${userId}/reactivate`, {
    method: "PATCH",
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

interface UserCreateBase {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
}

export type AdminCreatePayload = UserCreateBase;

export interface ProfessorCreatePayload extends UserCreateBase {
  department: string;
  title: string;
  employee_number: string;
  office_location?: string;
  specialty?: string;
}

export interface StudentCreatePayload extends UserCreateBase {
  student_number: string;
  group_id: string;
  enrollment_year: number;
  level: string;
}

async function postJson<T>(accessToken: string, path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export function createAdmin(accessToken: string, payload: AdminCreatePayload): Promise<UserPublic> {
  return postJson(accessToken, "/admin/users/admins", payload);
}

export function createProfessor(accessToken: string, payload: ProfessorCreatePayload): Promise<UserPublic> {
  return postJson(accessToken, "/admin/users/professors", payload);
}

export function createStudent(accessToken: string, payload: StudentCreatePayload): Promise<UserPublic> {
  return postJson(accessToken, "/admin/users/students", payload);
}

export interface StudentDetail extends UserPublic {
  student_number: string;
  group_id: string;
  enrollment_year: number;
  level: string;
}

export interface ProfessorDetail extends UserPublic {
  department: string;
  title: string;
  employee_number: string;
  office_location: string | null;
  specialty: string | null;
}

export type UserDetail = UserPublic | ProfessorDetail | StudentDetail;

export async function getUserDetail(accessToken: string, userId: string): Promise<UserDetail> {
  const response = await fetch(`${API_URL}/admin/users/${userId}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

async function patchJson<T>(accessToken: string, path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "PATCH",
    headers: authHeaders(accessToken),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export type AdminUpdatePayload = Omit<AdminCreatePayload, "password">;
export type ProfessorUpdatePayload = Omit<ProfessorCreatePayload, "password">;
export type StudentUpdatePayload = Omit<StudentCreatePayload, "password">;

export function updateAdmin(accessToken: string, userId: string, payload: AdminUpdatePayload): Promise<UserPublic> {
  return patchJson(accessToken, `/admin/users/admins/${userId}`, payload);
}

export function updateProfessor(
  accessToken: string,
  userId: string,
  payload: ProfessorUpdatePayload,
): Promise<ProfessorDetail> {
  return patchJson(accessToken, `/admin/users/professors/${userId}`, payload);
}

export function updateStudent(
  accessToken: string,
  userId: string,
  payload: StudentUpdatePayload,
): Promise<StudentDetail> {
  return patchJson(accessToken, `/admin/users/students/${userId}`, payload);
}

export interface ProgramRead {
  id: string;
  name: string;
  code: string;
}

export interface GroupRead {
  id: string;
  label: string;
  academic_year: string;
  program_id: string;
  program_name: string;
}

export async function listPrograms(accessToken: string): Promise<CursorPage<ProgramRead>> {
  const response = await fetch(`${API_URL}/programs?limit=200`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function listGroupsByProgram(accessToken: string, programId: string): Promise<CursorPage<GroupRead>> {
  const response = await fetch(`${API_URL}/programs/${programId}/groups?limit=200`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

async function deleteResource(accessToken: string, path: string): Promise<void> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }
}

export interface ProgramCreatePayload {
  name: string;
  code: string;
}

export function createProgram(accessToken: string, payload: ProgramCreatePayload): Promise<ProgramRead> {
  return postJson(accessToken, "/programs", payload);
}

export function deleteProgram(accessToken: string, programId: string): Promise<void> {
  return deleteResource(accessToken, `/programs/${programId}`);
}

export interface ProgramUpdatePayload {
  name: string;
  code: string;
}

export function updateProgram(
  accessToken: string,
  programId: string,
  payload: ProgramUpdatePayload,
): Promise<ProgramRead> {
  return patchJson(accessToken, `/programs/${programId}`, payload);
}

export async function getProgram(accessToken: string, programId: string): Promise<ProgramRead> {
  const response = await fetch(`${API_URL}/programs/${programId}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface GroupCreatePayload {
  program_id: string;
  label: string;
  academic_year: string;
}

export function createGroup(accessToken: string, programId: string, payload: GroupCreatePayload): Promise<GroupRead> {
  return postJson(accessToken, `/programs/${programId}/groups`, payload);
}

export function deleteGroup(accessToken: string, groupId: string): Promise<void> {
  return deleteResource(accessToken, `/groups/${groupId}`);
}

export interface ModuleRead {
  id: string;
  name: string;
  code: string;
  program_id: string;
  program_name: string;
}

export interface ModuleCreatePayload {
  program_id: string;
  name: string;
  code: string;
}

export async function listModulesByProgram(accessToken: string, programId: string): Promise<CursorPage<ModuleRead>> {
  const response = await fetch(`${API_URL}/programs/${programId}/modules?limit=200`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export function createModule(accessToken: string, programId: string, payload: ModuleCreatePayload): Promise<ModuleRead> {
  return postJson(accessToken, `/programs/${programId}/modules`, payload);
}

export function deleteModule(accessToken: string, moduleId: string): Promise<void> {
  return deleteResource(accessToken, `/modules/${moduleId}`);
}

export interface ModuleUpdatePayload {
  name: string;
  code: string;
}

export function updateModule(
  accessToken: string,
  moduleId: string,
  payload: ModuleUpdatePayload,
): Promise<ModuleRead> {
  return patchJson(accessToken, `/modules/${moduleId}`, payload);
}

export interface EnrollmentRead {
  id: string;
  is_active: boolean;
  enrolled_at: string;
  student_id: string;
  student_full_name: string;
  module_id: string;
  module_name: string;
}

export interface EnrollmentCreatePayload {
  student_id: string;
  module_id: string;
}

export async function listModuleEnrollments(accessToken: string, moduleId: string): Promise<CursorPage<EnrollmentRead>> {
  const response = await fetch(`${API_URL}/modules/${moduleId}/enrollments?limit=200`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export function createEnrollment(accessToken: string, payload: EnrollmentCreatePayload): Promise<EnrollmentRead> {
  return postJson(accessToken, "/enrollments", payload);
}

export function deactivateEnrollment(accessToken: string, enrollmentId: string): Promise<EnrollmentRead> {
  return postJson(accessToken, `/enrollments/${enrollmentId}/deactivate`, {});
}

export interface PlatformStatistics {
  total_users: number;
  users_by_role: { student: number; professor: number; admin: number };
  total_exercises: number;
  exercises_by_status: {
    draft: number;
    published_as_exam: number;
    published_as_homework: number;
    archived_in_library: number;
  };
  total_submissions: number;
  submissions_by_status: {
    pending_ocr: number;
    pending_student_verification: number;
    pending_arbitration: number;
    pending_evaluation: number;
    evaluated: number;
    absent: number;
  };
  average_score: number | null;
}

export async function getPlatformStatistics(accessToken: string): Promise<PlatformStatistics> {
  const response = await fetch(`${API_URL}/admin/statistics/platform`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export type JobStatus = "pending" | "running" | "retrying" | "interrupted" | "completed" | "failed" | "cancelled";

export interface JobRead {
  id: string;
  exercise_id: string | null;
  submission_id: string | null;
  flow_type: "exercise_setup" | "student_evaluation";
  status: JobStatus;
  current_node: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  // Positionnés en mémoire par JobSupervisionService.get_overview — jamais
  // garantis (exercise_setup sans étudiant, exercice/soumission supprimé...).
  exercise_title: string | null;
  student_full_name: string | null;
}

export interface JobsOverview {
  counts_by_status: Record<JobStatus, number>;
  recent_jobs: JobRead[];
  problematic_jobs: JobRead[];
}

export async function getJobsOverview(accessToken: string): Promise<JobsOverview> {
  const response = await fetch(`${API_URL}/admin/jobs/overview`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// Relance manuelle d'un Job FAILED — gap trouvé en test réel (2026-08-30) :
// au-delà des 5 retries automatiques Celery, rien ne relançait jamais une
// soumission bloquée sans script développeur. Uniquement STUDENT_EVALUATION
// pour l'instant (409 sinon, cf. job_retry_service.py côté backend).
export function retryJob(accessToken: string, jobId: string): Promise<JobRead> {
  return postJson(accessToken, `/admin/jobs/${jobId}/retry`, {});
}

export type AuditSeverity = "info" | "warning" | "critical";

export interface AuditLogRead {
  id: string;
  user_id: string;
  user_full_name: string;
  entity_type: string;
  entity_id: string;
  // Nom lisible de l'entité visée — résolu côté service seulement pour
  // entity_type "User" à ce jour, null sinon.
  entity_label: string | null;
  action: string;
  diff: Record<string, unknown> | null;
  success: boolean;
  severity: AuditSeverity;
  created_at: string;
}

export async function listAuditLogs(
  accessToken: string,
  options: { cursor?: string; limit?: number; entity_type?: string; user_id?: string; severity?: AuditSeverity } = {},
): Promise<CursorPage<AuditLogRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.entity_type) params.set("entity_type", options.entity_type);
  if (options.user_id) params.set("user_id", options.user_id);
  if (options.severity) params.set("severity", options.severity);

  const response = await fetch(`${API_URL}/admin/audit-logs?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export type IntegrityAlertStatus = "pending" | "under_review" | "confirmed" | "dismissed";
export type IntegrityActionTaken = "warning_issued" | "grade_invalidated" | "escalated" | "no_action";

export interface IntegrityAlertRead {
  id: string;
  student_id: string;
  student_full_name: string;
  trigger_type: string;
  auto_generated: boolean;
  evidence: Record<string, unknown>;
  reason: string;
  status: IntegrityAlertStatus;
  action_taken: IntegrityActionTaken | null;
  reviewed_by_user_id: string | null;
  review_notes: string | null;
  reviewed_at: string | null;
  created_at: string;
}

export async function listUnresolvedIntegrityAlerts(accessToken: string): Promise<IntegrityAlertRead[]> {
  const response = await fetch(`${API_URL}/integrity/alerts/unresolved`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface IntegrityAlertReviewPayload {
  status: IntegrityAlertStatus;
  action_taken?: IntegrityActionTaken;
  review_notes?: string;
}

export function resolveIntegrityAlert(
  accessToken: string,
  alertId: string,
  payload: IntegrityAlertReviewPayload,
): Promise<IntegrityAlertRead> {
  return postJson(accessToken, `/integrity/alerts/${alertId}/resolve`, payload);
}

// --- Signalement manuel (gap fermé : IntegrityService.flag_student()
// existait déjà côté backend, jamais exposé par aucun endpoint avant) ---

// HIGH_REJECTION_RATE et SYSTEMATIC_CONTESTATION réservés à la génération
// automatique (rejetés par un vrai validateur Pydantic côté backend,
// jamais proposés ici pour ne pas donner un choix qui échouera toujours).
export type ManualIntegrityTriggerType = "suspected_plagiarism" | "suspicious_pattern" | "manual_flag";

export interface IntegrityManualFlagPayload {
  student_id: string;
  trigger_type: ManualIntegrityTriggerType;
  reason: string;
}

export function flagStudentManually(
  accessToken: string,
  payload: IntegrityManualFlagPayload,
): Promise<IntegrityAlertRead> {
  return postJson(accessToken, "/integrity/alerts", payload);
}

async function putJson<T>(accessToken: string, path: string, payload: unknown): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "PUT",
    headers: authHeaders(accessToken),
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export type TaskType =
  | "ocr_vision"
  | "document_structuring"
  | "question_attachment"
  | "solution_variant_generation"
  | "reasoning_graph"
  | "comparative_evaluation"
  | "pedagogical_evaluation"
  | "competency_assessment"
  | "feedback_generation"
  | "contestation_verification"
  | "extraction_verification";

export type ModelProvider = "groq" | "openai" | "azure_openai" | "ollama";

export interface ModelConfigurationRead {
  task_type: TaskType;
  provider: ModelProvider;
  model_name: string;
  timeout_seconds: number;
  temperature: number;
  max_tokens: number | null;
  supports_vision: boolean;
  is_overridden: boolean;
  updated_at: string | null;
}

export async function getModelConfigurations(accessToken: string): Promise<ModelConfigurationRead[]> {
  const response = await fetch(`${API_URL}/admin/config/models`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface ModelConfigurationUpdatePayload {
  provider: ModelProvider;
  model_name: string;
  timeout_seconds: number;
}

export function updateModelConfiguration(
  accessToken: string,
  taskType: TaskType,
  payload: ModelConfigurationUpdatePayload,
): Promise<ModelConfigurationRead> {
  return putJson(accessToken, `/admin/config/models/${taskType}`, payload);
}

export interface SettingOverrideRead {
  key: string;
  value_type: string;
  default_value: string;
  override_value: string | null;
  effective_value: string;
  updated_at: string | null;
}

export async function getSystemSettings(accessToken: string): Promise<SettingOverrideRead[]> {
  const response = await fetch(`${API_URL}/admin/config/settings`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export function updateSystemSetting(accessToken: string, key: string, value: string): Promise<SettingOverrideRead> {
  return putJson(accessToken, `/admin/config/settings/${key}`, { value });
}

export interface ProviderCredentialRead {
  key: string;
  source: "database" | "environment" | "unset";
  is_wired: boolean;
  updated_at: string | null;
}

export async function getProviderCredentials(accessToken: string): Promise<ProviderCredentialRead[]> {
  const response = await fetch(`${API_URL}/admin/config/credentials`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export function createProviderCredential(accessToken: string, key: string, value: string): Promise<ProviderCredentialRead> {
  return postJson(accessToken, "/admin/config/credentials", { key, value });
}

export function updateProviderCredential(accessToken: string, key: string, value: string): Promise<ProviderCredentialRead> {
  return putJson(accessToken, `/admin/config/credentials/${key}`, { value });
}

export function clearProviderCredential(accessToken: string, key: string): Promise<void> {
  return deleteResource(accessToken, `/admin/config/credentials/${key}`);
}

export type ProfessorValidationStatus = "not_reviewed" | "validated" | "corrected";

export interface AgentDecisionLogRead {
  id: string;
  agent_name: string;
  related_entity_type: string;
  related_entity_id: string;
  // Libellé lisible de l'entité visée — couvre les 5 types possibles de
  // related_entity_type (Exercise, Question, SolutionVariant,
  // TeacherCorrectionBlock, ExtractionCorrection).
  entity_label: string | null;
  // Exercice parent, résolu séparément pour permettre le regroupement par
  // exercice à l'écran. Null si l'exercice référencé n'existe plus.
  exercise_id: string | null;
  exercise_title: string | null;
  input_summary: string | null;
  output_summary: string | null;
  justification: string;
  confidence_score: number | null;
  model_version: string;
  professor_validation_status: ProfessorValidationStatus;
  professor_correction: string | null;
  validated_by_professor_id: string | null;
  created_at: string;
}

export type PrivacyRequestType = "access_export" | "erasure" | "rectification" | "restriction" | "objection";
export type PrivacyRequestStatus = "pending" | "in_progress" | "completed" | "rejected";
export type PrivacyResolutionDetail =
  | "full_deletion"
  | "pseudonymized"
  | "partial_retention_legal"
  | "exported"
  | "rectified"
  | "processing_restricted"
  | "objection_upheld"
  | "rejected";

// Gap fermé (audit espace admin, migration backend c0d1e2f3a4b5) : la
// liste proposée à l'admin dépendait auparavant d'une seule liste plate
// (ERASURE_RESOLUTION_DETAILS) réutilisée pour TOUS les request_type,
// forçant par ex. une opposition (OBJECTION) à choisir "rectified" —
// sémantiquement faux. Une liste par type, jamais une seule liste
// partagée. "exported" toujours exclu partout : aucune infra de
// génération de fichier n'existe (cf. complete_export, non exposé
// côté admin).
export const RESOLUTION_DETAILS_BY_REQUEST_TYPE: Record<PrivacyRequestType, PrivacyResolutionDetail[]> = {
  access_export: [],
  erasure: ["full_deletion", "pseudonymized", "partial_retention_legal"],
  rectification: ["rectified"],
  restriction: ["processing_restricted"],
  objection: ["objection_upheld"],
};

export interface DataPrivacyRequestRead {
  id: string;
  user_id: string;
  user_full_name: string;
  request_type: PrivacyRequestType;
  status: PrivacyRequestStatus;
  legal_deadline: string;
  identity_verified: boolean;
  processed_by_user_id: string | null;
  processed_at: string | null;
  resolution_detail: PrivacyResolutionDetail | null;
  retention_or_rejection_reason: string | null;
  export_file_url: string | null;
  export_file_expires_at: string | null;
  created_at: string;
}

export async function listPendingPrivacyRequests(accessToken: string): Promise<DataPrivacyRequestRead[]> {
  const response = await fetch(`${API_URL}/privacy/requests/pending`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function getPrivacyRequest(accessToken: string, requestId: string): Promise<DataPrivacyRequestRead> {
  const response = await fetch(`${API_URL}/privacy/requests/${requestId}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export function verifyPrivacyRequestIdentity(
  accessToken: string,
  requestId: string,
  verificationMethod: string,
): Promise<DataPrivacyRequestRead> {
  return postJson(accessToken, `/privacy/requests/${requestId}/verify-identity`, {
    verification_method: verificationMethod,
  });
}

export function startProcessingPrivacyRequest(accessToken: string, requestId: string): Promise<DataPrivacyRequestRead> {
  return postJson(accessToken, `/privacy/requests/${requestId}/start-processing`, {});
}

export interface CompleteErasurePayload {
  resolution_detail: PrivacyResolutionDetail;
  reason?: string | null;
}

export function completeErasurePrivacyRequest(
  accessToken: string,
  requestId: string,
  payload: CompleteErasurePayload,
): Promise<DataPrivacyRequestRead> {
  return postJson(accessToken, `/privacy/requests/${requestId}/complete-erasure`, payload);
}

export function rejectPrivacyRequest(
  accessToken: string,
  requestId: string,
  reason: string,
): Promise<DataPrivacyRequestRead> {
  return postJson(accessToken, `/privacy/requests/${requestId}/reject`, { reason });
}

export async function listAgentDecisions(
  accessToken: string,
  options: { cursor?: string; limit?: number; agent_name?: string; professor_validation_status?: ProfessorValidationStatus } = {},
): Promise<CursorPage<AgentDecisionLogRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));
  if (options.agent_name) params.set("agent_name", options.agent_name);
  if (options.professor_validation_status) params.set("professor_validation_status", options.professor_validation_status);

  const response = await fetch(`${API_URL}/admin/agent-decisions?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}
