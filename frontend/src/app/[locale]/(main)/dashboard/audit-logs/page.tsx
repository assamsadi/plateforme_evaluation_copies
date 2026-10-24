"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { DataTableSkeleton } from "@/app/[locale]/(main)/dashboard/_components/data-table-skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { listAuditLogs, type AuditLogRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { AuditLogs } from "./_components/audit-logs";

// GET /admin/audit-logs est paginé par curseur côté backend (max 200/page) ;
// on charge la première grande page comme pour Users/Programs — pas de
// "load more" ici, cf. commentaire équivalent dans users/page.tsx.
const PAGE_SIZE = 200;

function AuditLogsPageContent() {
  const t = useTranslations("AuditLogs");
  const [logs, setLogs] = useState<AuditLogRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchLogs = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listAuditLogs(session.accessToken, { limit: PAGE_SIZE });
      setLogs(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

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

  return <AuditLogs logs={logs} />;
}

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <AuditLogsPageContent />
    </AuthGuard>
  );
}
