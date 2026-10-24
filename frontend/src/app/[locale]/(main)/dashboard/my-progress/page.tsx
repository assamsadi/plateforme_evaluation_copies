"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useSearchParams } from "next/navigation";

import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { useAuth } from "@/lib/auth-context";
import {
  getMyCompetencyHistory,
  getMyCompetencyProfile,
  getMyRecommendations,
  listAssignedExercises,
  type AssignedExerciseRead,
  type CompetencyObservationRead,
  type RecommendedExerciseRead,
  type StudentCompetencyReport,
} from "@/lib/student-api";

import { MyProgress, type ModuleOption } from "./_components/my-progress";

function MyProgressPageContent() {
  const t = useTranslations("MyProgress");
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const [exercises, setExercises] = useState<AssignedExerciseRead[]>([]);
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const [report, setReport] = useState<StudentCompetencyReport | null>(null);
  const [history, setHistory] = useState<CompetencyObservationRead[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendedExerciseRead[]>([]);
  const [isLoadingModules, setIsLoadingModules] = useState(true);
  const [isLoadingReport, setIsLoadingReport] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const modules: ModuleOption[] = useMemo(() => {
    const seen = new Map<string, string>();
    for (const exercise of exercises) seen.set(exercise.module_id, exercise.module_name);
    return Array.from(seen, ([id, name]) => ({ id, name }));
  }, [exercises]);

  useEffect(() => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoadingModules(true);
    setError(null);
    listAssignedExercises(session.accessToken, { limit: 200 })
      .then((page) => {
        setExercises(page.items);
        // Module tiré de l'URL (navigation directe depuis une sous-section
        // de sidebar "My Progress") s'il est valide, sinon le premier module
        // assigné par défaut — aucun agrégat "tous modules" n'existe côté
        // backend (StudentCompetencyProfile est scopé par module, cf.
        // docstring GET /students/me/competency-profile) : un module doit
        // toujours être sélectionné explicitement.
        if (page.items.length > 0) {
          const urlModuleId = searchParams.get("module_id");
          const isValidUrlModule = Boolean(urlModuleId) && page.items.some((e) => e.module_id === urlModuleId);
          setSelectedModuleId(isValidUrlModule ? urlModuleId! : page.items[0].module_id);
        }
      })
      .catch((fetchError) => {
        setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
      })
      .finally(() => setIsLoadingModules(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ne fetch qu'une fois ; le changement d'URL après montage est géré par l'effet suivant
  }, [t]);

  // Navigation directe depuis un sous-item de sidebar pendant que la page
  // est déjà montée (changement de query sans remount) — synchronise
  // selectedModuleId sur module_id dès qu'il change dans l'URL.
  useEffect(() => {
    const urlModuleId = searchParams.get("module_id");
    if (!urlModuleId || exercises.length === 0) return;
    const isValid = exercises.some((e) => e.module_id === urlModuleId);
    if (isValid && urlModuleId !== selectedModuleId) setSelectedModuleId(urlModuleId);
  }, [searchParams, exercises, selectedModuleId]);

  const fetchReport = useCallback(async () => {
    if (!user || !selectedModuleId) return;
    const session = getStoredSession();
    if (!session) return;

    setIsLoadingReport(true);
    setError(null);
    try {
      const [profileResult, recommendationsResult, historyResult] = await Promise.all([
        getMyCompetencyProfile(session.accessToken, selectedModuleId),
        getMyRecommendations(session.accessToken, user.id, selectedModuleId),
        getMyCompetencyHistory(session.accessToken, user.id, selectedModuleId),
      ]);
      setReport(profileResult);
      setRecommendations(recommendationsResult);
      setHistory(historyResult);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoadingReport(false);
    }
  }, [user, selectedModuleId, t]);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoadingModules) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-9 w-64" />
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-20 w-full" />
        ))}
      </div>
    );
  }

  if (modules.length === 0) {
    return (
      <div className="rounded-xl border border-dashed py-16 text-center">
        <p className="text-sm text-muted-foreground">{t("noModules")}</p>
      </div>
    );
  }

  return (
    <MyProgress
      modules={modules}
      selectedModuleId={selectedModuleId}
      report={report}
      history={history}
      recommendations={recommendations}
      exercises={exercises}
      isLoading={isLoadingReport}
    />
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="student">
      <MyProgressPageContent />
    </AuthGuard>
  );
}
