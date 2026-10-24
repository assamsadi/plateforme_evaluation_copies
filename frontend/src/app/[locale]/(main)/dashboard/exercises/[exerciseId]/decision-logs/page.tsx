"use client";

import { useCallback, useEffect, useState } from "react";

import { useParams } from "next/navigation";

import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Link } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { getExercise, listExerciseDecisionLogs, type ExerciseRead } from "@/lib/professor-api";

import { DecisionLogsView } from "../_components/decision-logs-view";

function ExerciseDecisionLogsPageContent() {
  const t = useTranslations("ExerciseDetail");
  const { exerciseId } = useParams<{ exerciseId: string }>();
  const [exercise, setExercise] = useState<ExerciseRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchExercise = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await getExercise(session.accessToken, exerciseId);
      setExercise(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [exerciseId, t]);

  useEffect(() => {
    fetchExercise();
  }, [fetchExercise]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Link
          href={`/dashboard/exercises/${exerciseId}`}
          className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-sm font-medium text-muted-foreground shadow-2xs transition-colors hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          {t("back")}
        </Link>
      </div>

      {error ? (
        <Alert variant="destructive" className="rounded-xl">
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : isLoading || !exercise ? (
        <div className="flex items-center gap-2 py-8">
          <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-xs font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</span>
        </div>
      ) : (
        <DecisionLogsView
          title={t("decisionLogsTitle", { title: exercise.title })}
          fetchLogs={(accessToken) => listExerciseDecisionLogs(accessToken, exercise.id, { limit: 100 })}
        />
      )}
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <ExerciseDecisionLogsPageContent />
    </AuthGuard>
  );
}
