"use client";

import { useCallback, useEffect, useState } from "react";

import { useParams } from "next/navigation";

import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getProgram, type ProgramRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { GroupsTab } from "./_components/groups-tab";
import { ModulesTab } from "./_components/modules-tab";
import { ProgramHeader } from "./_components/program-header";

function ProgramDetailPageContent() {
  const { programId } = useParams<{ programId: string }>();
  const t = useTranslations("ProgramDetail");
  const [program, setProgram] = useState<ProgramRead | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProgram = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await getProgram(session.accessToken, programId);
      setProgram(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [programId, t]);

  useEffect(() => {
    fetchProgram();
  }, [fetchProgram]);

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading || !program) {
    return (
      <div className="flex flex-col gap-6">
        <Skeleton className="h-16 w-full" />
        <div className="flex flex-col gap-3">
          <Skeleton className="h-9 w-48" />
          <Skeleton className="h-64 w-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <ProgramHeader program={program} />

      <Tabs defaultValue="groups">
        <TabsList>
          <TabsTrigger value="groups">{t("tabGroups")}</TabsTrigger>
          <TabsTrigger value="modules">{t("tabModules")}</TabsTrigger>
        </TabsList>
        <TabsContent value="groups">
          <GroupsTab programId={programId} />
        </TabsContent>
        <TabsContent value="modules">
          <ModulesTab programId={programId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <ProgramDetailPageContent />
    </AuthGuard>
  );
}
