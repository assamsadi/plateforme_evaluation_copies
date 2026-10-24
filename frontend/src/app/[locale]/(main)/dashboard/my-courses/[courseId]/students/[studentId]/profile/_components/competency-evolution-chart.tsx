"use client";

import { useLocale, useTranslations } from "next-intl";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { CompetencyObservationRead } from "@/lib/professor-api";


// Une soumission notée peut toucher plusieurs compétences à la fois
// (plusieurs lignes StudentCompetencyObservation partageant le même
// submission_id/created_at) — regroupées ici en UN point par soumission
// (moyenne des compétences touchées), pour une seule courbe d'ensemble.
// Jamais une courbe par compétence : violerait la règle "une seule
// couleur d'accent, jamais une teinte différente par compétence".
function aggregateBySubmission(observations: CompetencyObservationRead[], locale: string) {
  const bySubmission = new Map<string, { created_at: string; total: number; count: number }>();
  for (const obs of observations) {
    const entry = bySubmission.get(obs.submission_id) ?? { created_at: obs.created_at, total: 0, count: 0 };
    entry.total += obs.performance_copie;
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
  const t = useTranslations("StudentProfilePage");
  const locale = useLocale();

  const chartConfig = {
    average: { label: t("chartEvolutionAverage"), color: "var(--primary)" },
  } satisfies ChartConfig;

  const data = aggregateBySubmission(observations, locale);

  if (data.length < 2) {
    return (
      <div className="rounded-xl border-[0.5px] border-border bg-muted/30 py-12 text-center">
        <p className="text-sm text-muted-foreground">{t("evolutionNotEnoughData")}</p>
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
