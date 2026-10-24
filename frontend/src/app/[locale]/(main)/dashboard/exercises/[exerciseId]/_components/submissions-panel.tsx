"use client";

import { useCallback, useEffect, useState } from "react";

import { Users } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  type ExerciseRead,
  listExerciseSubmissions,
  type SubmissionStatus,
  type SubmissionSummaryRead,
} from "@/lib/professor-api";

import { SubmissionDetailDialog } from "./submission-detail-dialog";

const submissionStatusTone: Record<SubmissionStatus, StatusTone> = {
  pending_ocr: "neutral",
  pending_student_verification: "warning",
  pending_arbitration: "warning",
  pending_evaluation: "info",
  evaluated: "success",
  absent: "danger",
};

const PAGE_SIZE = 100;

export function SubmissionsPanel({ exercise }: { exercise: ExerciseRead }) {
  const t = useTranslations("ExerciseDetail");
  const locale = useLocale();
  const [submissions, setSubmissions] = useState<SubmissionSummaryRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailTarget, setDetailTarget] = useState<SubmissionSummaryRead | null>(null);

  const fetchSubmissions = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const page = await listExerciseSubmissions(session.accessToken, exercise.id, { limit: PAGE_SIZE });
      setSubmissions(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("submissionsFetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [exercise.id, t]);

  useEffect(() => {
    fetchSubmissions();
  }, [fetchSubmissions]);

  const evaluatedCount = submissions.filter((s) => s.status === "evaluated").length;

  return (
    <>
      <Card className="overflow-hidden border-slate-200/90 shadow-2xs dark:border-zinc-800">
        <CardHeader className="border-b border-slate-100 pb-4 pt-4 dark:border-zinc-800">
          <CardTitle className="font-serif text-base font-bold text-slate-900 dark:text-zinc-100">
            {t("submissionsTitle")}
            {submissions.length > 0 && (
              <StatusBadge
                tone="success"
                status={t("evaluatedCountBadge", { evaluated: evaluatedCount, total: submissions.length })}
                className="ml-2 text-xs"
              />
            )}
          </CardTitle>
          <p className="mt-1 text-sm font-medium text-slate-500 dark:text-zinc-400">{t("submissionsDescription")}</p>
        </CardHeader>
        <CardContent className="pt-4 pb-3">
          {isLoading ? (
            <div className="flex items-center gap-2 py-4">
              <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("submissionsLoading")}</p>
            </div>
          ) : error ? (
            <p className="text-sm font-medium text-danger">{error}</p>
          ) : submissions.length === 0 ? (
            <EmptyState icon={Users} title={t("emptySubmissionsTitle")} description={t("noSubmissions")} />
          ) : (
            <div className="flex flex-col gap-2 pb-2">
              {submissions.map((submission) => (
                <button
                  key={submission.id}
                  type="button"
                  onClick={() => setDetailTarget(submission)}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-slate-50/60 px-4 py-3 text-left transition-colors hover:border-primary/40 hover:bg-emerald-50/20 dark:border-zinc-800 dark:bg-zinc-900/60"
                >
                  <div className="min-w-0">
                    <span className="font-bold text-sm text-slate-900 dark:text-zinc-100">
                      {submission.student_full_name}
                    </span>
                    {submission.attempt_number > 1 ? (
                      <span className="ml-2 text-xs font-semibold text-slate-500 dark:text-zinc-400">
                        {t("attemptLabel", { number: submission.attempt_number })}
                      </span>
                    ) : null}
                    <div className="mt-0.5 text-xs font-semibold text-slate-600 dark:text-zinc-400">
                      {new Date(submission.created_at).toLocaleString(locale)}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    {submission.total_score !== null ? (
                      <span className="font-mono text-base font-bold text-slate-900 dark:text-zinc-100">
                        {submission.total_score} pts
                      </span>
                    ) : null}
                    <StatusBadge
                      tone={submissionStatusTone[submission.status]}
                      status={t(`submissionStatus_${submission.status}`)}
                      className="text-xs"
                    />
                  </div>
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <SubmissionDetailDialog
        submission={detailTarget}
        open={Boolean(detailTarget)}
        onOpenChange={(open) => !open && setDetailTarget(null)}
      />
    </>
  );
}
