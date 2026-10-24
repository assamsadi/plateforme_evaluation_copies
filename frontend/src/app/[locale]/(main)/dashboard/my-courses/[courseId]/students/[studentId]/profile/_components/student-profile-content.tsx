"use client";

import { useCallback, useEffect, useState } from "react";

import { IconChartRadar, IconSparkles } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  getStudentCompetencyHistory,
  getStudentCompetencyProfile,
  getStudentModuleSummary,
  getStudentRecommendations,
  type CompetencyObservationRead,
  type RecommendedExerciseRead,
  type StudentCompetencyReport,
  type StudentModuleOptionRead,
  type StudentModuleSummaryRead,
  type StudentPublic,
} from "@/lib/professor-api";

import { CompetencyCard } from "./competency-card";
import { CompetencyEvolutionChart } from "./competency-evolution-chart";
import { CompetencyRadarChart } from "./competency-radar-chart";
import { RecommendationCard } from "./recommendation-card";

export function StudentProfileContent({
  student,
  modules,
  selectedModuleId,
  onModuleChange,
}: {
  student: StudentPublic;
  modules: StudentModuleOptionRead[];
  selectedModuleId: string;
  onModuleChange: (moduleId: string) => void;
}) {
  const t = useTranslations("StudentProfilePage");

  const [summary, setSummary] = useState<StudentModuleSummaryRead | null>(null);
  const [report, setReport] = useState<StudentCompetencyReport | null>(null);
  const [history, setHistory] = useState<CompetencyObservationRead[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendedExerciseRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchModuleData = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const [summaryResult, reportResult, historyResult, recommendationsResult] = await Promise.all([
        getStudentModuleSummary(session.accessToken, student.id, selectedModuleId),
        getStudentCompetencyProfile(session.accessToken, student.id, selectedModuleId),
        getStudentCompetencyHistory(session.accessToken, student.id, selectedModuleId),
        getStudentRecommendations(session.accessToken, student.id, selectedModuleId),
      ]);
      setSummary(summaryResult);
      setReport(reportResult);
      setHistory(historyResult);
      setRecommendations(recommendationsResult);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [student.id, selectedModuleId, t]);

  useEffect(() => {
    fetchModuleData();
  }, [fetchModuleData]);

  const selectedModule = modules.find((m) => m.module_id === selectedModuleId);
  const generalAverage =
    summary && summary.max_score > 0 ? Math.round((summary.total_score / summary.max_score) * 200) / 10 : null;

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="grid flex-1 grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricCard label={t("infoEmail")} value={student.email} small />
          <MetricCard label={t("infoModule")} value={selectedModule?.module_name ?? ""} small />
          <MetricCard
            label={t("infoSubmissions")}
            value={summary ? t("submissionsValue", { total: summary.total_submissions, evaluated: summary.evaluated_submissions }) : "—"}
          />
          <MetricCard label={t("infoAverage")} value={generalAverage !== null ? t("averageValue", { score: generalAverage }) : "—"} />
        </div>

        {modules.length > 1 ? (
          <Select value={selectedModuleId} onValueChange={onModuleChange}>
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {modules.map((module) => (
                <SelectItem key={module.module_id} value={module.module_id}>
                  {module.module_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-lg border border-danger/20 bg-danger/10 p-4 text-sm text-danger">{error}</div>
      ) : isLoading ? (
        <div className="flex items-center justify-center gap-2 py-16">
          <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">{t("loading")}</p>
        </div>
      ) : !report || report.lines.length === 0 ? (
        <div className="rounded-xl border-[0.5px] border-border bg-muted/30 py-16 text-center">
          <p className="text-sm text-muted-foreground">{t("noCompetencyData")}</p>
        </div>
      ) : (
        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">
              <IconChartRadar className="size-4" stroke={1.75} />
              {t("tabOverview")}
            </TabsTrigger>
            <TabsTrigger value="recommendations">
              <IconSparkles className="size-4" stroke={1.75} />
              {t("tabRecommendations")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="mt-6 flex flex-col gap-8">
            <section className="flex flex-col gap-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="text-lg font-medium text-foreground">{t("radarTitle")}</h2>
                <p className="text-sm text-muted-foreground">
                  {t("radarSummary", {
                    count: report.lines.filter((l) => l.mastery_level > 50).length,
                    total: report.lines.length,
                  })}
                </p>
              </div>
              {/* Fond teinté primary/5 (pas bg-card blanc) — la carte doit se
                  distinguer du fond de page ; largeur du graphique bornée
                  pour éviter la zone morte constatée sur une carte pleine
                  largeur. */}
              <div className="flex justify-center rounded-xl border-[0.5px] border-primary/15 bg-primary/5 p-5">
                <div className="w-full max-w-sm">
                  <CompetencyRadarChart lines={report.lines} />
                </div>
              </div>
            </section>

            <section className="flex flex-col gap-4">
              <h2 className="text-lg font-medium text-foreground">{t("detailTitle")}</h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {report.lines.map((line) => (
                  <CompetencyCard key={line.competency} line={line} />
                ))}
              </div>
            </section>

            <section className="flex flex-col gap-4">
              <h2 className="text-lg font-medium text-foreground">{t("evolutionTitle")}</h2>
              <div className="rounded-xl border-[0.5px] border-border bg-card p-5">
                <CompetencyEvolutionChart observations={history} />
              </div>
            </section>
          </TabsContent>

          <TabsContent value="recommendations" className="mt-6 flex flex-col gap-4">
            {recommendations.length === 0 ? (
              <div className="rounded-xl border-[0.5px] border-border bg-muted/30 py-16 text-center">
                <p className="text-sm text-muted-foreground">{t("noRecommendations")}</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                {recommendations.map((recommendation) => (
                  <RecommendationCard key={recommendation.id} recommendation={recommendation} />
                ))}
              </div>
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

// Metric card — fond légèrement teinté (primary/5, pas gris neutre),
// libellé au-dessus en petit, valeur en grand. Remplace le simple texte
// aligné à plat de la première version, jugée trop terne.
function MetricCard({ label, value, small = false }: { label: string; value: string; small?: boolean }) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border-[0.5px] border-primary/15 bg-primary/5 p-4">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={small ? "truncate text-sm font-medium text-foreground" : "text-xl font-medium text-foreground"}>
        {value}
      </span>
    </div>
  );
}
