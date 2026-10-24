import {
  Award,
  Gavel,
  GitBranch,
  GraduationCap,
  Layers,
  Lightbulb,
  MessageSquare,
  ScanText,
  Scale,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

/**
 * Identité visuelle par agent — un seul système de couleur sémantique
 * (dérivé des tokens existants success/info/warning/primary/muted, jamais
 * une couleur décorative nouvelle), une icône distincte par agent pour la
 * timeline de décisions IA (journal d'exercice + page agent-decisions).
 */
export const AGENT_VISUALS: Record<string, { icon: LucideIcon; tone: string }> = {
  OCR_Extraction_Agent: { icon: ScanText, tone: "text-slate-500 bg-slate-100 dark:text-zinc-400 dark:bg-zinc-800" },
  Document_Structuring_Agent: { icon: Layers, tone: "text-slate-500 bg-slate-100 dark:text-zinc-400 dark:bg-zinc-800" },
  Extraction_Verification_Agent: { icon: ShieldCheck, tone: "text-info bg-info/10" },
  Reasoning_Graph_Agent: { icon: GitBranch, tone: "text-primary bg-primary/10" },
  Solution_Variant_Generation_Agent: { icon: Sparkles, tone: "text-primary bg-primary/10" },
  Comparative_Evaluation_Agent: { icon: Scale, tone: "text-warning bg-warning/10" },
  Pedagogical_Evaluation_Agent: { icon: GraduationCap, tone: "text-warning bg-warning/10" },
  Competency_Assessment_Agent: { icon: Award, tone: "text-warning bg-warning/10" },
  Feedback_Agent: { icon: MessageSquare, tone: "text-info bg-info/10" },
  Recommendation_Agent: { icon: Lightbulb, tone: "text-info bg-info/10" },
  Contestation_Verification_Agent: { icon: Gavel, tone: "text-danger bg-danger/10" },
};

const DEFAULT_AGENT_VISUAL = { icon: Sparkles, tone: "text-slate-500 bg-slate-100 dark:text-zinc-400 dark:bg-zinc-800" };

export function getAgentVisual(agentName: string) {
  return AGENT_VISUALS[agentName] ?? DEFAULT_AGENT_VISUAL;
}

// Clé de traduction "AgentDecisions.agentName_<technique>" par agent connu —
// le nom technique brut (ex. "Document_Structuring_Agent") reste toujours
// affiché à côté (tooltip/sous-titre), jamais masqué, mais n'est plus le
// texte principal. Repli sur une version humanisée automatique (underscores
// -> espaces, suffixe "_Agent" retiré) pour un agent futur pas encore ajouté
// ici — jamais une clé de traduction manquante qui casse le rendu.
const AGENT_NAME_KEYS: Record<string, string> = Object.fromEntries(
  Object.keys(AGENT_VISUALS).map((agentName) => [agentName, `agentName_${agentName}`]),
);

export function getAgentLabel(agentName: string, t: (key: string) => string): string {
  const key = AGENT_NAME_KEYS[agentName];
  if (key) return t(key);
  return agentName.replace(/_Agent$/, "").replace(/_/g, " ");
}
