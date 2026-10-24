"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { listPendingClarifications, type ReasoningClarificationRequestRead } from "@/lib/professor-api";

import { Clarifications } from "./_components/clarifications";

function ClarificationsPageContent() {
  const t = useTranslations("Clarifications");
  const [requests, setRequests] = useState<ReasoningClarificationRequestRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRequests = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await listPendingClarifications(session.accessToken);
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

  function handleResolved(resolved: ReasoningClarificationRequestRead) {
    setRequests((prev) => prev.filter((r) => r.id !== resolved.id));
    toast.success(t("resolveSuccess"));
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

  return <Clarifications requests={requests} onResolved={handleResolved} />;
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <ClarificationsPageContent />
    </AuthGuard>
  );
}
