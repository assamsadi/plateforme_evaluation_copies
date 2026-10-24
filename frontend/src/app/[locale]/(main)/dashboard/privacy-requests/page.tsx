"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { DataTableSkeleton } from "@/app/[locale]/(main)/dashboard/_components/data-table-skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { listPendingPrivacyRequests, type DataPrivacyRequestRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { PrivacyRequests } from "./_components/privacy-requests";
import { RequestDetailDialog } from "./_components/request-detail-dialog";

function PrivacyRequestsPageContent() {
  const t = useTranslations("PrivacyRequests");
  const [requests, setRequests] = useState<DataPrivacyRequestRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewTarget, setViewTarget] = useState<DataPrivacyRequestRead | null>(null);

  const fetchRequests = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await listPendingPrivacyRequests(session.accessToken);
      setRequests(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchRequests();
  }, [fetchRequests]);

  function handleUpdated(updated: DataPrivacyRequestRead) {
    if (updated.status === "completed" || updated.status === "rejected") {
      // Sortie définitive de la file DPO active — retirée de la liste.
      setRequests((prev) => prev.filter((r) => r.id !== updated.id));
      setViewTarget(null);
      toast.success(t("updateSuccess", { name: updated.user_full_name }));
      return;
    }
    setRequests((prev) => prev.map((r) => (r.id === updated.id ? updated : r)));
    setViewTarget(updated);
    toast.success(t("updateSuccess", { name: updated.user_full_name }));
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
      <PrivacyRequests requests={requests} onView={setViewTarget} />
      <RequestDetailDialog
        request={viewTarget}
        open={Boolean(viewTarget)}
        onOpenChange={(open) => !open && setViewTarget(null)}
        onUpdated={handleUpdated}
      />
    </>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <PrivacyRequestsPageContent />
    </AuthGuard>
  );
}
