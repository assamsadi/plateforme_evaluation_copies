"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { DataTableSkeleton } from "@/app/[locale]/(main)/dashboard/_components/data-table-skeleton";
import { DecisionDetailDialog } from "@/app/[locale]/(main)/dashboard/_components/decision-detail-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { listAgentDecisions, type AgentDecisionLogRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { AgentDecisions } from "./_components/agent-decisions";

// GET /admin/agent-decisions est paginé par curseur côté backend (max
// 200/page) ; on charge la première grande page, cf. commentaire équivalent
// dans users/page.tsx.
const PAGE_SIZE = 200;

function AgentDecisionsPageContent() {
  const t = useTranslations("AgentDecisions");
  const [logs, setLogs] = useState<AgentDecisionLogRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewTarget, setViewTarget] = useState<AgentDecisionLogRead | null>(null);

  const fetchLogs = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listAgentDecisions(session.accessToken, { limit: PAGE_SIZE });
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

  return (
    <>
      <AgentDecisions logs={logs} onView={setViewTarget} />
      <DecisionDetailDialog
        log={viewTarget}
        open={Boolean(viewTarget)}
        onOpenChange={(open) => !open && setViewTarget(null)}
      />
    </>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <AgentDecisionsPageContent />
    </AuthGuard>
  );
}
