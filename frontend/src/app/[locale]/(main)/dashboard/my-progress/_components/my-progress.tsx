"use client";

import { BookOpen } from "lucide-react";
import { useTranslations } from "next-intl";

import type { AssignedExerciseRead, CompetencyObservationRead, RecommendedExerciseRead, StudentCompetencyReport } from "@/lib/student-api";

import { CompetencyDetailCard } from "./competency-detail-card";
import { CompetencyEvolutionChart } from "./competency-evolution-chart";
import { CompetencyRadarChart } from "./competency-radar-chart";
import { RecommendationCard } from "./recommendation-card";

export interface ModuleOption {
  id: string;
  name: string;
}

export function MyProgress({
  modules,
  selectedModuleId,
  report,
  history,
  recommendations,
  exercises,
  isLoading,
}: {
  modules: ModuleOption[];
  selectedModuleId: string | null;
  report: StudentCompetencyReport | null;
  history: CompetencyObservationRead[];
  recommendations: RecommendedExerciseRead[];
  exercises: AssignedExerciseRead[];
  isLoading: boolean;
}) {
  const t = useTranslations("MyProgress");
  const selectedModuleName = modules.find((module) => module.id === selectedModuleId)?.name;

  return (
    <div className="flex flex-col gap-6">
      {/* Le module se choisit désormais depuis la sidebar (sous-sections de
          "My Progress", cf. AppSidebar.withModuleSubItems) — plus de
          sélecteur en double ici, juste un rappel du module affiché. */}
      {selectedModuleName ? (
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-muted-foreground">{t("moduleSelectorLabel")}</span>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-gradient-to-r from-primary/15 via-emerald-400/15 to-primary/15 px-3.5 py-1 shadow-xs ring-1 ring-primary/25">
            <BookOpen className="size-3.5 text-primary" />
            <span className="text-sm font-bold italic text-primary">{selectedModuleName}</span>
          </span>
        </div>
      ) : null}

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-16">
          <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">{t("loading")}</p>
        </div>
      ) : !report || report.lines.length === 0 ? (
        <div className="rounded-xl border border-dashed py-16 text-center">
          <p className="text-sm text-muted-foreground">{t("noCompetencyData")}</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <div className="flex flex-col items-center gap-2 rounded-2xl border border-slate-200/80 bg-emerald-50/40 py-6 dark:border-zinc-800 dark:bg-emerald-950/20">
              <h2 className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("radarTitle")}</h2>
              <CompetencyRadarChart lines={report.lines} />
            </div>

            <div className="flex flex-col gap-2 rounded-2xl border border-slate-200/80 bg-emerald-50/40 p-6 dark:border-zinc-800 dark:bg-emerald-950/20">
              <h2 className="text-center text-base font-bold text-slate-900 dark:text-zinc-100">{t("evolutionTitle")}</h2>
              <CompetencyEvolutionChart observations={history} />
            </div>
          </div>

          <div className="flex flex-col gap-6 mt-2">
            <div className="flex flex-col gap-3.5">
              <h2 className="text-lg font-bold text-slate-900 dark:text-zinc-100">{t("detailTitle")}</h2>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {report.lines.map((line) => (
                  <CompetencyDetailCard key={line.competency} line={line} />
                ))}
              </div>
            </div>

            <div className="flex flex-col gap-3.5">
            <h2 className="text-lg font-bold text-slate-900 dark:text-zinc-100">{t("recommendationsTitle")}</h2>
            {recommendations.length === 0 ? (
              <div className="rounded-xl border border-dashed py-10 text-center">
                <p className="text-sm text-muted-foreground">{t("noRecommendations")}</p>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                {recommendations.map((recommendation) => (
                  <RecommendationCard
                    key={recommendation.id}
                    recommendation={recommendation}
                    exercise={exercises.find((e) => e.id === recommendation.exercise_id) ?? null}
                  />
                ))}
              </div>
            )}
          </div>
          </div>
        </>
      )}
    </div>
  );
}
