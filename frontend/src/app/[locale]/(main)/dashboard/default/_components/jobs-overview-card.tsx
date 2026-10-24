"use client";

import { useMemo, useState } from "react";

import { Ban, Check, ChevronDown, Clock, Info, Pause, RefreshCw, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { type JobRead, type JobStatus, type JobsOverview, retryJob } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { classifyError, nodeLabelKey } from "@/lib/pipeline-labels";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<JobStatus, { dot: string; icon: React.ReactNode }> = {
  completed: { dot: "bg-success text-white", icon: <Check className="size-3.5" /> },
  failed: { dot: "bg-danger text-white", icon: <X className="size-3.5" /> },
  running: { dot: "bg-info text-white", icon: <RefreshCw className="size-3.5 animate-spin" /> },
  retrying: { dot: "bg-warning text-white", icon: <RefreshCw className="size-3.5" /> },
  interrupted: { dot: "bg-warning text-white", icon: <Pause className="size-3.5" /> },
  pending: { dot: "bg-muted text-muted-foreground", icon: <Clock className="size-3.5" /> },
  cancelled: { dot: "bg-muted text-muted-foreground", icon: <Ban className="size-3.5" /> },
};

const TERMINAL_STATUSES: JobStatus[] = ["completed", "failed", "cancelled"];

// Style "Repeat" (Uiverse.io by andrew-demchenk0) — pilule rouge, icône qui
// tourne (sens anti-horaire, cf. keyframe spin-reverse dans globals.css) au
// survol ET pendant la vraie relance (isRetrying), pas juste décoratif.
function RetryButton({
  onClick,
  isRetrying,
  label,
  retryingLabel,
}: {
  onClick: () => void;
  isRetrying: boolean;
  label: string;
  retryingLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isRetrying}
      className="group flex h-[34px] shrink-0 items-center justify-center gap-2 rounded-full bg-[#ff362b]/20 px-3.5 text-[15px] font-semibold tracking-wide text-[#ff342b] transition-colors hover:bg-[#ff362b]/35 disabled:pointer-events-none disabled:opacity-70"
    >
      <RefreshCw
        className={cn(
          "size-4",
          isRetrying
            ? "animate-[spin-reverse_2s_linear_infinite]"
            : "group-hover:animate-[spin-reverse_2s_linear_infinite]",
        )}
      />
      <span>{isRetrying ? retryingLabel : label}</span>
    </button>
  );
}

// Gap relevé en test réel : "1011m 58s" (~17h) affiché tel quel, confondu
// avec un temps de traitement normal — au-delà de ce seuil, un Job est
// presque certainement resté bloqué, jamais un traitement légitime.
const ANOMALY_THRESHOLD_SECONDS = 60 * 60;

function getDurationSeconds(startIso: string, endIso: string): number {
  return Math.max(0, Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000));
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return remainder === 0 ? `${minutes}m` : `${minutes}m ${remainder}s`;
}

function formatAnomalyDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return `${hours}h${minutes.toString().padStart(2, "0")}`;
}

function getDurationDisplay(
  job: JobRead,
  t: ReturnType<typeof useTranslations>,
): { text: string; isAnomaly: boolean } | null {
  if (!TERMINAL_STATUSES.includes(job.status)) return null;
  const seconds = getDurationSeconds(job.created_at, job.updated_at);
  if (seconds > ANOMALY_THRESHOLD_SECONDS) {
    return { text: t("anomalyDuration", { duration: formatAnomalyDuration(seconds) }), isAnomaly: true };
  }
  return { text: formatDuration(seconds), isAnomaly: false };
}

// Titre humain — jamais l'id technique du job en texte principal (gap relevé
// en test réel : "c13b9e96" ne dit rien à un admin non-développeur).
// exercise_title/student_full_name sont positionnés en mémoire côté service
// (aucune relation ORM Job -> Submission/Exercise/Student), donc
// potentiellement absents (exercice/soumission supprimé entretemps) — repli
// sur le libellé du flow dans ce cas plutôt qu'un champ vide.
function getJobTitle(job: JobRead, t: ReturnType<typeof useTranslations>): string {
  if (job.student_full_name) {
    return t("submissionLabel", {
      student: job.student_full_name,
      exercise: job.exercise_title ?? t("unknownExercise"),
    });
  }
  if (job.flow_type === "exercise_setup" && job.exercise_title) {
    return t("exerciseSetupLabel", { exercise: job.exercise_title });
  }
  return job.exercise_title ?? t(`flowType.${job.flow_type}`);
}

type TimelineEntry = { kind: "single"; job: JobRead } | { kind: "failure-group"; jobs: JobRead[] };

// Fusionne les échecs répétés d'une même soumission en un seul bloc dépliable
// — gap relevé en test réel : deux échecs de la même étudiante affichés comme
// deux événements indépendants, sans jamais indiquer qu'il s'agit de la même
// soumission ayant retenté deux fois. Les jobs sont déjà triés du plus récent
// au plus ancien (contrat de JobRepository.list_recent) — le groupe apparaît
// donc à la position de son échec le plus récent, jobs[0].
function buildTimelineEntries(jobs: JobRead[]): TimelineEntry[] {
  const entries: TimelineEntry[] = [];
  const groupIndexBySubmission = new Map<string, number>();

  for (const job of jobs) {
    if (job.status === "failed" && job.submission_id) {
      const existingIndex = groupIndexBySubmission.get(job.submission_id);
      const existingEntry = existingIndex !== undefined ? entries[existingIndex] : undefined;
      if (existingEntry && existingEntry.kind === "failure-group") {
        existingEntry.jobs.push(job);
        continue;
      }
      groupIndexBySubmission.set(job.submission_id, entries.length);
      entries.push({ kind: "failure-group", jobs: [job] });
      continue;
    }
    entries.push({ kind: "single", job });
  }
  return entries;
}

const STEPPER_CIRCLE_STYLE: Record<JobStatus, { circle: string; icon: React.ReactNode }> = {
  completed: {
    circle: "bg-emerald-600 text-white dark:bg-emerald-500 dark:text-white shadow-xs",
    icon: <Check className="size-4 stroke-[2.5]" />,
  },
  running: {
    circle:
      "border-2 border-emerald-600 text-emerald-600 bg-emerald-50 dark:border-emerald-400 dark:text-emerald-400 dark:bg-emerald-950/40",
    icon: <RefreshCw className="size-4 animate-spin stroke-[2.5]" />,
  },
  retrying: {
    circle:
      "border-2 border-amber-600 text-amber-600 bg-amber-50 dark:border-amber-400 dark:text-amber-400 dark:bg-amber-950/40",
    icon: <RefreshCw className="size-4 stroke-[2.5]" />,
  },
  interrupted: {
    circle:
      "border-2 border-amber-600 text-amber-600 bg-amber-50 dark:border-amber-400 dark:text-amber-400 dark:bg-amber-950/40",
    icon: <Pause className="size-4 stroke-[2.5]" />,
  },
  failed: {
    circle:
      "border-2 border-rose-600 text-rose-600 bg-rose-50 dark:border-rose-400 dark:text-rose-400 dark:bg-rose-950/40",
    icon: <X className="size-4 stroke-[2.5]" />,
  },
  pending: {
    circle:
      "border-2 border-slate-200 text-slate-400 bg-white dark:border-zinc-800 dark:text-zinc-500 dark:bg-zinc-900",
    icon: <Clock className="size-4 stroke-[2.5]" />,
  },
  cancelled: {
    circle:
      "border-2 border-slate-200 text-slate-400 bg-white dark:border-zinc-800 dark:text-zinc-500 dark:bg-zinc-900",
    icon: <Ban className="size-4 stroke-[2.5]" />,
  },
};

export function JobsOverviewCard({ overview, onRetried }: { overview: JobsOverview; onRetried: () => void }) {
  const t = useTranslations("Overview");

  const timelineEntries = useMemo(() => buildTimelineEntries(overview.recent_jobs).slice(0, 8), [overview.recent_jobs]);

  return (
    <Card className="border-slate-200/90 shadow-2xs dark:border-zinc-800">
      <CardHeader className="border-b border-slate-100 pb-3.5 dark:border-zinc-800">
        <CardTitle className="text-xl font-bold italic leading-none text-slate-900 dark:text-zinc-100">
          {t("jobsHealth")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 pt-5 pb-5">
        {overview.recent_jobs.length > 0 ? (
          <div className="space-y-3.5">
            <p className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-zinc-300">
              {t("recentActivity")}
            </p>

            {timelineEntries.length > 0 ? (
              <div className="relative pt-2">
                {timelineEntries.map((entry) => {
                  if (entry.kind === "failure-group" && entry.jobs.length > 1) {
                    return <FailureGroupRow key={entry.jobs[0].id} jobs={entry.jobs} onRetried={onRetried} />;
                  }
                  const job = entry.kind === "failure-group" ? entry.jobs[0] : entry.job;
                  return <JobTimelineRow key={job.id} job={job} onRetried={onRetried} />;
                })}
              </div>
            ) : (
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 py-6 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
                <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("noFilteredActivity")}</p>
              </div>
            )}
          </div>
        ) : (
          <div className="rounded-xl border border-success/20 bg-success/10 p-4 text-center">
            <p className="text-sm font-semibold text-success">{t("noRecentActivity")}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Une ligne label/valeur — plutôt qu'un empilement de <p> non annotés, pour
// que chaque champ de la carte se comprenne sans avoir à deviner ce qu'il
// représente.
function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-sm font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">{label}</span>
      <span className="font-mono text-base font-medium break-all text-black dark:text-white">{value}</span>
    </div>
  );
}

// Toute l'info secondaire (id, nœud humanisé + brut, horodatage précis,
// erreur brute) est regroupée et structurée ici plutôt qu'éparpillée dans la
// ligne principale ou empilée sans étiquette — la ligne ne garde que le
// titre, le statut et la durée/erreur qui comptent vraiment au premier coup
// d'œil.
function JobIdTooltip({
  job,
  tPipeline,
  nodeLabel,
  locale,
}: {
  job: JobRead;
  tPipeline: ReturnType<typeof useTranslations>;
  nodeLabel: string | null;
  locale: string;
}) {
  const errorCategory = classifyError(job.error_message);
  const hasTechnicalDetail = job.error_message !== null && errorCategory !== "domainMessage";
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="text-slate-400 transition-colors hover:text-slate-700 dark:text-zinc-500 dark:hover:text-zinc-200"
        >
          <Info className="size-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[34rem] max-w-[95vw] gap-0 overflow-hidden rounded-xl border-0 bg-[#F8FBFE] p-0 shadow-xl ring-1 ring-black/5 dark:bg-zinc-900 dark:ring-white/10">
        <div className="flex items-center gap-2 px-5 py-3.5">
          <span className="size-3.5 rounded-full bg-[#ff605c]" />
          <span className="size-3.5 rounded-full bg-[#ffbd44]" />
          <span className="size-3.5 rounded-full bg-[#00ca4e]" />
        </div>
        <div className="flex flex-col gap-5 border-t border-black/5 px-5 py-5 text-left dark:border-white/10">
          <DetailRow label={tPipeline("jobIdLabel")} value={job.id} />
          {nodeLabel ? <DetailRow label={tPipeline("stepLabel")} value={nodeLabel} /> : null}
          {job.current_node ? <DetailRow label={tPipeline("technicalNodeLabel")} value={job.current_node} /> : null}
          {hasTechnicalDetail ? <DetailRow label={tPipeline("technicalDetail")} value={job.error_message} /> : null}
          <DetailRow label={tPipeline("updatedAtLabel")} value={new Date(job.updated_at).toLocaleString(locale)} />
        </div>
      </PopoverContent>
    </Popover>
  );
}

function JobTimelineRow({ job, onRetried }: { job: JobRead; onRetried: () => void }) {
  const t = useTranslations("Overview");
  const tPipeline = useTranslations("PipelineLabels");
  const locale = useLocale();
  const [isRetrying, setIsRetrying] = useState(false);
  const style = STEPPER_CIRCLE_STYLE[job.status];

  const canRetry = job.status === "failed";
  const title = getJobTitle(job, t);
  const nodeLabel = job.current_node
    ? tPipeline(`nodes.${nodeLabelKey(job.current_node)}`, { node: job.current_node })
    : null;
  const errorCategory = classifyError(job.error_message);
  const errorLabel = job.error_message
    ? errorCategory === "domainMessage"
      ? job.error_message
      : tPipeline(`errors.${errorCategory}`)
    : null;
  const duration = getDurationDisplay(job, t);

  const handleRetry = () => {
    const session = getStoredSession();
    if (!session) return;
    setIsRetrying(true);
    retryJob(session.accessToken, job.id)
      .then(() => {
        toast.success(t("retrySuccess"));
        onRetried();
      })
      .catch((retryError) => {
        toast.error(retryError instanceof AuthApiError ? retryError.message : t("retryError"));
      })
      .finally(() => setIsRetrying(false));
  };

  return (
    <div className="group relative flex gap-4 pb-8 last:pb-0">
      {/* Stepper connecting line */}
      <div className="absolute left-[19px] top-[40px] bottom-0 w-[2px] bg-slate-200 dark:bg-zinc-800 group-last:hidden" />

      {/* Stepper Circle */}
      <div
        className={cn(
          "relative z-10 flex size-10 shrink-0 items-center justify-center rounded-full transition-colors",
          style.circle,
        )}
      >
        {style.icon}
      </div>

      {/* Stepper Content */}
      <div className="flex-1 min-w-0 pt-0.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <h4 className="text-base font-bold text-slate-900 dark:text-zinc-100 truncate">{title}</h4>
            <JobIdTooltip job={job} tPipeline={tPipeline} nodeLabel={nodeLabel} locale={locale} />
          </div>
          {canRetry ? (
            <RetryButton
              onClick={handleRetry}
              isRetrying={isRetrying}
              label={t("retryAction")}
              retryingLabel={t("retrying")}
            />
          ) : null}
        </div>

        {/* Durée (terminal uniquement) — le nœud en cours et l'horodatage
            précis sont désormais dans la carte de détail (ⓘ) plutôt que
            répétés ici. */}
        {duration ? (
          <div className="flex flex-wrap items-center gap-3 text-xs font-semibold text-slate-600 dark:text-zinc-400">
            <span className={duration.isAnomaly ? "font-bold text-amber-600" : undefined}>{duration.text}</span>
          </div>
        ) : null}

        {errorLabel ? (
          <p className="mt-1.5 text-sm font-semibold text-rose-600 dark:text-rose-400">{errorLabel}</p>
        ) : null}
      </div>
    </div>
  );
}

function FailureGroupRow({ jobs, onRetried }: { jobs: JobRead[]; onRetried: () => void }) {
  const t = useTranslations("Overview");
  const tPipeline = useTranslations("PipelineLabels");
  const locale = useLocale();
  const [isOpen, setIsOpen] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const style = STEPPER_CIRCLE_STYLE.failed;

  const headJob = jobs[0];
  const olderJobs = jobs.slice(1);

  const title = getJobTitle(headJob, t);
  const nodeLabel = headJob.current_node
    ? tPipeline(`nodes.${nodeLabelKey(headJob.current_node)}`, { node: headJob.current_node })
    : null;
  const errorCategory = classifyError(headJob.error_message);
  const errorLabel = headJob.error_message
    ? errorCategory === "domainMessage"
      ? headJob.error_message
      : tPipeline(`errors.${errorCategory}`)
    : null;
  const duration = getDurationDisplay(headJob, t);

  const handleRetry = () => {
    const session = getStoredSession();
    if (!session) return;
    setIsRetrying(true);
    retryJob(session.accessToken, headJob.id)
      .then(() => {
        toast.success(t("retrySuccess"));
        onRetried();
      })
      .catch((retryError) => {
        toast.error(retryError instanceof AuthApiError ? retryError.message : t("retryError"));
      })
      .finally(() => setIsRetrying(false));
  };

  return (
    <div className="group relative flex gap-4 pb-8 last:pb-0">
      {/* Stepper connecting line */}
      <div className="absolute left-[19px] top-[40px] bottom-0 w-[2px] bg-slate-200 dark:bg-zinc-800 group-last:hidden" />

      {/* Stepper Circle */}
      <div
        className={cn(
          "relative z-10 flex size-10 shrink-0 items-center justify-center rounded-full transition-colors",
          style.circle,
        )}
      >
        {style.icon}
      </div>

      {/* Stepper Content */}
      <div className="flex-1 min-w-0 pt-0.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <h4 className="text-base font-bold text-slate-900 dark:text-zinc-100 truncate">{title}</h4>
            <JobIdTooltip job={headJob} tPipeline={tPipeline} nodeLabel={nodeLabel} locale={locale} />
          </div>
          <RetryButton
            onClick={handleRetry}
            isRetrying={isRetrying}
            label={t("retryAction")}
            retryingLabel={t("retrying")}
          />
        </div>

        {/* Durée (terminal uniquement) — le nœud en cours et l'horodatage
            précis sont désormais dans la carte de détail (ⓘ) plutôt que
            répétés ici. */}
        {duration ? (
          <div className="flex flex-wrap items-center gap-3 text-xs font-semibold text-slate-600 dark:text-zinc-400">
            <span className={duration.isAnomaly ? "font-bold text-amber-600" : undefined}>{duration.text}</span>
          </div>
        ) : null}

        {errorLabel ? (
          <p className="mt-1.5 text-sm font-semibold text-rose-600 dark:text-rose-400">{errorLabel}</p>
        ) : null}

        {/* Collapsible history for repeated failures */}
        <Collapsible open={isOpen} onOpenChange={setIsOpen} className="mt-2.5">
          <CollapsibleTrigger className="flex items-center gap-1 text-xs font-semibold text-slate-500 hover:text-slate-700 dark:text-zinc-400 dark:hover:text-zinc-200">
            <ChevronDown className={cn("size-3.5 transition-transform", isOpen && "rotate-180")} />
            {t("repeatedFailures", { count: jobs.length })}
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-2 flex flex-col gap-2.5 border-l-2 border-rose-500/20 pl-3">
            {olderJobs.map((job) => {
              const jobErrorCategory = classifyError(job.error_message);
              const jobErrorLabel = job.error_message
                ? jobErrorCategory === "domainMessage"
                  ? job.error_message
                  : tPipeline(`errors.${jobErrorCategory}`)
                : null;
              const jobDuration = getDurationDisplay(job, t);
              return (
                <div key={job.id} className="text-xs space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2 font-mono text-[13px] text-slate-500 dark:text-zinc-400">
                    <span>ID: {job.id}</span>
                    <span>·</span>
                    <span>{new Date(job.updated_at).toLocaleString(locale)}</span>
                  </div>
                  {jobErrorLabel ? (
                    <p className="text-xs font-medium text-rose-600 dark:text-rose-400">{jobErrorLabel}</p>
                  ) : null}
                </div>
              );
            })}
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  );
}
