"use client";

import { useCallback, useEffect, useState } from "react";

import { useParams } from "next/navigation";

import { AlertTriangle, ArrowLeft, Award, Eye, EyeOff } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Link } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { listMySubmissions, type SubmissionRead } from "@/lib/student-api";

import { SubmissionResultsContent } from "./_components/submission-results-content";

const PAGE_SIZE = 200;

function SubmissionResultsPageInner() {
  const t = useTranslations("SubmissionResultsPage");
  const locale = useLocale();
  const { submissionId } = useParams<{ submissionId: string }>();
  const [submission, setSubmission] = useState<SubmissionRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [score, setScore] = useState<{ total_score: number; max_score: number; is_fully_graded: boolean } | null>(null);
  const [isScoreRevealed, setIsScoreRevealed] = useState(false);
  const [displayedScore, setDisplayedScore] = useState(0);

  // Compteur rapide (ease-out, ~900ms) déclenché à chaque révélation — le
  // chiffre "monte" jusqu'à la vraie note plutôt que d'apparaître figé.
  useEffect(() => {
    if (!score || !isScoreRevealed) {
      setDisplayedScore(0);
      return;
    }
    const target = Number(score.total_score);
    const duration = 900;
    const startTime = performance.now();
    let frameId: number;

    function tick(now: number) {
      const progress = Math.min((now - startTime) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayedScore(target * eased);
      if (progress < 1) frameId = requestAnimationFrame(tick);
    }

    frameId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameId);
  }, [isScoreRevealed, score]);

  const fetchSubmission = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const page = await listMySubmissions(session.accessToken, { limit: PAGE_SIZE });
      const found = page.items.find((s) => s.id === submissionId) ?? null;
      if (!found) {
        setError(t("submissionNotFound"));
      }
      setSubmission(found);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [submissionId, t]);

  useEffect(() => {
    fetchSubmission();
  }, [fetchSubmission]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Link
          href="/dashboard/my-exams"
          className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-sm font-medium text-muted-foreground shadow-2xs transition-colors hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          {t("backToMyExams")}
        </Link>
      </div>

      {error ? (
        <Alert variant="destructive" className="rounded-xl">
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : isLoading || !submission ? (
        <div className="flex items-center gap-2 py-8">
          <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm font-medium text-muted-foreground">{t("loading")}</span>
        </div>
      ) : (
        <>
          {score && !score.is_fully_graded ? (
            <Alert className="rounded-xl border-warning/30 bg-warning/10 text-foreground">
              <AlertTriangle className="size-4 text-warning" />
              <AlertTitle>{t("incompleteGradingTitle")}</AlertTitle>
              <AlertDescription>{t("incompleteGradingDescription")}</AlertDescription>
            </Alert>
          ) : null}

          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <Award className="size-5" />
              </div>
              <div>
                <p className="text-sm text-muted-foreground">
                  {submission.student_full_name} · {t("submittedOn", { date: new Date(submission.created_at).toLocaleDateString(locale) })}
                </p>
              </div>
            </div>

            {score ? (
              <button
                type="button"
                onClick={() => setIsScoreRevealed((prev) => !prev)}
                className="group flex flex-col items-center gap-1.5"
              >
                {/* Cachet "copie corrigée" — sceau rond en encre rouge tamponné
                    en biais sur fond papier, chiffre qui compte à la révélation. */}
                <span
                  className="relative flex size-44 -rotate-6 flex-col items-center justify-center gap-1 rounded-full border-4 border-double border-red-600/80 bg-[#fdfaf3] shadow-[0_1px_3px_rgba(0,0,0,0.15)] transition-transform duration-300 group-hover:-rotate-3 dark:bg-zinc-800/80"
                  style={{ boxShadow: "inset 0 0 0 1px rgba(220,38,38,0.15)" }}
                >
                  <span
                    className={`[font-family:var(--font-handwriting)] text-6xl leading-none font-bold text-red-700/90 transition-all duration-300 dark:text-red-500/90 ${
                      isScoreRevealed ? "blur-none opacity-100" : "blur-md opacity-80 select-none"
                    }`}
                    style={{ textShadow: "0 0 0.5px rgba(185,28,28,0.6)" }}
                  >
                    {displayedScore.toFixed(2)}
                  </span>
                  <span
                    className={`[font-family:var(--font-handwriting)] text-2xl leading-none font-semibold text-red-700/70 dark:text-red-500/70 ${
                      isScoreRevealed ? "" : "blur-md opacity-80 select-none"
                    }`}
                  >
                    / {Number(score.max_score).toFixed(2)}
                  </span>
                  <span className="absolute -bottom-2 -right-2 flex size-9 items-center justify-center rounded-full border border-red-600/30 bg-[#fdfaf3] shadow-sm dark:bg-zinc-800">
                    {isScoreRevealed ? (
                      <EyeOff className="size-4.5 text-red-700/70 dark:text-red-500/70" />
                    ) : (
                      <Eye className="size-4.5 text-red-700/70 dark:text-red-500/70" />
                    )}
                  </span>
                </span>
                {!isScoreRevealed ? (
                  <span className="text-xs font-medium text-muted-foreground">{t("revealScoreHint")}</span>
                ) : null}
              </button>
            ) : null}
          </div>

          <SubmissionResultsContent submission={submission} onScoreLoaded={setScore} />
        </>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="student">
      <SubmissionResultsPageInner />
    </AuthGuard>
  );
}
