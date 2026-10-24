"use client";

import { useCallback, useEffect, useState } from "react";

import { useParams } from "next/navigation";

import { ArrowLeft, ScanText } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Link, useRouter } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  listAssignedExercises,
  listMySubmissions,
  type AssignedExerciseRead,
  type SubmissionRead,
} from "@/lib/student-api";

import { VerifyExtractionContent } from "./_components/verify-extraction-content";

const PAGE_SIZE = 200;

function VerifyExtractionPageInner() {
  const t = useTranslations("VerifyExtractionDialog");
  const locale = useLocale();
  const router = useRouter();
  const { submissionId } = useParams<{ submissionId: string }>();
  const [submission, setSubmission] = useState<SubmissionRead | null>(null);
  const [exercise, setExercise] = useState<AssignedExerciseRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const [submissionsPage, exercisesPage] = await Promise.all([
        listMySubmissions(session.accessToken, { limit: PAGE_SIZE }),
        listAssignedExercises(session.accessToken, { limit: PAGE_SIZE }),
      ]);
      const found = submissionsPage.items.find((s) => s.id === submissionId) ?? null;
      if (!found) {
        setError(t("submissionNotFound"));
      }
      setSubmission(found);
      setExercise(found ? (exercisesPage.items.find((e) => e.id === found.exercise_id) ?? null) : null);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [submissionId, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

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
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
              <ScanText className="size-5" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-foreground">{submission.exercise_title}</h1>
              <p className="text-sm text-muted-foreground">
                {submission.student_full_name} · {t("submittedOn", { date: new Date(submission.created_at).toLocaleDateString(locale) })}
              </p>
            </div>
          </div>

          <VerifyExtractionContent
            submission={submission}
            exercise={exercise}
            onConfirmed={() => router.push("/dashboard/my-exams")}
          />
        </>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="student">
      <VerifyExtractionPageInner />
    </AuthGuard>
  );
}
