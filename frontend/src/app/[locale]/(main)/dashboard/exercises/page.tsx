"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useRouter } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { listMyExercises, type ExerciseRead } from "@/lib/professor-api";

import { Exercises } from "./_components/exercises";

const PAGE_SIZE = 200;

function ExercisesPageContent() {
  const t = useTranslations("Exercises");
  const router = useRouter();
  const [exercises, setExercises] = useState<ExerciseRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchExercises = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listMyExercises(session.accessToken, { limit: PAGE_SIZE });
      setExercises(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchExercises();
  }, [fetchExercises]);

  function handleCreated(created: ExerciseRead) {
    setExercises((prev) => [created, ...prev]);
    toast.success(t("createSuccess", { title: created.title }));
    router.push(`/dashboard/exercises/${created.id}`);
  }

  if (error) {
    return (
      <Alert variant="destructive" className="rounded-2xl">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-12 justify-center">
        <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-xs font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</span>
      </div>
    );
  }

  return (
    <Exercises
      exercises={exercises}
      onView={(exercise) => router.push(`/dashboard/exercises/${exercise.id}`)}
      onCreated={handleCreated}
    />
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <ExercisesPageContent />
    </AuthGuard>
  );
}
