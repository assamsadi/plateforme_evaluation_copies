import { AuthApiError } from "@/lib/auth-api";
import type { AgentDecisionLogRead, CursorPage } from "@/lib/admin-api";

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

async function deleteResource(accessToken: string, path: string): Promise<void> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }
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

async function postFormData<T>(accessToken: string, path: string, formData: FormData): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: formData,
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface CourseRead {
  id: string;
  semester: string;
  module_id: string;
  module_name: string;
  professor_user_id: string;
  professor_full_name: string;
  group_id: string;
  group_label: string;
}

export async function listMyCourses(
  accessToken: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<CourseRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/courses/mine?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface CourseCreatePayload {
  module_id: string;
  group_id: string;
  semester: string;
}

export function createCourse(accessToken: string, payload: CourseCreatePayload): Promise<CourseRead> {
  return postJson(accessToken, "/courses", payload);
}

export function deleteCourse(accessToken: string, courseId: string): Promise<void> {
  return deleteResource(accessToken, `/courses/${courseId}`);
}

export function updateCourseSemester(accessToken: string, courseId: string, semester: string): Promise<CourseRead> {
  return patchJson(accessToken, `/courses/${courseId}`, { semester });
}

export type AcademicStatus = "active" | "suspended" | "graduated";

export interface StudentPublic {
  id: string;
  email: string;
  role: "student";
  first_name: string;
  last_name: string;
  is_active: boolean;
  student_number: string;
  group_id: string;
  enrollment_year: number;
  academic_status: AcademicStatus;
  level: string;
}

export async function listCourseStudents(accessToken: string, courseId: string): Promise<StudentPublic[]> {
  const response = await fetch(`${API_URL}/courses/${courseId}/students`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Résultats étudiants : profil de compétences & recommandations ---

export type C2PCTSkillCode =
  | "data_and_planning"
  | "decomposition_and_organization"
  | "algorithmic_structuring"
  | "generalization_and_transfer"
  | "solution_communication"
  | "self_evaluation_and_creativity"
  | "reflection_and_metacognition";

export type CompetencyTrend = "IMPROVING" | "DECLINING" | "STABLE" | "INSUFFICIENT_DATA";

export interface CompetencyProfileLine {
  competency: C2PCTSkillCode;
  mastery_level: number;
  trend: CompetencyTrend;
  evaluations_count: number;
  subquestions_concerned: string[];
  evidence_questions: string[];
  identified_difficulties: string[];
  strengths: string[];
  weaknesses: string[];
  confidence_level: number;
}

export interface StudentCompetencyReport {
  student_id: string;
  module_id: string;
  generated_at: string;
  lines: CompetencyProfileLine[];
}

export async function getStudentCompetencyProfile(
  accessToken: string,
  studentId: string,
  moduleId: string,
): Promise<StudentCompetencyReport> {
  const params = new URLSearchParams({ module_id: moduleId });
  const response = await fetch(`${API_URL}/students/${studentId}/competency-profile?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface RecommendedExerciseRead {
  id: string;
  student_id: string;
  module_id: string;
  competency_code: string;
  category: string;
  status: string;
  submission_id: string | null;
  exercise_id: string;
  exercise_title: string;
  difficulty_level: string | null;
  reason: string;
  relevance_score: number;
  // 3e palier ("faiblesse persistante") — jointure côté backend avec le
  // profil de compétence, jamais un champ natif de RecommendedExercise.
  is_persistent_weakness: boolean;
  audio_overview_url: string | null;
  flashcards_url: string | null;
  video_overview_url: string | null;
  video_overview_status: string;
  notebook_chat_url: string | null;
}

export async function getStudentRecommendations(
  accessToken: string,
  studentId: string,
  moduleId: string,
): Promise<RecommendedExerciseRead[]> {
  const params = new URLSearchParams({ module_id: moduleId });
  const response = await fetch(`${API_URL}/students/${studentId}/recommendations?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Écran "Profil de compétence" (refonte, test réel 2026-08-31) ---

export interface StudentModuleOptionRead {
  module_id: string;
  module_name: string;
}

// PAS sourcé depuis Enrollment côté backend (souvent vide — accès via
// groupe de cours, jamais une inscription module explicite, cf. docstring
// StudentCompetencyProfileRepository.list_distinct_modules_by_student) :
// seuls les modules où un vrai profil de compétence existe apparaissent.
export async function getStudentCompetencyModules(
  accessToken: string,
  studentId: string,
): Promise<StudentModuleOptionRead[]> {
  const response = await fetch(`${API_URL}/students/${studentId}/competency-modules`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface CompetencyObservationRead {
  competency_code: C2PCTSkillCode;
  performance_copie: number;
  submission_id: string;
  created_at: string;
}

export async function getStudentCompetencyHistory(
  accessToken: string,
  studentId: string,
  moduleId: string,
): Promise<CompetencyObservationRead[]> {
  const params = new URLSearchParams({ module_id: moduleId });
  const response = await fetch(`${API_URL}/students/${studentId}/competency-history?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface StudentModuleSummaryRead {
  student_id: string;
  module_id: string;
  total_submissions: number;
  evaluated_submissions: number;
  total_score: number;
  max_score: number;
}

export async function getStudentModuleSummary(
  accessToken: string,
  studentId: string,
  moduleId: string,
): Promise<StudentModuleSummaryRead> {
  const params = new URLSearchParams({ module_id: moduleId });
  const response = await fetch(`${API_URL}/students/${studentId}/module-summary?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export type AppealStatus = "pending" | "under_review" | "resolved";
export type AppealResolution = "grade_upheld" | "grade_revised" | "partial_revision";

export interface GradeAppealRead {
  id: string;
  submission_id: string;
  evaluation_id: string | null;
  extraction_correction_id: string | null;
  student_id: string;
  student_full_name: string;
  reason: string;
  created_at: string;
  original_score: number;
  status: AppealStatus;
  resolution: AppealResolution | null;
  revised_score: number | null;
  resolved_by_professor_id: string | null;
  resolved_by_professor_name: string | null;
  review_comment: string | null;
  resolved_at: string | null;
  ai_reevaluation_score: number | null;
  ai_reevaluation_justification: string | null;
  ai_reevaluation_criteria: { criterion: string; score: number; justification: string }[] | null;
}

export async function listPendingAppeals(
  accessToken: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<GradeAppealRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/appeals/pending?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface GradeAppealResolvePayload {
  resolution: AppealResolution;
  review_comment?: string | null;
  revised_score?: number | null;
}

export function resolveGradeAppeal(
  accessToken: string,
  appealId: string,
  payload: GradeAppealResolvePayload,
): Promise<GradeAppealRead> {
  return postJson(accessToken, `/appeals/${appealId}/resolve`, payload);
}

export type ClarificationSeverity = "blocking" | "warning" | "informational";
export type ClarificationStatus = "pending" | "answered";
export type ComparativeClarificationKind = "alternative_answer" | "coherence_ambiguity";

export interface ReasoningClarificationRequestRead {
  id: string;
  variant_id: string | null;
  related_entity_type: string | null;
  related_entity_id: string | null;
  criterion_id: string | null;
  comparative_clarification_kind: ComparativeClarificationKind | null;
  resolved_as_coherent: boolean | null;
  unclear_content: string | null;
  agent_question: string;
  proposed_answer: string | null;
  severity: ClarificationSeverity;
  status: ClarificationStatus;
  professor_answer: string | null;
  answered_by_professor_id: string | null;
  answered_by_professor_name: string | null;
  answered_at: string | null;
  resulting_step_id: string | null;
  created_at: string;
}

export async function listPendingClarifications(accessToken: string): Promise<ReasoningClarificationRequestRead[]> {
  const response = await fetch(`${API_URL}/clarifications/pending`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export function answerClarification(
  accessToken: string,
  requestId: string,
  professorAnswer: string,
): Promise<ReasoningClarificationRequestRead> {
  return postJson(accessToken, `/clarifications/${requestId}/answer`, { professor_answer: professorAnswer });
}

export function validateAlternativeAnswerClarification(
  accessToken: string,
  requestId: string,
  accepted: boolean,
): Promise<ReasoningClarificationRequestRead> {
  return postJson(accessToken, `/clarifications/${requestId}/validate-alternative-answer`, { accepted });
}

export function resolveCoherenceAmbiguityClarification(
  accessToken: string,
  requestId: string,
  resolvedAs: "coherent" | "incoherent",
): Promise<ReasoningClarificationRequestRead> {
  return postJson(accessToken, `/clarifications/${requestId}/resolve-coherence-ambiguity`, {
    resolved_as: resolvedAs,
  });
}

// --- Exercises ---

export type ExerciseStatus = "draft" | "published_as_exam" | "published_as_homework" | "archived_in_library";
export type ExerciseDifficulty = "facile" | "intermediaire" | "avance";

export interface CriterionCreate {
  label: string;
  points: number;
}

export interface CriterionRead {
  id: string;
  label: string;
  points: number;
}

export interface BaremeCreate {
  points: number;
  criteria: CriterionCreate[];
}

// Saisie manuelle de secours pour le barème C2PCT natif — distinct de
// BaremeCreate ci-dessus (barème classique). Jamais de champ "total"
// séparé : la somme des valeurs de `points` EST le total, rien à
// dupliquer ni à valider en double.
export interface SubquestionPointsCreate {
  points: Record<string, number>;
}

export interface BaremeRead {
  id: string;
  points: number;
  criteria: CriterionRead[];
}

export interface QuestionCreate {
  order: number;
  statement: string;
  bareme?: BaremeCreate | null;
}

export interface SubquestionRead {
  id: string;
  official_title: string;
  content: string;
}

export interface QuestionRead {
  id: string;
  exercise_id: string;
  section_id: string | null;
  order: number;
  statement: string;
  attachment_path: string | null;
  bareme: BaremeRead | null;
  covered_subquestions: string[];
  subquestions: SubquestionRead[] | null;
  // Barème C2PCT natif (id de sous-question officielle -> points), DISTINCT
  // de `bareme` ci-dessus (mécanisme classique, reste null pour ce type de
  // document) — null si ce document n'utilise pas le barème C2PCT natif.
  subquestion_points: Record<string, number> | null;
}

export interface ExerciseRead {
  id: string;
  module_id: string;
  module_name: string;
  course_id: string | null;
  created_by_professor_id: string;
  professor_full_name: string;
  title: string;
  description: string | null;
  status: ExerciseStatus;
  deadline: string | null;
  difficulty_level: ExerciseDifficulty | null;
  sections: { id: string; exercise_id: string; order: number; title: string }[];
  questions: QuestionRead[];
}

export interface ExerciseCreatePayload {
  module_id: string;
  title: string;
  description?: string | null;
  questions: QuestionCreate[];
}

export async function listMyExercises(
  accessToken: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<ExerciseRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/exercises/mine?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function getExercise(accessToken: string, exerciseId: string): Promise<ExerciseRead> {
  const response = await fetch(`${API_URL}/exercises/${exerciseId}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export function createExercise(accessToken: string, payload: ExerciseCreatePayload): Promise<ExerciseRead> {
  return postJson(accessToken, "/exercises", payload);
}

export function deleteExercise(accessToken: string, exerciseId: string): Promise<void> {
  return deleteResource(accessToken, `/exercises/${exerciseId}`);
}

export interface PublishExercisePayload {
  // "draft" (2026-09-07) : retour arrière depuis n'importe quel statut,
  // y compris ARCHIVED_IN_LIBRARY — décision actée côté backend (aucune
  // restriction, cf. docstring ExerciseService, point 3), course_id/
  // deadline alors sans objet.
  status: "draft" | "published_as_exam" | "published_as_homework";
  course_id?: string;
  deadline?: string;
}

export function publishExercise(
  accessToken: string,
  exerciseId: string,
  payload: PublishExercisePayload,
): Promise<ExerciseRead> {
  return postJson(accessToken, `/exercises/${exerciseId}/publish`, payload);
}

// Report/avance de la deadline d'un examen/devoir déjà publié — jamais
// republier via publishExercise pour ce seul besoin (cf. docstring
// ExerciseService.update_deadline côté backend).
export function updateExerciseDeadline(
  accessToken: string,
  exerciseId: string,
  deadline: string,
): Promise<ExerciseRead> {
  return patchJson(accessToken, `/exercises/${exerciseId}/deadline`, { deadline });
}

export function archiveExerciseToLibrary(
  accessToken: string,
  exerciseId: string,
  difficultyLevel: ExerciseDifficulty,
): Promise<ExerciseRead> {
  return postJson(accessToken, `/exercises/${exerciseId}/archive-to-library`, {
    difficulty_level: difficultyLevel,
  });
}

export interface PublicationReadinessQuestionSummary {
  question_id: string;
  order: number;
  statement: string;
  bareme_points: number;
  bareme_criteria: CriterionRead[];
  reference_variant_summary: string;
}

export interface PublicationReadinessRead {
  exercise_id: string;
  confirmed_at: string;
  questions: PublicationReadinessQuestionSummary[];
}

export function confirmPublicationReadiness(
  accessToken: string,
  exerciseId: string,
): Promise<PublicationReadinessRead> {
  return postJson(accessToken, `/exercises/${exerciseId}/confirm-publication-readiness`, {});
}

export function uploadExerciseReferenceDocument(
  accessToken: string,
  exerciseId: string,
  file: File,
): Promise<ExerciseRead> {
  const formData = new FormData();
  formData.append("document", file);
  return postFormData(accessToken, `/exercises/${exerciseId}/reference-document`, formData);
}

// --- Solution variants (variante de référence) ---

export type VariantSource = "teacher_original" | "teacher_manual" | "ai_generated";
export type VariantDifficulty = "facile" | "intermediaire" | "avance";

export interface SolutionVariantCreatePayload {
  question_id: string;
  content: string;
  source: VariantSource;
  difficulty_level: VariantDifficulty;
  is_reference: boolean;
  structured_content?: Record<string, unknown> | null;
  reasoning_steps?: unknown[];
}

export interface SolutionVariantRead {
  id: string;
  question_id: string;
  content: string;
  is_reference: boolean;
  source: VariantSource;
  status: string;
}

export function createSolutionVariant(
  accessToken: string,
  payload: SolutionVariantCreatePayload,
): Promise<SolutionVariantRead> {
  return postJson(accessToken, "/solution-variants", payload);
}

export type VariantStatus = "pending_validation" | "approved" | "rejected";

export interface SolutionVariantSummaryRead {
  id: string;
  question_id: string;
  is_reference: boolean;
  source: VariantSource;
  difficulty_level: VariantDifficulty;
  status: VariantStatus;
  strategy_name: string | null;
  distinction_score: number | null;
  reasoning_summary: string | null;
  content: string;
  created_at: string;
}

export async function listQuestionSolutionVariants(
  accessToken: string,
  questionId: string,
): Promise<SolutionVariantSummaryRead[]> {
  const response = await fetch(`${API_URL}/questions/${questionId}/solution-variants`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface GuidedVariantGenerationPayload {
  method_hint?: string | null;
  concept_hint?: string[] | null;
}

export interface GuidedVariantGenerationAck {
  question_id: string;
  status: string;
}

export function generateGuidedSolutionVariant(
  accessToken: string,
  questionId: string,
  payload: GuidedVariantGenerationPayload,
): Promise<GuidedVariantGenerationAck> {
  return postJson(accessToken, `/questions/${questionId}/solution-variants/generate-guided`, payload);
}

export type ReasoningStepType = string;

export interface ReasoningStepRead {
  id: string;
  variant_id: string;
  order: number;
  step_type: ReasoningStepType;
  description: string;
  formula: string | null;
  concept_tags: string[];
  tools_used: string[];
  related_competency_code: C2PCTSkillCode | null;
  related_competency_name: string | null;
  depends_on_step_ids: string[];
}

export async function getVariantReasoningGraph(
  accessToken: string,
  variantId: string,
): Promise<ReasoningStepRead[]> {
  const response = await fetch(`${API_URL}/solution-variants/${variantId}/reasoning-graph`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface ReasoningStepUpdatePayload {
  description?: string | null;
  formula?: string | null;
}

export interface ReasoningStepUpdateResponse {
  id: string;
  description: string;
  formula: string | null;
}

// Correction ciblée d'UNE étape (cf. mémoire de session) — distinct de
// reviewSolutionVariant(action="MODIFIED") qui réécrit tout le contenu de la
// variante en bloc.
export function updateReasoningStep(
  accessToken: string,
  stepId: string,
  payload: ReasoningStepUpdatePayload,
): Promise<ReasoningStepUpdateResponse> {
  return patchJson(accessToken, `/reasoning-steps/${stepId}`, payload);
}

// --- Traçabilité IA (gap : logs de décision jamais exposés au professeur) ---

export async function listExerciseDecisionLogs(
  accessToken: string,
  exerciseId: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<AgentDecisionLogRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/exercises/${exerciseId}/decision-logs?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function listQuestionDecisionLogs(
  accessToken: string,
  questionId: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<AgentDecisionLogRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/questions/${questionId}/decision-logs?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export type VariantReviewAction = "ACCEPTED" | "REJECTED" | "MODIFIED" | "DELETED";

export interface VariantReviewPayload {
  action: VariantReviewAction;
  modified_content?: string | null;
  modified_summary?: string | null;
  review_comment?: string | null;
  // Pris en compte UNIQUEMENT quand action === "REJECTED" : le backend
  // déclenche alors automatiquement une nouvelle génération guidée pour la
  // question, pilotée par ces 2 champs s'ils sont renseignés (cf. mémoire
  // de session — même mécanisme que generateGuidedSolutionVariant).
  method_hint?: string | null;
  concept_hint?: string[] | null;
}

export interface RetroactiveEquityReport {
  exercise_id: string;
  question_id: string;
  newly_accepted_variant_id: string;
  impacted_submission_ids: string[];
  message: string;
}

export interface VariantReviewResponse {
  variant_id: string | null;
  status: VariantStatus | null;
  content: string | null;
  deleted: boolean;
  retroactive_equity: RetroactiveEquityReport | null;
  strategy_name: string | null;
  distinction_score: number | null;
  intermediate_check_note: string | null;
}

export function reviewSolutionVariant(
  accessToken: string,
  variantId: string,
  payload: VariantReviewPayload,
): Promise<VariantReviewResponse> {
  return postJson(accessToken, `/solution-variants/${variantId}/review`, payload);
}

// --- Teacher correction blocks (chemin IA) ---

export type BlockEvidenceLevel =
  | "label_explicite"
  | "inferred_single_question"
  | "content_matched"
  | "unresolved_no_label";
export type ExtractionContentType = "TEXT" | "EQUATION" | "DIAGRAM" | "STRUCTURE";

export interface TeacherCorrectionBlockRead {
  id: string;
  exercise_id: string;
  question_id: string | null;
  image_crop_url: string | null;
  content_type: ExtractionContentType;
  raw_text: string | null;
  structured_content: Record<string, unknown> | string | null;
  evidence_level: BlockEvidenceLevel;
  professor_resolution: string | null;
  justification: string;
  created_at: string | null;
  ocr_confidence: number | null;
  is_low_ocr_confidence: boolean;
}

export async function listExerciseCorrectionBlocks(
  accessToken: string,
  exerciseId: string,
): Promise<TeacherCorrectionBlockRead[]> {
  const response = await fetch(`${API_URL}/exercises/${exerciseId}/correction-blocks`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface BlockResolutionItem {
  block_id: string;
  question_id: string | null;
  professor_resolution: string;
}

export function resolveCorrectionBlocks(
  accessToken: string,
  exerciseId: string,
  resolutions: BlockResolutionItem[],
): Promise<TeacherCorrectionBlockRead[]> {
  return postJson(accessToken, `/exercises/${exerciseId}/structure/resolve-blocks`, { resolutions });
}

// Confirme une structuration déjà visible (aucun bloc UNRESOLVED_NO_LABEL à
// corriger via resolveCorrectionBlocks) pour reprendre le pipeline en pause
// à await_structuring_resolution_node — 204 No Content, jamais de corps JSON
// à parser (postJson appelle .json() inconditionnellement, ce qui échouerait
// sur une réponse vide).
export async function confirmExerciseStructuring(accessToken: string, exerciseId: string): Promise<void> {
  const response = await fetch(`${API_URL}/exercises/${exerciseId}/structure/confirm`, {
    method: "POST",
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }
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

export function setQuestionBareme(
  accessToken: string,
  exerciseId: string,
  questionId: string,
  payload: BaremeCreate,
): Promise<ExerciseRead> {
  return putJson(accessToken, `/exercises/${exerciseId}/questions/${questionId}/bareme`, payload);
}

export function setQuestionSubquestionPoints(
  accessToken: string,
  exerciseId: string,
  questionId: string,
  payload: SubquestionPointsCreate,
): Promise<ExerciseRead> {
  return putJson(accessToken, `/exercises/${exerciseId}/questions/${questionId}/subquestion-points`, payload);
}

export function addQuestion(accessToken: string, exerciseId: string, statement: string): Promise<ExerciseRead> {
  return postJson(accessToken, `/exercises/${exerciseId}/questions`, { statement });
}

export function updateQuestionStatement(
  accessToken: string,
  exerciseId: string,
  questionId: string,
  statement: string,
): Promise<ExerciseRead> {
  return patchJson(accessToken, `/exercises/${exerciseId}/questions/${questionId}`, { statement });
}

export function deleteQuestion(accessToken: string, exerciseId: string, questionId: string): Promise<ExerciseRead> {
  return deleteResourceWithBody(accessToken, `/exercises/${exerciseId}/questions/${questionId}`);
}

async function deleteResourceWithBody<T>(accessToken: string, path: string): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    method: "DELETE",
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Copies déposées (gap : aucune vue d'ensemble des soumissions d'un exercice) ---

export type SubmissionStatus =
  | "pending_ocr"
  | "pending_student_verification"
  | "pending_arbitration"
  | "pending_evaluation"
  | "evaluated"
  | "absent";

export interface SubmissionSummaryRead {
  id: string;
  student_id: string;
  student_full_name: string;
  attempt_number: number;
  status: SubmissionStatus;
  total_score: number | null;
  // Chantier "notation vivante" — nécessaire pour un seuil de couleur
  // proportionnel (le barème total varie par exercice). Même repli que
  // total_score : null tant que status !== "evaluated".
  max_score: number | null;
  created_at: string;
  // Gap fermé (test réel 2026-08-31) : accès au document original déposé
  // par l'étudiant depuis l'écran de résultat professeur. URL SAS déjà
  // résolue par le backend, jamais le chemin blob brut.
  document_url: string | null;
}

export async function listExerciseSubmissions(
  accessToken: string,
  exerciseId: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<SubmissionSummaryRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/exercises/${exerciseId}/submissions?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Détail d'une copie : notes par question + agrégat de correction ---

export interface EvaluationCriteriaRead {
  id: string;
  bareme_id: string | null;
  criterion_id: string | null;
  criterion_label: string | null;
  points_awarded: number;
  comment: string | null;
  competency_code: C2PCTSkillCode | null;
}

export interface EvaluationRead {
  id: string;
  submission_id: string;
  question_id: string;
  question_order: number;
  score: number;
  criteria: EvaluationCriteriaRead[];
}

export async function listSubmissionEvaluations(
  accessToken: string,
  submissionId: string,
): Promise<EvaluationRead[]> {
  const response = await fetch(`${API_URL}/submissions/${submissionId}/evaluations`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface CopyReportOverview {
  questions_sans_ambiguite: number;
  questions_necessitant_un_regard: number;
  consigne_non_respectee_count: number;
}

export interface CopyReport {
  submission_id: string;
  overview: CopyReportOverview;
}

export async function getSubmissionCopyReport(accessToken: string, submissionId: string): Promise<CopyReport> {
  const response = await fetch(`${API_URL}/submissions/${submissionId}/copy-report`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// Chantier "notation vivante" — accès professeur au texte socratique de
// Feedback_Agent pour une soumission (nouveau, cf. GET /submissions/
// {id}/feedback réservé au professeur créateur de l'exercice). 404 tant
// que feedback_node n'a pas encore traité cette soumission.
export interface FeedbackReportRead {
  submission_id: string;
  feedback_text: string;
  competencies_addressed: string[];
  generated_at: string;
}

export async function getSubmissionFeedback(
  accessToken: string,
  submissionId: string,
): Promise<FeedbackReportRead> {
  const response = await fetch(`${API_URL}/submissions/${submissionId}/feedback`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Pipeline status (gap : visibilité du job OCR après upload) ---

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
}

export async function getExercisePipelineStatus(accessToken: string, exerciseId: string): Promise<JobRead | null> {
  const response = await fetch(`${API_URL}/exercises/${exerciseId}/pipeline-status`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  const body = await response.text();
  return body ? JSON.parse(body) : null;
}

// --- Arbitrage : corrections contestées (gap : aucune file de découverte) ---

export type ArbitrationVerdict = "accepted" | "rejected";

export interface PendingCorrectionArbitrationRead {
  arbitration_id: string;
  extraction_correction_id: string;
  submission_id: string;
  student_id: string;
  student_full_name: string;
  exercise_id: string;
  exercise_title: string;
  question_id: string | null;
  contestation_type: "content" | "attachment" | "structure_element" | "fusion" | null;
  claimed_question_order: number | null;
  prediction_ocr: string;
  human_correction: string | null;
  image_crop_url: string | null;
  document_url: string | null;
  created_at: string;
  // Traçabilité réelle (2026-09-06) : status/verdict/teacher_full_name
  // portent le verdict PERSISTÉ en base — jamais un état local qui se
  // perdrait au rechargement de la page.
  status: "pending" | "resolved";
  verdict: ArbitrationVerdict | null;
  teacher_full_name: string | null;
}

export async function listPendingCorrectionArbitrations(
  accessToken: string,
): Promise<PendingCorrectionArbitrationRead[]> {
  const response = await fetch(`${API_URL}/arbitrations/corrections/pending`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// Liste PRINCIPALE (traçabilité réelle, 2026-09-06) : contrairement à
// listPendingCorrectionArbitrations, inclut aussi les arbitrages déjà
// résolus — sans ça, la ligne d'un étudiant disparaît du tableau dès que
// tout est tranché, sans plus aucun moyen d'accéder à son historique.
export async function listAllCorrectionArbitrations(
  accessToken: string,
): Promise<PendingCorrectionArbitrationRead[]> {
  const response = await fetch(`${API_URL}/arbitrations/corrections/all`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// Historique COMPLET (pending + resolved) des arbitrages d'un étudiant —
// traçabilité réelle (2026-09-06) : listPendingCorrectionArbitrations
// n'expose QUE les pending, une contestation tranchée y disparaît sans
// laisser de trace consultable après un rechargement de page.
export async function getStudentArbitrationHistory(
  accessToken: string,
  studentId: string,
): Promise<PendingCorrectionArbitrationRead[]> {
  const response = await fetch(`${API_URL}/arbitrations/corrections/students/${studentId}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface CorrectionArbitrationRead {
  id: string;
  extraction_correction_id: string;
  status: "pending" | "resolved";
  teacher_professor_id: string | null;
  teacher_full_name: string | null;
  verdict: ArbitrationVerdict | null;
  comment: string | null;
  claimed_correction: string | null;
  created_at: string;
}

export interface CorrectionArbitrationResolvePayload {
  verdict: ArbitrationVerdict;
  comment?: string | null;
  claimed_correction?: string | null;
}

export function resolveCorrectionArbitration(
  accessToken: string,
  extractionCorrectionId: string,
  payload: CorrectionArbitrationResolvePayload,
): Promise<CorrectionArbitrationRead> {
  return postJson(accessToken, `/arbitrations/corrections/${extractionCorrectionId}/resolve`, payload);
}

// --- Arbitrage : incidents (gap : aucune file de découverte) ---

export type IncidentCategory = "technical" | "health" | "other";
export type IncidentResolution = "justified_absence" | "retry_granted" | "deadline_extended" | "rejected";
export type IncidentStatusValue = "pending" | "resolved";

export interface SubmissionIncidentRead {
  id: string;
  exercise_id: string;
  exercise_title: string;
  student_id: string;
  student_full_name: string;
  reported_by_user_id: string;
  parent_incident_id: string | null;
  category: IncidentCategory;
  incident_occurred_at: string | null;
  reason: string;
  attachment_url: string | null;
  status: IncidentStatusValue;
  resolution: IncidentResolution | null;
  resolution_comment: string | null;
  resolved_by_professor_id: string | null;
  resolved_at: string | null;
  extended_deadline: string | null;
  new_submission_id: string | null;
}

export async function listPendingIncidents(accessToken: string): Promise<SubmissionIncidentRead[]> {
  const response = await fetch(`${API_URL}/incidents/pending`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface IncidentResolvePayload {
  resolution: IncidentResolution;
  resolution_comment?: string | null;
  extended_deadline?: string | null;
}

export function resolveIncident(
  accessToken: string,
  incidentId: string,
  payload: IncidentResolvePayload,
): Promise<SubmissionIncidentRead> {
  return postJson(accessToken, `/incidents/${incidentId}/resolve`, payload);
}

// --- Regroupement d'incidents (gap fermé, audit espace professeur) : ces
// endpoints existaient déjà côté backend mais n'étaient appelés par aucune
// UI — cf. ArbitrationService.detect_and_cluster/resolve_cluster. Un bug
// réel a été corrigé au passage (resolve_cluster ne créait jamais de
// nouvelle tentative pour RETRY_GRANTED, ni ne posait extended_deadline).

export interface ClusterDetectionResult {
  root_incident_id: string | null;
}

export function detectAndClusterIncidents(
  accessToken: string,
  exerciseId: string,
): Promise<ClusterDetectionResult> {
  return postJson(accessToken, `/exercises/${exerciseId}/incidents/cluster`, {});
}

export interface ClusterResolutionResult {
  resolved_count: number;
}

export function resolveIncidentCluster(
  accessToken: string,
  parentIncidentId: string,
  payload: IncidentResolvePayload,
): Promise<ClusterResolutionResult> {
  return postJson(accessToken, `/incidents/clusters/${parentIncidentId}/resolve`, payload);
}

// --- Signalement manuel d'intégrité (gap fermé, audit espace admin —
// ouvert ici aussi au professeur : IntegrityService.flag_student()
// autorise déjà les deux rôles, cf. docstring service. Aucun nouvel
// endpoint backend nécessaire — un professeur n'a pas accès à /admin/users
// (liste globale), donc la liste d'étudiants proposée ici passe par ses
// propres cours (listMyCourses + listCourseStudents, déjà existants),
// jamais une liste globale) ---

export type ManualIntegrityTriggerType = "suspected_plagiarism" | "suspicious_pattern" | "manual_flag";

export interface IntegrityAlertRead {
  id: string;
  student_id: string;
  student_full_name: string;
  trigger_type: string;
  auto_generated: boolean;
  evidence: Record<string, unknown>;
  reason: string;
  status: string;
  created_at: string;
}

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
