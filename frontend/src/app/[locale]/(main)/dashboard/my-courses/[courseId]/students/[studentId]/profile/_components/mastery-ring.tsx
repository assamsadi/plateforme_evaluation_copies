"use client";

import { useTranslations } from "next-intl";

function getMasteryConfig(value: number): {
  color: string;
  bgSegment: string;
  labelKey: string;
  segments: number;
} {
  if (value >= 80)
    return { color: "text-emerald-700 dark:text-emerald-400", bgSegment: "bg-emerald-500", labelKey: "mastery_excellent", segments: 5 };
  if (value >= 60)
    return { color: "text-sky-700 dark:text-sky-400", bgSegment: "bg-sky-500", labelKey: "mastery_mastered", segments: 4 };
  if (value >= 40)
    return { color: "text-amber-700 dark:text-amber-400", bgSegment: "bg-amber-500", labelKey: "mastery_in_progress", segments: 3 };
  if (value >= 20)
    return { color: "text-orange-700 dark:text-orange-400", bgSegment: "bg-orange-500", labelKey: "mastery_insufficient", segments: 2 };
  return { color: "text-rose-700 dark:text-rose-400", bgSegment: "bg-rose-500", labelKey: "mastery_very_low", segments: 1 };
}

export function MasteryRing({ value }: { value: number; size?: number }) {
  const t = useTranslations("StudentProfilePage");
  const clamped = Math.max(0, Math.min(100, value));
  const { color, bgSegment, labelKey, segments } = getMasteryConfig(clamped);

  return (
    <div className="flex w-full flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <span className={`font-mono text-2xl font-bold tracking-tight leading-none ${color}`}>
          {Math.round(clamped)}
          <span className="ml-0.5 text-sm font-semibold opacity-75">%</span>
        </span>
        <span className={`text-xs font-bold uppercase tracking-wider ${color}`}>{t(labelKey)}</span>
      </div>

      <div className="flex items-center gap-1">
        {Array.from({ length: 5 }, (_, i) => (
          <div
            key={i}
            className={`h-2 flex-1 rounded-full transition-all duration-500 ${
              i < segments ? bgSegment : "bg-slate-200 dark:bg-zinc-700"
            }`}
            style={{ transitionDelay: `${i * 60}ms` }}
          />
        ))}
      </div>
    </div>
  );
}
