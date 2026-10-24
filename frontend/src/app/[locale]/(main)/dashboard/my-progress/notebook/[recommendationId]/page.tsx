"use client";

import { useCallback, useEffect, useState } from "react";

import { useParams, useSearchParams } from "next/navigation";

import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { useAuth } from "@/lib/auth-context";
import { getMyRecommendations, type RecommendedExerciseRead } from "@/lib/student-api";

import { NotebookWorkspace } from "./_components/notebook-workspace";

function NotebookPageContent() {
  const t = useTranslations("NotebookSheet");
  const { user } = useAuth();
  const { recommendationId } = useParams<{ recommendationId: string }>();
  const searchParams = useSearchParams();
  const moduleId = searchParams.get("module_id");

  const [recommendations, setRecommendations] = useState<RecommendedExerciseRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRecommendations = useCallback(async () => {
    if (!user || !moduleId) {
      setIsLoading(false);
      return;
    }
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      setRecommendations(await getMyRecommendations(session.accessToken, user.id, moduleId));
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [user, moduleId, t]);

  useEffect(() => {
    fetchRecommendations();
  }, [fetchRecommendations]);

  // Aucun endpoint GET /recommendations/{id} dédié — on retrouve la
  // recommandation dans la liste du module, même principe que les autres
  // écrans de cette app qui refetchent une liste plutôt que d'ajouter un
  // endpoint mono-item.
  const recommendation = recommendations.find((r) => r.id === recommendationId) ?? null;

  function updateRecommendation(patch: Partial<RecommendedExerciseRead>) {
    setRecommendations((prev) =>
      prev.map((r) => (r.id === recommendationId ? { ...r, ...patch } : r)),
    );
  }

  if (!moduleId) {
    return (
      <div className="p-4 md:p-6">
        <Alert variant="destructive">
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription>{t("notFoundMessage")}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 md:p-6">
        <Alert variant="destructive">
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3 p-4 md:p-6">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-[60vh] w-full" />
      </div>
    );
  }

  if (!recommendation) {
    return (
      <div className="p-4 md:p-6">
        <div className="rounded-xl border border-dashed py-16 text-center">
          <p className="text-sm text-muted-foreground">{t("notFoundMessage")}</p>
        </div>
      </div>
    );
  }

  return <NotebookWorkspace recommendation={recommendation} onRecommendationChange={updateRecommendation} />;
}

export default function Page() {
  return (
    <AuthGuard requiredRole="student">
      <NotebookPageContent />
    </AuthGuard>
  );
}
