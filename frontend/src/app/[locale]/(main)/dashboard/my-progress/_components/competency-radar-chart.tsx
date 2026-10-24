"use client";

import { useTranslations } from "next-intl";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
} from "recharts";

import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import type { CompetencyProfileLine } from "@/lib/student-api";

const chartConfig = {
  mastery: { label: "Maîtrise", color: "var(--primary)" },
} satisfies ChartConfig;

// Une seule couleur d'accent (primary) — jamais une teinte par compétence,
// même discipline que la page profil professeur.
export function CompetencyRadarChart({ lines }: { lines: CompetencyProfileLine[] }) {
  const t = useTranslations("MyProgress");

  const data = lines.map((line) => ({
    competency: t(`competencyShort_${line.competency}`),
    mastery: Math.round(line.mastery_level),
  }));

  return (
    <ChartContainer config={chartConfig} className="mx-auto aspect-square max-h-80 w-full">
      <RadarChart data={data}>
        <ChartTooltip content={<ChartTooltipContent />} />
        <PolarGrid stroke="var(--border)" />
        <PolarAngleAxis dataKey="competency" tick={{ fontSize: 12, fill: "var(--muted-foreground)" }} />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Radar
          dataKey="mastery"
          stroke="var(--primary)"
          fill="var(--primary)"
          fillOpacity={0.18}
          strokeWidth={2}
          dot={{ r: 3, fill: "var(--primary)", strokeWidth: 0 }}
        />
      </RadarChart>
    </ChartContainer>
  );
}
