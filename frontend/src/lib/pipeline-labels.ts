// Traduction centralisée des données brutes du pipeline (nom de nœud
// LangGraph, message d'erreur technique) en quelque chose de lisible pour
// un professeur/admin non-développeur — utilisé à la fois par l'écran admin
// (jobs-overview-card.tsx) et par la bannière de statut professeur
// (pipeline-status-banner.tsx), jamais dupliqué entre les deux.
//
// error_message est toujours `str(exception)` côté backend (jamais une
// classe nommée, cf. app/graph/job_sync.py) — impossible de faire une
// correspondance exacte pour les erreurs inattendues, d'où une
// classification par motif plutôt qu'un dictionnaire. Le texte brut original
// reste toujours accessible (jamais perdu), seulement relégué au second plan.

const KNOWN_NODES = new Set([
  "entry_router_node",
  "scan_quality_control_node",
  "document_structuring_node",
  "await_structuring_resolution_node",
  "extraction_verification_node",
  "reasoning_graph_node",
  "solution_variant_generation_node",
  "await_clarification_resolution_node",
  "question_attachment_node",
  "await_student_verification_node",
  "contestation_verification_node",
  "teacher_arbitration_node",
  "comparative_evaluation_node",
  "evaluation_node",
  "competency_assessment_node",
  "recommendation_node",
  "feedback_node",
  "await_variant_candidate_resolution_node",
]);

// Clé de traduction sous "PipelineLabels.nodes.<clé>" — "unknown" si un
// nouveau nœud est ajouté côté graphe sans mise à jour de cette liste (le
// nom technique brut reste affichable à côté, jamais masqué silencieusement).
export function nodeLabelKey(node: string | null): string {
  if (node && KNOWN_NODES.has(node)) return node;
  return "unknown";
}

export type ErrorCategory = "configError" | "connectionError" | "rateLimited" | "domainMessage" | "generic";

// Motifs testés dans l'ordre, premier qui matche gagne. "domainMessage" =
// message déjà rédigé en français par le code métier (DocumentQualityError,
// OCRExtractionError, etc.) — affiché tel quel. "generic" = repli quand rien
// ne permet de reconnaître le message (ex. exception inattendue capturée par
// le catch-all Celery on_failure()).
export function classifyError(message: string | null): ErrorCategory {
  if (!message) return "generic";
  const trimmed = message.trim();
  if (/^'[^']+'$/.test(trimmed)) return "configError";
  if (/kafka|connectionerror|econnrefused|timeout/i.test(trimmed)) return "connectionError";
  if (/\b429\b|rate.?limit/i.test(trimmed)) return "rateLimited";
  // Une vraie phrase française (avec espaces) est traitée comme un message
  // métier déjà lisible ; un token brut sans espace (repr d'exception,
  // identifiant) tombe dans le repli générique plutôt que d'être affiché tel quel.
  if (trimmed.includes(" ")) return "domainMessage";
  return "generic";
}
