import type { StatusTone } from "@/components/ui/status-badge";
import type { ClarificationSeverity, ReasoningClarificationRequestRead } from "@/lib/professor-api";

// Déduit l'agent source SANS nouveau champ backend — les 3 agents qui
// produisent une ReasoningClarificationRequest se distinguent déjà
// entièrement par les champs existants (jamais une supposition sur le
// texte de la question) :
// - comparative_clarification_kind renseigné -> Comparative_Evaluation_Agent
//   (seul agent à poser ce champ, ALTERNATIVE_ANSWER/COHERENCE_AMBIGUITY).
// - variant_id renseigné (sans kind) -> Reasoning_Graph_Agent (rattaché à
//   une SolutionVariant, jamais à une Question directement).
// - ni l'un ni l'autre -> Extraction_Verification_Agent (rattaché à une
//   Question via related_entity_type, jamais de variant_id).
export function deriveAgentName(request: ReasoningClarificationRequestRead): string {
  if (request.comparative_clarification_kind) return "Comparative_Evaluation_Agent";
  if (request.variant_id) return "Reasoning_Graph_Agent";
  return "Extraction_Verification_Agent";
}

// "informational" -> "info" (bleu), jamais "neutral" (gris muet, réservé par
// StatusBadge à "aucun statut réel" — une clarification informative EST un
// statut réel, juste non bloquant, pas la même chose qu'une absence de
// statut). Corrigé : c'était la cause directe du tableau presque
// entièrement gris (la majorité des clarifications réelles sont
// informationnelles).
export const severityTone: Record<ClarificationSeverity, StatusTone> = {
  blocking: "danger",
  warning: "warning",
  informational: "info",
};

// Bordure gauche colorée par sévérité (pas une boîte encadrée séparée —
// une seule carte par dialog, cf. resolve-clarification-dialog) — même
// échelle de tons que StatusBadge, jamais une couleur inventée.
export const severityBorderClasses: Record<ClarificationSeverity, string> = {
  blocking: "border-danger",
  warning: "border-warning",
  informational: "border-info",
};
