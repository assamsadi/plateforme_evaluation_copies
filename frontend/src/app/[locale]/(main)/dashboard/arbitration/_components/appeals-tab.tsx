"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Appeals } from "@/app/[locale]/(main)/dashboard/appeals/_components/appeals";
import { ResolveAppealDialog } from "@/app/[locale]/(main)/dashboard/appeals/_components/resolve-appeal-dialog";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { listPendingAppeals, type GradeAppealRead } from "@/lib/professor-api";

const PAGE_SIZE = 200;

// Recours de note ("arbitrage" au sens large pour un professeur — gap
// fermé, test réel 2026-08-31) : un étudiant peut déposer un vrai recours
// (POST /appeals, GradeAppeal, correctement persisté), mais rien ne le
// signalait sur la page "Arbitrage" — seule /dashboard/appeals (page
// séparée, jamais reliée visuellement) l'exposait. Réutilise tel quel
// Appeals/ResolveAppealDialog (aucune logique dupliquée), même pattern de
// fetch autonome que CorrectionsTab/IncidentsTab ci-à-côté.
export function AppealsTab() {
  const t = useTranslations("Appeals");
  const [appeals, setAppeals] = useState<GradeAppealRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolveTarget, setResolveTarget] = useState<GradeAppealRead | null>(null);

  const fetchAppeals = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listPendingAppeals(session.accessToken, { limit: PAGE_SIZE });
      setAppeals(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchAppeals();
  }, [fetchAppeals]);

  function handleResolved(resolved: GradeAppealRead) {
    setAppeals((prev) => prev.filter((a) => a.id !== resolved.id));
    toast.success(t("resolveSuccess", { name: resolved.student_full_name }));
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
      <div className="flex items-center justify-center gap-2 py-12">
        <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-xs font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</span>
      </div>
    );
  }

  return (
    <>
      <Appeals appeals={appeals} onResolve={setResolveTarget} />
      <ResolveAppealDialog
        appeal={resolveTarget}
        open={Boolean(resolveTarget)}
        onOpenChange={(open) => !open && setResolveTarget(null)}
        onResolved={handleResolved}
      />
    </>
  );
}
