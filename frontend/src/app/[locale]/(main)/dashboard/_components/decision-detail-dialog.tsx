"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";

import { DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { LatexText } from "@/components/ui/latex-text";
import { Separator } from "@/components/ui/separator";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import type { AgentDecisionLogRead, ProfessorValidationStatus } from "@/lib/admin-api";
import { getAgentLabel, getAgentVisual } from "@/lib/agent-visuals";
import { cn } from "@/lib/utils";

export const validationStatusTone: Record<ProfessorValidationStatus, StatusTone> = {
  not_reviewed: "neutral",
  validated: "success",
  corrected: "warning",
};

// confidence_score=0 + model_version="unknown" est le repli déterministe
// écrit par les agents quand le LLM n'a jamais pu être appelé (ex. plafond
// d'appels dépassé, cf. Document_Structuring_Agent._classify_block) — pas
// une vraie évaluation à 0% de confiance. On distingue visuellement cet
// échec structurel plutôt que de l'afficher comme un résultat normal.
function isFailureLog(log: AgentDecisionLogRead): boolean {
  return log.confidence_score === 0 && log.model_version === "unknown";
}

function DetailBlock({ label, value, danger }: { label: string; value: string; danger?: boolean }) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border p-3",
        danger
          ? "border-destructive/30 bg-destructive/5 dark:border-destructive/40 dark:bg-destructive/10"
          : "border-black/5 bg-white/70 dark:border-white/10 dark:bg-white/5",
      )}
    >
      <span
        className={cn(
          "flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider",
          danger ? "text-destructive" : "text-slate-400 dark:text-zinc-500",
        )}
      >
        {danger ? <AlertTriangle className="size-3.5" /> : null}
        {label}
      </span>
      <LatexText
        text={value}
        className={cn("text-sm", danger ? "text-destructive dark:text-red-300" : "text-slate-900 dark:text-zinc-100")}
      />
    </div>
  );
}

export function DecisionDetailDialog({
  log,
  open,
  onOpenChange,
}: {
  log: AgentDecisionLogRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("AgentDecisions");
  const { icon: AgentIcon, tone } = getAgentVisual(log?.agent_name ?? "");
  const failure = log ? isFailureLog(log) : false;

  return (
    <TrafficLightDialog open={open} onOpenChange={onOpenChange} contentClassName="sm:max-w-2xl">
      <>
        <DialogHeader className="gap-2">
          <div className="flex items-center gap-3">
            <div className={cn("flex size-9 items-center justify-center rounded-lg", tone)}>
              <AgentIcon className="size-4" />
            </div>
            <div>
              <DialogTitle className="text-base font-semibold text-slate-900 dark:text-zinc-100">
                {log ? getAgentLabel(log.agent_name, t) : ""}
              </DialogTitle>
              <p className="mt-0.5 font-mono text-xs text-slate-500 dark:text-zinc-400">{log?.agent_name}</p>
            </div>
          </div>
        </DialogHeader>

        {log ? (
          <div className="mt-5 flex flex-col gap-3.5">
            <div className="grid grid-cols-3 gap-3 rounded-xl border border-black/5 bg-white/70 p-3.5 dark:border-white/10 dark:bg-white/5">
              <div className="flex flex-col gap-1">
                <span className="text-[13px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  {t("columnValidation")}
                </span>
                <StatusBadge
                  tone={validationStatusTone[log.professor_validation_status]}
                  status={t(`validation_${log.professor_validation_status}`)}
                  className="w-fit"
                />
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-[13px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  {t("columnConfidence")}
                </span>
                {failure ? (
                  <span className="text-sm font-semibold text-slate-400 italic dark:text-zinc-500">
                    {t("failureNotApplicable")}
                  </span>
                ) : (
                  <span className="text-sm font-bold text-slate-900 dark:text-zinc-100">
                    {log.confidence_score !== null ? `${(log.confidence_score * 100).toFixed(0)}%` : "—"}
                  </span>
                )}
              </div>
              <div className="flex flex-col gap-1">
                <span className="text-[13px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                  {t("modelLabel")}
                </span>
                {failure ? (
                  <span className="text-sm font-semibold text-slate-400 italic dark:text-zinc-500">
                    {t("failureNotApplicable")}
                  </span>
                ) : (
                  <span className="truncate font-mono text-xs font-medium text-slate-800 dark:text-zinc-200">
                    {log.model_version}
                  </span>
                )}
              </div>
            </div>

            <Separator className="bg-slate-100 dark:bg-zinc-800" />

            <DetailBlock
              label={failure ? t("failureJustification") : t("justification")}
              value={log.justification}
              danger={failure}
            />
            {log.input_summary ? <DetailBlock label={t("inputSummary")} value={log.input_summary} /> : null}
            {log.output_summary ? <DetailBlock label={t("outputSummary")} value={log.output_summary} /> : null}
            {log.professor_correction ? (
              <DetailBlock label={t("professorCorrection")} value={log.professor_correction} />
            ) : null}
          </div>
        ) : null}
      </>
    </TrafficLightDialog>
  );
}
