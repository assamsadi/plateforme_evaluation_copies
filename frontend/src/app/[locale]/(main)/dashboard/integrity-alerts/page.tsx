"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { DataTableSkeleton } from "@/app/[locale]/(main)/dashboard/_components/data-table-skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { listUnresolvedIntegrityAlerts, type IntegrityAlertRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { FlagStudentDialog } from "./_components/flag-student-dialog";
import { IntegrityAlerts } from "./_components/integrity-alerts";
import { ResolveAlertDialog } from "./_components/resolve-alert-dialog";

function IntegrityAlertsPageContent() {
  const t = useTranslations("IntegrityAlerts");
  const [alerts, setAlerts] = useState<IntegrityAlertRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [resolveTarget, setResolveTarget] = useState<IntegrityAlertRead | null>(null);
  const [isFlagDialogOpen, setIsFlagDialogOpen] = useState(false);

  const fetchAlerts = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await listUnresolvedIntegrityAlerts(session.accessToken);
      setAlerts(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  function handleResolved(resolved: IntegrityAlertRead) {
    // Résolue = elle sort de la liste des non-résolues (le backend ne
    // renvoie que list_pending) — pas une mise à jour en place.
    setAlerts((prev) => prev.filter((a) => a.id !== resolved.id));
    toast.success(t("resolveSuccess", { name: resolved.student_full_name }));
  }

  function handleFlagged(alert: IntegrityAlertRead) {
    setAlerts((prev) => [alert, ...prev]);
    toast.success(t("flagSuccess", { name: alert.student_full_name }));
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading) {
    return <DataTableSkeleton columnCount={6} />;
  }

  return (
    <>
      <IntegrityAlerts alerts={alerts} onResolve={setResolveTarget} onFlagStudent={() => setIsFlagDialogOpen(true)} />
      <ResolveAlertDialog
        alert={resolveTarget}
        open={Boolean(resolveTarget)}
        onOpenChange={(open) => !open && setResolveTarget(null)}
        onResolved={handleResolved}
      />
      <FlagStudentDialog
        open={isFlagDialogOpen}
        onOpenChange={setIsFlagDialogOpen}
        onFlagged={handleFlagged}
      />
    </>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <IntegrityAlertsPageContent />
    </AuthGuard>
  );
}
