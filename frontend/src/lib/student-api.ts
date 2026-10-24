import { AuthApiError } from "@/lib/auth-api";
import type { CursorPage } from "@/lib/admin-api";

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
  return { Authorization: `Bearer ${accessToken}` };
}

// --- Examens/devoirs assignés (gap : jamais exposé avant, cf. audit espace étudiant) ---

export type ExerciseStatus = "draft" | "published_as_exam" | "published_as_homework" | "archived_in_library";

export interface CriterionRead {
  id: string;
  label: string;
  points: number;
}

export interface BaremeRead {
  id: string;
  points: number;
  criteria: CriterionRead[];
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
}

export interface AssignedExerciseRead {
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
  difficulty_level: string | null;
  questions: QuestionRead[];
}

export async function listAssignedExercises(
  accessToken: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<AssignedExerciseRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/students/me/assigned-exercises?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Bibliothèque d'un module (ARCHIVED_IN_LIBRARY, pratique libre) —
// gap fermé (test réel 2026-08-31) : GET /modules/{id}/library existait
// déjà côté backend (get_current_user, donc déjà accessible à un étudiant),
// mais aucune fonction ni page frontend étudiante ne l'utilisait — le
// bouton "voir l'exercice" d'une recommandation n'avait donc aucune
// destination réelle. Même forme que AssignedExerciseRead (structurellement
// identique côté backend, ExerciseRead), réutilisable telle quelle par
// SubmitExamDialog. ---

export async function listModuleLibrary(
  accessToken: string,
  moduleId: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<AssignedExerciseRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/modules/${moduleId}/library?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function getReferenceDocumentUrl(
  accessToken: string,
  exerciseId: string,
): Promise<string | null> {
  const response = await fetch(`${API_URL}/exercises/${exerciseId}/reference-document-url`, {
    headers: authHeaders(accessToken),
  });

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  const data = await response.json();
  return data.url;
}

// --- Mes soumissions (bug corrigé : validation cassée avant ce chantier) ---

export type SubmissionStatus =
  | "pending_ocr"
  | "pending_student_verification"
  | "pending_arbitration"
  | "pending_evaluation"
  | "evaluated"
  | "absent";

export interface SubmissionRead {
  id: string;
  exercise_id: string;
  exercise_title: string;
  student_id: string;
  student_full_name: string;
  attempt_number: number;
  status: SubmissionStatus;
  created_at: string;
}

export async function listMySubmissions(
  accessToken: string,
  options: { cursor?: string; limit?: number } = {},
): Promise<CursorPage<SubmissionRead>> {
  const params = new URLSearchParams();
  if (options.cursor) params.set("cursor", options.cursor);
  if (options.limit) params.set("limit", String(options.limit));

  const response = await fetch(`${API_URL}/students/me/submissions?${params.toString()}`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Notes par question (réutilise GET /submissions/{id}/evaluations, déjà
// contrôlé en accès pour l'étudiant propriétaire — cf. EvaluationService.
// _authorize_submission_access, chantier plus tôt cette session) ---

export interface SubquestionScoreDetailItem {
  subquestion_id: string;
  addressed: boolean;
  is_correct: boolean | null;
  source: string;
}

export interface SubquestionDetailBlock {
  subquestions: SubquestionScoreDetailItem[];
  covered_count: number;
  successful_count: number;
  success_rate: number;
}

export interface EvaluationCriteriaRead {
  id: string;
  bareme_id: string | null;
  criterion_id: string | null;
  criterion_label: string | null;
  points_awarded: number;
  comment: string | null;
  competency_code: string | null;
  subquestion_detail: SubquestionDetailBlock | null;
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

// --- Résultats ("Mes résultats", gap fermé 2026-08-31) — total_score/
// max_score, jamais exposés sur SubmissionRead ni sur EvaluationRead seuls
// (un étudiant voyait son statut passer à "evaluated" sans jamais voir sa
// note nulle part) ---

export interface QuestionResultRead {
  question_id: string;
  question_order: number;
  // null tant que la question n'a pas encore d'Evaluation — distinct de 0,
  // qui serait une vraie note obtenue.
  score: number | null;
  max_score: number;
  is_graded: boolean;
  // None si is_graded=true. "no_student_answer" : aucun contenu déposé pour
  // cette question précise. "pending_review" : du contenu existe mais pas
  // encore de note (traitement en cours ou en attente d'arbitrage).
  not_graded_reason: "no_student_answer" | "pending_review" | null;
  // Justification RÉELLE de l'agent (Comparative_Evaluation_Agent) pour
  // CETTE soumission précise, quand not_graded_reason="pending_review" et
  // qu'une clarification bloquante existe — null sinon (jamais un texte
  // générique substitué ici, cf. backend).
  blocking_justification: string | null;
}

export interface SubmissionResultRead {
  submission_id: string;
  exercise_title: string;
  total_score: number;
  max_score: number;
  is_fully_graded: boolean;
  questions: QuestionResultRead[];
}

export async function getMySubmissionResults(
  accessToken: string,
  submissionId: string,
): Promise<SubmissionResultRead> {
  const response = await fetch(`${API_URL}/students/me/submissions/${submissionId}/results`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Feedback pédagogique socratique (Feedback_Agent) — self-only, 404 si
// pas encore généré par le pipeline (jamais une génération à la demande) ---

export interface FeedbackReportRead {
  submission_id: string;
  feedback_text: string;
  competencies_addressed: string[];
  generated_at: string;
}

export async function getSubmissionFeedback(
  accessToken: string,
  studentId: string,
  submissionId: string,
): Promise<FeedbackReportRead> {
  const response = await fetch(
    `${API_URL}/students/${studentId}/submissions/${submissionId}/feedback`,
    { headers: authHeaders(accessToken) },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Recours de note (gap fermé : aucune lecture étudiante n'existait
// avant pour revoir le statut d'une contestation déposée — cf.
// GradeAppealService.list_by_submission_for_student) ---

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
}

export async function listSubmissionAppeals(
  accessToken: string,
  submissionId: string,
): Promise<GradeAppealRead[]> {
  const response = await fetch(`${API_URL}/submissions/${submissionId}/appeals`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface GradeAppealCreatePayload {
  submission_id: string;
  evaluation_id?: string | null;
  reason: string;
}

export async function fileGradeAppeal(
  accessToken: string,
  payload: GradeAppealCreatePayload,
): Promise<GradeAppealRead> {
  const response = await fetch(`${API_URL}/appeals`, {
    method: "POST",
    headers: { ...authHeaders(accessToken), "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Mes statistiques ---

export interface StudentStats {
  student_id: string;
  total_submissions: number;
  total_evaluations: number;
  average_score: number | null;
}

export async function getMyStats(accessToken: string): Promise<StudentStats> {
  const response = await fetch(`${API_URL}/students/me/stats`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// --- Vérification étudiante post-OCR (gap fermé : aucun endpoint n'existait
// pour voir ce qui a été extrait, ni pour confirmer sa copie — cf.
// ExtractionService.list_corrections_for_submission/confirm_submission) ---

export type ExtractionContentType = "TEXT" | "EQUATION" | "DIAGRAM" | "STRUCTURE";
export type ExtractionEvidenceLevel = "label_explicite" | "contenu_vs_reference" | "ambigu" | "orphelin";
export type ContestationStatus = "pending_verification" | "plausible" | "implausible" | "ambigu" | "resolved";

export interface ExtractionCorrectionRead {
  id: string;
  submission_id: string;
  question_id: string | null;
  question_order: number | null;
  image_url: string;
  content_type: ExtractionContentType;
  prediction_ocr: string;
  structured_output: Record<string, unknown> | null;
  human_correction: string | null;
  confidence_score: number;
  bounding_box: Record<string, unknown>;
  evidence_level: ExtractionEvidenceLevel;
  contestation_status: ContestationStatus | null;
  verified_content: string | null;
  is_low_ocr_confidence: boolean;
  // Traçabilité réelle (2026-09-06) : contestation_status="resolved" est
  // posé à l'identique que le prof ait accepté ou refusé — le vrai verdict
  // vit ici, jamais sur contestation_status seul.
  arbitration_verdict: "accepted" | "rejected" | null;
}

export async function listSubmissionCorrections(
  accessToken: string,
  submissionId: string,
): Promise<ExtractionCorrectionRead[]> {
  const response = await fetch(`${API_URL}/submissions/${submissionId}/corrections`, {
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface SubmissionConfirmationRead {
  submission_id: string;
  status: SubmissionStatus;
}

export async function confirmSubmission(
  accessToken: string,
  submissionId: string,
): Promise<SubmissionConfirmationRead> {
  const response = await fetch(`${API_URL}/submissions/${submissionId}/confirm`, {
    method: "POST",
    headers: authHeaders(accessToken),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// Cas A (CONTENT — transcription en cause) et Cas B (ATTACHMENT — question
// réclamée) sont couverts côté UI : ce sont les deux cas d'usage réels vus
// en test (2026-09-05, "Bloc non rattaché" — l'étudiant n'avait aucun moyen
// de réclamer la bonne question). Cas C/D (élément STRUCTURE, fusion)
// existent côté backend (ContestationType) mais restent sans UI dédiée ici —
// scope volontairement réduit à ces deux cas plutôt qu'un formulaire
// exhaustif rarement utilisé.
export async function contestExtractionContent(
  accessToken: string,
  submissionId: string,
  correctionId: string,
  claimedContent: string,
): Promise<ExtractionCorrectionRead> {
  const response = await fetch(
    `${API_URL}/submissions/${submissionId}/corrections/${correctionId}/contest`,
    {
      method: "POST",
      headers: { ...authHeaders(accessToken), "Content-Type": "application/json" },
      body: JSON.stringify({ contestation_type: "content", claimed_content: claimedContent }),
    },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function contestExtractionAttachment(
  accessToken: string,
  submissionId: string,
  correctionId: string,
  claimedQuestionId: string,
): Promise<ExtractionCorrectionRead> {
  const response = await fetch(
    `${API_URL}/submissions/${submissionId}/corrections/${correctionId}/contest`,
    {
      method: "POST",
      headers: { ...authHeaders(accessToken), "Content-Type": "application/json" },
      body: JSON.stringify({ contestation_type: "attachment", claimed_question_id: claimedQuestionId }),
    },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

const ALLOWED_SUBMISSION_MIME_TYPES = new Set([
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/tiff",
]);

export function isAllowedSubmissionFile(file: File): boolean {
  return ALLOWED_SUBMISSION_MIME_TYPES.has(file.type);
}

// --- Profil de compétences C2PCT + recommandations (StudentCompetencyReport
// est un dataclass Python, pas un schéma Pydantic — pas de response_model
// côté route, sérialisé par jsonable_encoder ; vérifié réel via ASGI avant
// d'écrire ces types, endpoints 200 confirmés) ---

export type CompetencyTrend = "IMPROVING" | "DECLINING" | "STABLE" | "INSUFFICIENT_DATA";

export interface CompetencyProfileLine {
  competency: string;
  mastery_level: number;
  trend: CompetencyTrend;
  evaluations_count: number;
  subquestions_concerned: string[];
  evidence_questions: string[];
  identified_difficulties: string[];
  strengths: string[];
  weaknesses: string[];
  confidence_level: number;
  is_persistent_weakness: boolean;
}

export interface StudentCompetencyReport {
  student_id: string;
  module_id: string;
  generated_at: string;
  lines: CompetencyProfileLine[];
}

export async function getMyCompetencyProfile(
  accessToken: string,
  moduleId: string,
): Promise<StudentCompetencyReport> {
  const response = await fetch(
    `${API_URL}/students/me/competency-profile?module_id=${moduleId}`,
    { headers: authHeaders(accessToken) },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

// Série temporelle brute (StudentCompetencyObservation) — distincte de
// StudentCompetencyReport (agrégat Niveau 3 uniquement), pour le graphique
// d'évolution. GET /students/{student_id}/competency-history a une garde
// d'accès dual rôle (étudiant sur son propre id, ou son professeur) — pas
// de raccourci "/students/me/...", donc studentId (son propre user.id) est
// requis ici, contrairement à getMyCompetencyProfile ci-dessus.
export interface CompetencyObservationRead {
  competency_code: string;
  performance_copie: number;
  submission_id: string;
  created_at: string;
}

export async function getMyCompetencyHistory(
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

export type VideoOverviewStatus = "not_requested" | "pending" | "ready" | "failed";
// Cycle de vie générique (audio/flashcards) — mêmes 4 valeurs que
// VideoOverviewStatus, cf. GenerationStatus côté backend.
export type GenerationStatus = "not_requested" | "pending" | "ready" | "failed";

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
  // profil de compétence (même RecommendationService._to_recommendation_
  // read que côté professeur), jamais un champ natif dupliqué en base.
  is_persistent_weakness: boolean;
  // NotebookLM (§7, Partie 2/2) — tous None/not_requested tant qu'aucun
  // StudentNotebook n'est rattaché (best-effort, cf. RecommendationService.
  // _to_recommendation_read). notebook_chat_url est le seul indicateur
  // fiable de "un notebook existe" (contrairement aux formats individuels,
  // qui peuvent rester None même avec un notebook réel — audio/flashcards
  // sont best-effort, jamais garantis).
  audio_overview_url: string | null;
  // Régénération à la demande (chantier "régénération NotebookLM") — même
  // cycle de vie explicite que video_overview_status (toujours renseigné).
  audio_overview_status: GenerationStatus;
  flashcards_url: string | null;
  flashcards_status: GenerationStatus;
  video_overview_url: string | null;
  video_overview_status: VideoOverviewStatus;
  notebook_chat_url: string | null;
}

export async function getMyRecommendations(
  accessToken: string,
  studentId: string,
  moduleId: string,
): Promise<RecommendedExerciseRead[]> {
  const response = await fetch(
    `${API_URL}/students/${studentId}/recommendations?module_id=${moduleId}`,
    { headers: authHeaders(accessToken) },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface VideoOverviewStateRead {
  video_overview_status: VideoOverviewStatus;
  video_overview_url: string | null;
}

export async function requestVideoOverview(
  accessToken: string,
  studentId: string,
  recommendationId: string,
): Promise<VideoOverviewStateRead> {
  const response = await fetch(
    `${API_URL}/students/${studentId}/recommendations/${recommendationId}/generate-video`,
    { method: "POST", headers: authHeaders(accessToken) },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface AudioOverviewStateRead {
  audio_overview_status: GenerationStatus;
  audio_overview_url: string | null;
}

export async function regenerateAudioOverview(
  accessToken: string,
  studentId: string,
  recommendationId: string,
): Promise<AudioOverviewStateRead> {
  const response = await fetch(
    `${API_URL}/students/${studentId}/recommendations/${recommendationId}/regenerate-audio`,
    { method: "POST", headers: authHeaders(accessToken) },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface FlashcardsStateRead {
  flashcards_status: GenerationStatus;
  flashcards_url: string | null;
}

export async function regenerateFlashcards(
  accessToken: string,
  studentId: string,
  recommendationId: string,
): Promise<FlashcardsStateRead> {
  const response = await fetch(
    `${API_URL}/students/${studentId}/recommendations/${recommendationId}/regenerate-flashcards`,
    { method: "POST", headers: authHeaders(accessToken) },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export async function askNotebookChat(
  accessToken: string,
  studentId: string,
  recommendationId: string,
  question: string,
): Promise<string> {
  const response = await fetch(
    `${API_URL}/students/${studentId}/recommendations/${recommendationId}/notebook-chat`,
    {
      method: "POST",
      headers: { ...authHeaders(accessToken), "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    },
  );

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  const body: { answer: string } = await response.json();
  return body.answer;
}

export async function createSubmission(
  accessToken: string,
  exerciseId: string,
  file: File,
): Promise<SubmissionRead> {
  const formData = new FormData();
  formData.append("exercise_id", exerciseId);
  formData.append("document", file);

  const response = await fetch(`${API_URL}/submissions`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: formData,
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}
