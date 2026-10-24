"use client";

import { ClipboardCheck, FileStack, Gauge } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { StudentStats } from "@/lib/student-api";

function StatTile({
  icon: Icon,
  label,
  value,
  accentClassName,
}: {
  icon: typeof FileStack;
  label: string;
  value: string;
  accentClassName: string;
}) {
  return (
    <Card className="relative overflow-hidden shadow-2xs border-slate-200/90 dark:border-zinc-800">
      <div className={`absolute inset-x-0 top-0 h-1 ${accentClassName}`} />
      <CardHeader className="flex flex-row items-center justify-between px-5 pt-4.5 pb-2">
        <CardDescription className="text-xs font-bold tracking-wider text-slate-700 uppercase dark:text-zinc-300">
          {label}
        </CardDescription>
        <div className="flex size-9 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
          <Icon className="size-4.5" />
        </div>
      </CardHeader>
      <CardContent className="px-5 pb-5">
        <div className="text-3xl font-bold tracking-tight text-slate-900 tabular-nums dark:text-zinc-100">{value}</div>
      </CardContent>
    </Card>
  );
}

export function MyStatsStrip({ stats }: { stats: StudentStats | null }) {
  const t = useTranslations("MyStatsStrip");

  if (!stats) return null;

  return (
    <div className="grid grid-cols-1 gap-4.5 sm:grid-cols-3">
      <StatTile
        icon={FileStack}
        label={t("totalSubmissions")}
        value={String(stats.total_submissions)}
        accentClassName="bg-primary"
      />
      <StatTile
        icon={ClipboardCheck}
        label={t("totalEvaluations")}
        value={String(stats.total_evaluations)}
        accentClassName="bg-info"
      />
      <StatTile
        icon={Gauge}
        label={t("averageScore")}
        value={stats.average_score !== null ? String(stats.average_score) : t("noScoreYet")}
        accentClassName="bg-success"
      />
    </div>
  );
}
