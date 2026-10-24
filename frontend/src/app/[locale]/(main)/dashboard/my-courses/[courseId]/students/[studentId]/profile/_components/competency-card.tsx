import { IconMinus, IconTrendingDown, IconTrendingUp } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

import { StatusBadge } from "@/components/ui/status-badge";
import type { CompetencyProfileLine } from "@/lib/professor-api";

import { MasteryRing } from "./mastery-ring";

function TrendIndicator({ trend }: { trend: CompetencyProfileLine["trend"] }) {
  const t = useTranslations("StudentProfilePage");
  if (trend === "IMPROVING") {
    return (
      <StatusBadge
        tone="success"
        status={
          <>
            <IconTrendingUp className="size-3.5" stroke={2} />
            {t("trend_IMPROVING")}
          </>
        }
        className="text-xs"
      />
    );
  }
  if (trend === "DECLINING") {
    return (
      <StatusBadge
        tone="danger"
        status={
          <>
            <IconTrendingDown className="size-3.5" stroke={2} />
            {t("trend_DECLINING")}
          </>
        }
        className="text-xs"
      />
    );
  }
  if (trend === "STABLE") {
    return (
      <StatusBadge
        tone="neutral"
        status={
          <>
            <IconMinus className="size-3.5" stroke={2} />
            {t("trend_STABLE")}
          </>
        }
        className="text-xs"
      />
    );
  }
  return <StatusBadge tone="warning" status={t("trend_INSUFFICIENT_DATA")} className="text-xs" />;
}

export function CompetencyCard({ line }: { line: CompetencyProfileLine }) {
  const t = useTranslations("StudentProfilePage");

  const confidenceLabel =
    line.confidence_level >= 0.7
      ? t("confidenceHigh")
      : line.confidence_level >= 0.4
        ? t("confidenceMedium")
        : t("confidenceLow");

  return (
    <div className="flex flex-col gap-4 rounded-2xl border border-slate-200/90 bg-white p-5 shadow-2xs dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-col gap-2 border-b border-slate-100 pb-3 dark:border-zinc-800">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100">{t(`competency_${line.competency}`)}</h3>
          <TrendIndicator trend={line.trend} />
        </div>
      </div>

      <MasteryRing value={line.mastery_level} />

      <p className="text-xs font-semibold text-slate-600 dark:text-zinc-400">
        {t("evaluationsBasis", { count: line.evaluations_count })} — {confidenceLabel}
      </p>

      {line.weaknesses.length > 0 ? (
        <div className="rounded-xl border border-slate-200/70 bg-slate-50/70 p-3.5 dark:border-zinc-800 dark:bg-zinc-800/40">
          <p className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-zinc-300">{t("attentionPointsLabel")}</p>
          <ul className="mt-2 flex flex-col gap-1.5 pl-4">
            {line.weaknesses.map((weakness, index) => (
              <li key={index} className="list-disc text-sm font-medium leading-relaxed text-slate-800 dark:text-zinc-200 marker:text-amber-500">
                {weakness}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
