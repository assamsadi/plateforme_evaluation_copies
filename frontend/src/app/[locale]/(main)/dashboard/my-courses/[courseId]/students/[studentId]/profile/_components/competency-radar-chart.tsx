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
import type { CompetencyProfileLine } from "@/lib/professor-api";

// Diagramme radar 7 axes — vue d'ensemble immédiate, remplace l'empilement
// de barres de l'ancienne modale. Une seule couleur d'accent (primary),
// jamais une teinte par compétence : la distinction entre axes vient de
// leur position et de leur étiquette, jamais de la couleur.

export function CompetencyRadarChart({ lines }: { lines: CompetencyProfileLine[] }) {
  const t = useTranslations("StudentProfilePage");

  const chartConfig = {
    mastery: { label: t("chartRadarMastery"), color: "var(--primary)" },
  } satisfies ChartConfig;

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
