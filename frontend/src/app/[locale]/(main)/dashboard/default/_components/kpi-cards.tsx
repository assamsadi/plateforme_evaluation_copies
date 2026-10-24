"use client";

import { BookOpen, FileStack, Percent, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import type { PlatformStatistics } from "@/lib/admin-api";

const KPI_ITEMS = [
  { key: "totalUsers", tag: "+Active", icon: Users, value: (stats: PlatformStatistics) => stats.total_users },
  {
    key: "totalExercises",
    tag: "Library",
    icon: BookOpen,
    value: (stats: PlatformStatistics) => stats.total_exercises,
  },
  {
    key: "totalSubmissions",
    tag: "Evaluated",
    icon: FileStack,
    value: (stats: PlatformStatistics) => stats.total_submissions,
  },
  {
    key: "averageScore",
    tag: "Mean",
    icon: Percent,
    value: (stats: PlatformStatistics) => stats.average_score ?? "—",
  },
] as const;

export function KpiCards({ stats }: { stats: PlatformStatistics }) {
  const t = useTranslations("Overview");

  return (
    <div className="grid grid-cols-1 gap-4.5 sm:grid-cols-2 xl:grid-cols-4">
      {KPI_ITEMS.map(({ key, tag, icon: Icon, value }) => (
        <Card key={key} className="relative overflow-hidden shadow-2xs border-slate-200/90 dark:border-zinc-800">
          <div className="absolute inset-x-0 top-0 h-1 bg-primary" />
          <CardHeader className="flex flex-row items-center justify-between px-5 pt-4.5 pb-2">
            <CardDescription className="text-sm font-bold tracking-wider text-slate-700 uppercase dark:text-zinc-300">
              {t(key)}
            </CardDescription>
            <div className="flex size-9 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
              <Icon className="size-4.5" />
            </div>
          </CardHeader>
          <CardContent className="px-5 pb-5">
            <div className="flex items-baseline justify-between">
              <div className="text-3xl font-bold tracking-tight text-slate-900 tabular-nums dark:text-zinc-100">
                {value(stats)}
              </div>
              <span className="inline-flex items-center rounded-md bg-muted px-2.5 py-0.5 text-sm font-bold text-slate-700 dark:text-zinc-300">
                {tag}
              </span>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
