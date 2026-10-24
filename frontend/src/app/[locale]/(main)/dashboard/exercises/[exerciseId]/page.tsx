"use client";

import { useCallback, useEffect, useState } from "react";

import { useParams } from "next/navigation";

import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Link } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { getExercise, type ExerciseRead, type JobRead } from "@/lib/professor-api";

import { ExerciseDetail } from "./_components/exercise-detail";
import { PipelineStatusBanner } from "./_components/pipeline-status-banner";

function ExerciseDetailPageContent() {
  const t = useTranslations("ExerciseDetail");
  const { exerciseId } = useParams<{ exerciseId: string }>();
  const [exercise, setExercise] = useState<ExerciseRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // `silent` : un rafraîchissement déclenché en arrière-plan (ex. le bandeau
  // pipeline détectant la fin du job) NE DOIT JAMAIS remettre isLoading à
  // true. Sinon la page retombe dans la branche "if (isLoading || !exercise)
  // return <spinner>" ci-dessous, ce qui démonte tout l'arbre (bandeau,
  // panneaux blocs/soumissions) — le bandeau remonte alors, son effet de
  // montage resonde le statut, retrouve "completed", rappelle ce même
  // rafraîchissement... boucle infinie constatée en test réel (rafale
  // continue sur 4 endpoints jusqu'à saturer le backend). Seul le chargement
  // initial (mount) doit afficher le spinner plein-page.
  const fetchExercise = useCallback(
    async (options?: { silent?: boolean }) => {
      const session = getStoredSession();
      if (!session) return;

      if (!options?.silent) setIsLoading(true);
      setError(null);
      try {
        const result = await getExercise(session.accessToken, exerciseId);
        setExercise(result);
      } catch (fetchError) {
        setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
      } finally {
        if (!options?.silent) setIsLoading(false);
      }
    },
    [exerciseId, t],
  );

  useEffect(() => {
    fetchExercise();
  }, [fetchExercise]);

  const handlePipelineStatusChange = useCallback(
    (job: JobRead) => {
      if (job.status === "completed") fetchExercise({ silent: true });
    },
    [fetchExercise],
  );

  if (error) {
    return (
      <Alert variant="destructive" className="rounded-xl">
        <AlertTitle>{t("errorTitle")}</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading || !exercise) {
    return (
      <div className="flex items-center gap-2 py-8">
        <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-xs font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <Link
          href="/dashboard/exercises"
          className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-sm font-medium text-muted-foreground shadow-2xs transition-colors hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" />
          {t("back")}
        </Link>
      </div>

      <PipelineStatusBanner exerciseId={exerciseId} onStatusChange={handlePipelineStatusChange} />

      <ExerciseDetail exercise={exercise} onUpdated={setExercise} />
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <ExerciseDetailPageContent />
    </AuthGuard>
  );
}
