"use client";

import { useCallback, useEffect, useState } from "react";

import { FileText, Gavel, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Separator } from "@/components/ui/separator";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  getSubmissionFeedback,
  listSubmissionAppeals,
  listSubmissionEvaluations,
  type AppealStatus,
  type EvaluationRead,
  type FeedbackReportRead,
  type GradeAppealRead,
  type SubmissionRead,
} from "@/lib/student-api";

import { FileAppealDialog } from "./file-appeal-dialog";

const appealStatusTone: Record<AppealStatus, StatusTone> = {
  pending: "warning",
  under_review: "info",
  resolved: "success",
};

function AppealRow({ appeal }: { appeal: GradeAppealRead }) {
  const t = useTranslations("SubmissionDetailDialog");
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-slate-100 bg-slate-50/60 p-3.5 dark:border-zinc-800 dark:bg-zinc-800/40">
      <div className="flex items-center justify-between gap-2">
        <StatusBadge tone={appealStatusTone[appeal.status]} status={t(`appealStatus_${appeal.status}`)} />
        <span className="font-mono text-xs text-slate-400 dark:text-zinc-500">
          {t("appealOriginalScore", { score: appeal.original_score })}
        </span>
      </div>
      <p className="text-sm leading-relaxed text-slate-600 dark:text-zinc-400">{appeal.reason}</p>
      {appeal.status === "resolved" ? (
        <div className="mt-1 rounded-lg border border-slate-200/60 bg-white p-2 text-sm dark:border-zinc-700/60 dark:bg-zinc-900">
          <p className="font-semibold text-slate-700 dark:text-zinc-300">
            {t(`appealResolution_${appeal.resolution}`)}
            {appeal.revised_score !== null ? ` — ${t("appealRevisedScore", { score: appeal.revised_score })}` : ""}
          </p>
          {appeal.review_comment ? (
            <p className="mt-1 text-slate-500 dark:text-zinc-400">{appeal.review_comment}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

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
  submission: SubmissionRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("SubmissionDetailDialog");
  const [evaluations, setEvaluations] = useState<EvaluationRead[]>([]);
  const [feedback, setFeedback] = useState<FeedbackReportRead | null>(null);
  const [appeals, setAppeals] = useState<GradeAppealRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAppealDialogOpen, setIsAppealDialogOpen] = useState(false);

  const fetchEvaluations = useCallback(async () => {
    const session = getStoredSession();
    if (!session || !submission) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await listSubmissionEvaluations(session.accessToken, submission.id);
      setEvaluations(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }

    // Best-effort, jamais bloquant pour l'affichage des notes : un 404
    // (pas encore généré par le pipeline, cf. FeedbackReportService) est
    // l'état normal pour la quasi-totalité des soumissions de cet
    // environnement de dev (aucun worker Celery ne tourne) — jamais une
    // bannière d'erreur pour ça, juste une absence de section.
    try {
      const feedbackResult = await getSubmissionFeedback(
        session.accessToken, submission.student_id, submission.id,
      );
      setFeedback(feedbackResult);
    } catch {
      setFeedback(null);
    }

    try {
      const appealsResult = await listSubmissionAppeals(session.accessToken, submission.id);
      setAppeals(appealsResult);
    } catch {
      // Non-bloquant, même principe que le feedback ci-dessus.
      setAppeals([]);
    }
  }, [submission, t]);

  function handleAppealFiled(appeal: GradeAppealRead) {
    setAppeals((prev) => [appeal, ...prev]);
  }

  useEffect(() => {
    if (open && submission) fetchEvaluations();
  }, [open, submission, fetchEvaluations]);

  const totalScore = evaluations.reduce((sum, e) => sum + e.score, 0);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto p-0 sm:max-w-lg">
        <div className="h-1.5 w-full bg-primary" />

        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <FileText className="size-4" />
              </div>
              <div>
                <DialogTitle className="text-base font-semibold text-slate-900 dark:text-zinc-100">
                  {submission?.exercise_title}
                </DialogTitle>
                {evaluations.length > 0 ? (
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-zinc-400">
                    {t("totalScoreLabel", { score: totalScore })}
                  </p>
                ) : null}
              </div>
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

              {feedback ? (
                <>
                  <Separator className="bg-slate-100 dark:bg-zinc-800" />
                  <div className="flex flex-col gap-2 rounded-lg border border-info/20 bg-info/10 p-3.5">
                    <div className="flex items-center gap-1.5 text-sm font-semibold text-info">
                      <Sparkles className="size-3.5" />
                      {t("feedbackTitle")}
                    </div>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-zinc-300">
                      {feedback.feedback_text}
                    </p>
                  </div>
                </>
              ) : null}

              {evaluations.length > 0 ? (
                <>
                  <Separator className="bg-slate-100 dark:bg-zinc-800" />
                  <div className="flex flex-col gap-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                        {t("appealsTitle")}
                      </span>
                      <Button size="sm" variant="outline" onClick={() => setIsAppealDialogOpen(true)}>
                        <Gavel className="size-3.5" /> {t("fileAppealAction")}
                      </Button>
                    </div>
                    {appeals.length > 0 ? (
                      <div className="flex flex-col gap-2">
                        {appeals.map((appeal) => (
                          <AppealRow key={appeal.id} appeal={appeal} />
                        ))}
                      </div>
                    ) : null}
                  </div>
                </>
              ) : null}
            </div>
          )}
        </div>
      </DialogContent>

      <FileAppealDialog
        submission={submission}
        evaluations={evaluations}
        open={isAppealDialogOpen}
        onOpenChange={setIsAppealDialogOpen}
        onFiled={handleAppealFiled}
      />
    </Dialog>
  );
}
