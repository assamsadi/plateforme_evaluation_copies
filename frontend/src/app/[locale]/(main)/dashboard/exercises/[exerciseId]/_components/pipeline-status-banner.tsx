"use client";

import { useCallback, useEffect, useState } from "react";

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { classifyError, nodeLabelKey } from "@/lib/pipeline-labels";
import {
  confirmExerciseStructuring,
  getExercisePipelineStatus,
  type JobRead,
  type JobStatus,
} from "@/lib/professor-api";
import { cn } from "@/lib/utils";

const TERMINAL_STATUSES: JobStatus[] = ["completed", "failed", "cancelled"];

// Stepper à 3 étapes (remplace le StatusBadge à plat) — les 7 valeurs réelles
// de JobStatus se replient sur ces 3 étapes visuelles :
//   pending/running/retrying/interrupted -> étape 1 (active, pastille pulsante)
//   completed -> étape 2 (les 2 étapes précédentes marquées faites)
//   failed/cancelled -> étape 1 marquée en erreur/neutre (jamais "faite")
// Le détail exact du statut (retrying, interrupted, etc.) reste affiché en
// texte + tooltip juste après le stepper — rien n'est perdu, seule la
// représentation visuelle change.
const STEP_KEYS = ["stepDocumentReceived", "stepProcessingStarted", "stepBlocksReady"] as const;

function stepIndexForStatus(status: JobStatus): number {
  return status === "completed" ? 2 : 1;
}

export function PipelineStatusBanner({
  exerciseId,
  onStatusChange,
}: {
  exerciseId: string;
  onStatusChange?: (job: JobRead) => void;
}) {
  const t = useTranslations("ExerciseDetail");
  const tPipeline = useTranslations("PipelineLabels");
  const [job, setJob] = useState<JobRead | null>(null);
  const [isConfirming, setIsConfirming] = useState(false);

  const fetchStatus = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    try {
      const result = await getExercisePipelineStatus(session.accessToken, exerciseId);
      setJob(result);
      if (result) onStatusChange?.(result);
    } catch {
      // Silencieux : ce bandeau est une commodité, pas une donnée critique —
      // ne bloque jamais l'affichage du reste de la page en cas d'échec.
    }
  }, [exerciseId, onStatusChange]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  useEffect(() => {
    // job === null tant qu'aucun document n'a encore été déposé (page déjà
    // ouverte avant l'upload) — il faut continuer à sonder dans ce cas,
    // sinon un job créé APRÈS le montage du bandeau n'est jamais détecté.
    // On n'arrête que sur un statut terminal confirmé.
    if (job && TERMINAL_STATUSES.includes(job.status)) return;
    const interval = setInterval(fetchStatus, 10_000);
    return () => clearInterval(interval);
  }, [job, fetchStatus]);

  const handleConfirm = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsConfirming(true);
    try {
      await confirmExerciseStructuring(session.accessToken, exerciseId);
      toast.success(t("confirmStructuringSuccess"));
      await fetchStatus();
    } catch (confirmError) {
      toast.error(confirmError instanceof AuthApiError ? confirmError.message : t("confirmStructuringError"));
    } finally {
      setIsConfirming(false);
    }
  }, [exerciseId, fetchStatus, t]);

  if (!job) return null;

  const errorCategory = classifyError(job.error_message);
  const errorLabel = job.error_message
    ? errorCategory === "domainMessage"
      ? job.error_message
      : tPipeline(`errors.${errorCategory}`)
    : null;
  const hasTechnicalDetail =
    job.current_node !== null || (job.error_message !== null && errorCategory !== "domainMessage");

  const stepIndex = stepIndexForStatus(job.status);
  const isFailed = job.status === "failed";
  const isCancelled = job.status === "cancelled";

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200/80 bg-slate-50/80 px-4 py-3 text-sm backdrop-blur-sm dark:border-zinc-800 dark:bg-zinc-900/80">
      <span className="font-semibold text-slate-700 dark:text-zinc-300">{t("pipelineStatusLabel")}</span>

      <div className="flex items-center gap-1.5">
        {STEP_KEYS.map((labelKey, i) => {
          const isDone = i < stepIndex;
          const isActive = i === stepIndex;
          const dotIsError = isActive && isFailed;
          const dotIsCancelled = isActive && isCancelled;
          const dotIsPulsing = isActive && !isFailed && !isCancelled;

          return (
            <div key={labelKey} className="flex items-center gap-1.5">
              <span
                className={cn(
                  "size-2.5 shrink-0 rounded-full",
                  dotIsError && "bg-coral",
                  dotIsCancelled && "bg-slate-300 dark:bg-zinc-600",
                  dotIsPulsing && "animate-pulse bg-forest-500 dark:bg-forest-500",
                  !dotIsError && !dotIsCancelled && !dotIsPulsing && isDone && "bg-forest-700 dark:bg-forest-500",
                  !isDone && !isActive && "bg-slate-200 dark:bg-zinc-700",
                )}
              />
              <span
                className={cn(
                  "text-xs font-semibold whitespace-nowrap",
                  isDone || isActive ? "text-slate-700 dark:text-zinc-300" : "text-slate-400 dark:text-zinc-600",
                )}
              >
                {t(labelKey)}
              </span>
              {i < STEP_KEYS.length - 1 ? <span className="h-px w-4 shrink-0 bg-slate-200 dark:bg-zinc-700" /> : null}
            </div>
          );
        })}
      </div>

      <span className="text-slate-500 dark:text-zinc-400">{t(`jobStatus_${job.status}`)}</span>
      {job.current_node ? (
        <span className="text-slate-500 dark:text-zinc-400">
          {tPipeline(`nodes.${nodeLabelKey(job.current_node)}`, { node: job.current_node })}
        </span>
      ) : null}
      {errorLabel ? <span className="text-sm font-medium text-danger">{errorLabel}</span> : null}
      {hasTechnicalDetail ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              className="text-slate-400 transition-colors hover:text-slate-700 dark:text-zinc-500 dark:hover:text-zinc-200"
            >
              <Info className="size-3.5" />
            </button>
          </TooltipTrigger>
          <TooltipContent className="max-w-xs text-left whitespace-normal">
            {job.current_node ? <p className="font-mono">{job.current_node}</p> : null}
            {job.error_message && errorCategory !== "domainMessage" ? (
              <p className="mt-1 font-mono">
                {tPipeline("technicalDetail")} : {job.error_message}
              </p>
            ) : null}
          </TooltipContent>
        </Tooltip>
      ) : null}
      {job.status === "interrupted" ? (
        <Button size="sm" onClick={handleConfirm} disabled={isConfirming}>
          {t("confirmStructuringAction")}
        </Button>
      ) : null}
    </div>
  );
}
