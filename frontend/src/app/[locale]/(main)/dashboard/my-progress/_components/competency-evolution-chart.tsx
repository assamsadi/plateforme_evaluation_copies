"use client";

import { TrendingUp } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { CompetencyObservationRead } from "@/lib/student-api";

const chartConfig = {
  average: { label: "Performance moyenne", color: "#ef4444" },
} satisfies ChartConfig;

// Même agrégation que la version professeur (student-profile) : une
// soumission notée peut toucher plusieurs compétences à la fois (plusieurs
// lignes StudentCompetencyObservation partageant le même submission_id/
// created_at) — regroupées ici en UN point par soumission (moyenne des
// compétences touchées), pour une seule courbe d'ensemble représentant
// l'évolution de la note au fil des examens passés. Jamais une courbe par
// compétence — un seul accent de couleur, cf. CompetencyRadarChart.
function aggregateBySubmission(observations: CompetencyObservationRead[], locale: string) {
  const bySubmission = new Map<string, { created_at: string; total: number; count: number }>();
  for (const obs of observations) {
    const entry = bySubmission.get(obs.submission_id) ?? { created_at: obs.created_at, total: 0, count: 0 };
    entry.total += Number(obs.performance_copie);
    entry.count += 1;
    bySubmission.set(obs.submission_id, entry);
  }
  return Array.from(bySubmission.values())
    .sort((a, b) => a.created_at.localeCompare(b.created_at))
    .map((entry) => ({
      date: new Date(entry.created_at).toLocaleDateString(locale, { day: "numeric", month: "short" }),
      average: Math.round((entry.total / entry.count) * 100),
    }));
}

export function CompetencyEvolutionChart({ observations }: { observations: CompetencyObservationRead[] }) {
  const t = useTranslations("MyProgress");
  const locale = useLocale();
  const data = aggregateBySubmission(observations, locale);
  console.log("CompetencyEvolutionChart data:", data.length, data, observations.length);

  if (data.length < 2) {
    const submissionsCount = data.length; // 0 ou 1
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed py-12 text-center">
        <div className="flex size-10 items-center justify-center rounded-full bg-muted">
          <TrendingUp className="size-5 text-muted-foreground" />
        </div>
        <div className="flex flex-col gap-1">
          <p className="text-sm font-medium text-slate-700 dark:text-zinc-300">{t("evolutionNotEnoughData")}</p>
          {submissionsCount === 1 && (
            <p className="text-xs text-muted-foreground">
              {t("evolutionOneMoreNeeded")}
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-64 w-full">
      <LineChart data={data} margin={{ left: 8, right: 8, top: 8, bottom: 0 }}>
        <ChartTooltip content={<ChartTooltipContent />} />
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} />
        <YAxis
          domain={[0, 100]}
          tickLine={false}
          axisLine={false}
          width={32}
          tick={{ fontSize: 12, fill: "var(--muted-foreground)" }}
        />
        <Line
          dataKey="average"
          type="monotone"
          stroke="#ef4444"
          strokeWidth={2.5}
          dot={{ r: 4, fill: "#ef4444", stroke: "#ffffff", strokeWidth: 1.5 }}
          activeDot={{ r: 6, fill: "#ef4444", stroke: "#ffffff", strokeWidth: 2 }}
        />
      </LineChart>
    </ChartContainer>
  );
}
