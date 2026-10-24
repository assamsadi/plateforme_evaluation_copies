"use client";

import { IconChartRadar, IconFileText, IconFiles, IconQuote } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import type { RecommendedExerciseRead } from "@/lib/student-api";

// Reste minimal — la liste des éléments qui alimentent le notebook
// (profil de compétence + feedback), jamais une zone d'upload : le contenu
// source est déjà assemblé côté backend (NotebookLMService._build_source_
// content), rien à gérer ici. Cartes numérotées façon "citations" de
// NotebookLM ([1], [2]) : l'étudiant retrouve d'où viennent les réponses.
export function SourcesPanel({ recommendation }: { recommendation: RecommendedExerciseRead }) {
  const t = useTranslations("NotebookSheet");
  const tProgress = useTranslations("MyProgress");

  const tierKey =
    recommendation.category === "remediation" && recommendation.is_persistent_weakness
      ? "tierToWorkOn"
      : recommendation.category === "verification"
        ? "tierToConfirm"
        : "tierConsolidated";
  const tierClass =
    tierKey === "tierToWorkOn"
      ? "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/40 dark:text-rose-300"
      : tierKey === "tierToConfirm"
        ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300"
        : "border-primary/20 bg-primary/10 text-primary";

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col gap-4 overflow-y-auto border-r border-border/60 bg-gradient-to-b from-primary/[0.06] via-slate-50/60 to-slate-50/30 p-4 md:p-6 dark:from-primary/10 dark:via-zinc-900/40 dark:to-zinc-900/20">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-2 text-xs font-bold tracking-wider text-muted-foreground uppercase">
          <IconFiles className="size-4 text-primary" stroke={1.75} />
          {t("sourcesTitle")}
        </span>
        <span className="rounded-full bg-primary/15 px-2 py-0.5 font-mono text-xs font-bold text-primary tabular-nums">
          2
        </span>
      </div>

      <div className="flex flex-col gap-3">
        <article className="group relative overflow-hidden rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/15 via-primary/5 to-transparent p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:shadow-md hover:shadow-primary/10">
          <div className="pointer-events-none absolute -top-8 -right-8 size-24 rounded-full bg-primary/15 blur-2xl" />
          <div className="relative flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm shadow-primary/30">
              <IconChartRadar className="size-5" stroke={1.75} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs font-bold tracking-wide text-primary uppercase">{t("sourceCompetencyProfile")}</p>
                <span className="font-mono text-[11px] font-bold text-primary/60">[1]</span>
              </div>
              <p className="mt-1 text-sm leading-snug font-semibold text-foreground">
                {tProgress(`competency_${recommendation.competency_code}`)}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Badge variant="outline" className={`text-[11px] font-semibold ${tierClass}`}>
                  {tProgress(tierKey)}
                </Badge>
                {recommendation.difficulty_level ? (
                  <Badge variant="outline" className="text-[11px] font-medium">
                    {recommendation.difficulty_level}
                  </Badge>
                ) : null}
                <Badge variant="outline" className="text-[11px] font-medium tabular-nums">
                  {Math.round(recommendation.relevance_score * 100)} %
                </Badge>
              </div>
            </div>
          </div>
        </article>

        <article className="group relative overflow-hidden rounded-2xl border border-info/25 bg-gradient-to-br from-info/15 via-info/5 to-transparent p-4 shadow-xs transition-all hover:-translate-y-0.5 hover:shadow-md hover:shadow-info/10">
          <div className="pointer-events-none absolute -bottom-8 -left-8 size-24 rounded-full bg-info/15 blur-2xl" />
          <div className="relative flex items-start gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-info text-info-foreground shadow-sm shadow-info/30">
              <IconFileText className="size-5" stroke={1.75} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-start justify-between gap-2">
                <p className="text-xs font-bold tracking-wide text-info uppercase">{t("sourceFeedbackReport")}</p>
                <span className="font-mono text-[11px] font-bold text-info/60">[2]</span>
              </div>
              <div className="mt-2 flex gap-2 border-l-2 border-info/40 pl-3">
                <IconQuote className="mt-0.5 size-3.5 shrink-0 text-info/60" stroke={2} />
                <p className="text-sm leading-relaxed text-foreground/90 italic">{recommendation.reason}</p>
              </div>
            </div>
          </div>
        </article>
      </div>
    </div>
  );
}
