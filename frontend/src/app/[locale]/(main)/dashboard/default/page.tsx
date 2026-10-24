"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  type JobsOverview,
  type PlatformStatistics,
  getJobsOverview,
  getPlatformStatistics,
} from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { BreakdownCard } from "./_components/breakdown-card";
import { JobsOverviewCard } from "./_components/jobs-overview-card";
import { KpiCards } from "./_components/kpi-cards";
import { KpiCardsSkeleton } from "./_components/kpi-cards-skeleton";
import { UsersByRoleChart } from "./_components/users-by-role-chart";

function OverviewContent() {
  const t = useTranslations("Overview");
  const [stats, setStats] = useState<PlatformStatistics | null>(null);
  const [jobs, setJobs] = useState<JobsOverview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const session = getStoredSession();
    if (!session) return;

    Promise.all([getPlatformStatistics(session.accessToken), getJobsOverview(session.accessToken)])
      .then(([statsResult, jobsResult]) => {
        setStats(statsResult);
        setJobs(jobsResult);
      })
      .catch((fetchError) => {
        setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
      })
      .finally(() => setIsLoading(false));
  }, [t]);

  const refetchJobs = useCallback(() => {
    const session = getStoredSession();
    if (!session) return;
    getJobsOverview(session.accessToken)
      .then(setJobs)
      .catch(() => {
        // Rafraîchissement silencieux après une relance de job — les données
        // déjà affichées restent valides, pas la peine de casser l'écran
        // pour un échec de ce refresh secondaire.
      });
  }, []);

  if (error) {
    return (
      <Alert variant="destructive" className="rounded-2xl">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading || !stats) {
    return <KpiCardsSkeleton />;
  }

  return (
    <div className="flex flex-col gap-4.5">
      <KpiCards stats={stats} />

      <div className="w-full lg:w-1/2">
        <UsersByRoleChart title={t("usersByRole")} usersByRole={stats.users_by_role} />
      </div>

      <div className="w-full lg:w-1/2">
        <BreakdownCard
          title={t("submissionsByStatus")}
          entries={Object.entries(stats.submissions_by_status).map(([key, value]) => ({
            key,
            label: t(`submissionStatus.${key}`),
            value,
          }))}
        />
      </div>

      {jobs ? <JobsOverviewCard overview={jobs} onRetried={refetchJobs} /> : null}
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="admin">
      <OverviewContent />
    </AuthGuard>
  );
}
