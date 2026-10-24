"use client";

import { useCallback, useEffect, useState } from "react";

import { CheckCircle2, ExternalLink, FileText, HelpCircle, XCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { StatusBadge } from "@/components/ui/status-badge";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  getSubmissionCopyReport,
  listSubmissionEvaluations,
  type CopyReport,
  type EvaluationRead,
  type SubmissionSummaryRead,
} from "@/lib/professor-api";

function EvaluationRow({ evaluation }: { evaluation: EvaluationRead }) {
  const t = useTranslations("SubmissionDetailDialog");
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-100 bg-slate-50/60 p-3.5 dark:border-zinc-800 dark:bg-zinc-800/40">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
          {t("questionLabel", { order: evaluation.question_order })}
        </span>
        <span className="font-mono text-sm font-bold text-slate-700 dark:text-zinc-300">{evaluation.score} pts</span>
      </div>
      {evaluation.criteria.length > 0 ? (
        <ul className="mt-1 flex flex-col gap-1.5 border-t border-slate-200/60 pt-2 dark:border-zinc-700/60">
          {evaluation.criteria.map((criterion) => (
            <li key={criterion.id} className="flex items-center justify-between gap-2 text-sm text-slate-600 dark:text-zinc-400">
              <span className="truncate">{criterion.criterion_label ?? criterion.competency_code ?? t("competencyLine")}</span>
              <span className="font-mono font-semibold text-slate-700 dark:text-zinc-300">+{criterion.points_awarded}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function SubmissionDetailDialog({
  submission,
  open,
  onOpenChange,
}: {
  submission: SubmissionSummaryRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("SubmissionDetailDialog");
  const [evaluations, setEvaluations] = useState<EvaluationRead[]>([]);
  const [copyReport, setCopyReport] = useState<CopyReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDetail = useCallback(async () => {
    const session = getStoredSession();
    if (!session || !submission) return;
    setIsLoading(true);
    setError(null);
    try {
      const [evaluationsResult, copyReportResult] = await Promise.all([
        listSubmissionEvaluations(session.accessToken, submission.id),
        submission.status === "evaluated"
          ? getSubmissionCopyReport(session.accessToken, submission.id)
          : Promise.resolve(null),
      ]);
      setEvaluations(evaluationsResult);
      setCopyReport(copyReportResult);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [submission, t]);

  useEffect(() => {
    if (open && submission) fetchDetail();
  }, [open, submission, fetchDetail]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto p-0 sm:max-w-lg">
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                  <FileText className="size-4" />
                </div>
                <div>
                  <DialogTitle className="text-base font-semibold text-slate-900 dark:text-zinc-100">
                    {submission ? t("title", { name: submission.student_full_name }) : ""}
                  </DialogTitle>
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-zinc-400">
                    {t("attemptScoreSubtitle", { attempt: submission?.attempt_number ?? 1, score: submission?.total_score ?? "-" })}
                  </p>
                </div>
              </div>
              {/* Gap fermé (test réel 2026-08-31) : aucun accès au document
                  original déposé par l'étudiant depuis cet écran — ouverture
                  en nouvel onglet, même convention que les liens NotebookLM
                  (pas de visionneuse PDF intégrée dans ce projet). */}
              {submission?.document_url ? (
                <a
                  href={submission.document_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border bg-background px-2.5 py-1.5 text-sm font-medium text-muted-foreground shadow-2xs transition-colors hover:bg-muted hover:text-foreground"
                >
                  <ExternalLink className="size-3.5" />
                  {t("viewOriginalAction")}
                </a>
              ) : null}
            </div>
          </DialogHeader>

          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-12">
              <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <p className="text-xs font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</p>
            </div>
          ) : error ? (
            <div className="mt-4 rounded-lg border border-danger/20 bg-danger/10 p-3 text-xs font-medium text-danger">
              {error}
            </div>
          ) : (
            <div className="mt-5 flex flex-col gap-4">
              {copyReport ? (
                <div className="flex flex-wrap gap-2">
                  <StatusBadge
                    tone="success"
                    status={
                      <>
                        <CheckCircle2 className="mr-1 size-3" />
                        {t("questionsClear", { count: copyReport.overview.questions_sans_ambiguite })}
                      </>
                    }
                  />
                  <StatusBadge
                    tone="warning"
                    status={
                      <>
                        <HelpCircle className="mr-1 size-3" />
                        {t("questionsNeedReview", { count: copyReport.overview.questions_necessitant_un_regard })}
                      </>
                    }
                  />
                  {copyReport.overview.consigne_non_respectee_count > 0 ? (
                    <StatusBadge
                      tone="danger"
                      status={
                        <>
                          <XCircle className="mr-1 size-3" />
                          {t("instructionsNotRespected", { count: copyReport.overview.consigne_non_respectee_count })}
                        </>
                      }
                    />
                  ) : null}
                </div>
              ) : null}

              <Separator className="bg-slate-100 dark:bg-zinc-800" />

              {evaluations.length === 0 ? (
                <div className="rounded-xl border border-slate-100 bg-slate-50/60 py-8 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
                  <p className="text-xs font-medium text-slate-400 dark:text-zinc-500">{t("noEvaluations")}</p>
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {[...evaluations]
                    .sort((a, b) => a.question_order - b.question_order)
                    .map((evaluation) => (
                      <EvaluationRow key={evaluation.id} evaluation={evaluation} />
                    ))}
                </div>
              )}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
