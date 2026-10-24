import { IconAlertTriangle, IconCircleCheck, IconMinus, IconTarget, IconTrendingDown, IconTrendingUp } from "@tabler/icons-react";
import { useLocale, useTranslations } from "next-intl";

import { formatC2PCTItem } from "@/lib/c2pct-i18n";
import type { CompetencyProfileLine } from "@/lib/student-api";

import styles from "./competency-detail-card.module.css";
import { MasteryRing } from "./mastery-ring";

// Fond de carte selon le score réel — jamais un fond vert fixe quel que
// soit le niveau (bug relevé après relecture) : danger pâle <40%, ambre
// pâle 40-70%, vert pâle >70%, mêmes seuils que MasteryRing/StatusBadge
// ailleurs dans l'app.
function getCardTone(masteryLevel: number): { cardClassName: string; dividerClassName: string } {
  if (masteryLevel < 40) {
    return {
      cardClassName: "border-rose-200/90 bg-rose-50 dark:border-rose-900/50 dark:bg-rose-950/30",
      dividerClassName: "border-rose-200/80 dark:border-rose-800/50",
    };
  }
  if (masteryLevel < 70) {
    return {
      cardClassName: "border-amber-200/90 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-950/30",
      dividerClassName: "border-amber-200/80 dark:border-amber-800/50",
    };
  }
  return {
    cardClassName: "border-emerald-200/90 bg-emerald-50 dark:border-emerald-900/50 dark:bg-emerald-950/40",
    dividerClassName: "border-emerald-200/80 dark:border-emerald-800/50",
  };
}

function TrendBadge({ trend }: { trend: CompetencyProfileLine["trend"] }) {
  const t = useTranslations("MyProgress");

  if (trend === "IMPROVING") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-100/90 px-2.5 py-1 text-xs font-semibold text-emerald-800 ring-1 ring-emerald-300/80 dark:bg-emerald-950/60 dark:text-emerald-300 dark:ring-emerald-700/60">
        <IconTrendingUp className="size-3.5" stroke={2.5} />
        {t("trend_IMPROVING")}
      </span>
    );
  }
  if (trend === "DECLINING") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-rose-100/90 px-2.5 py-1 text-xs font-semibold text-rose-800 ring-1 ring-rose-300/80 dark:bg-rose-950/60 dark:text-rose-300 dark:ring-rose-700/60">
        <IconTrendingDown className="size-3.5" stroke={2.5} />
        {t("trend_DECLINING")}
      </span>
    );
  }
  if (trend === "STABLE") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-200/90 px-2.5 py-1 text-xs font-semibold text-slate-700 ring-1 ring-slate-300 dark:bg-zinc-800 dark:text-zinc-300 dark:ring-zinc-700">
        <IconMinus className="size-3.5" stroke={2.5} />
        {t("trend_STABLE")}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100/90 px-2.5 py-1 text-xs font-semibold text-amber-800 ring-1 ring-amber-300/80 dark:bg-amber-950/60 dark:text-amber-300 dark:ring-amber-700/60">
      {t("trend_INSUFFICIENT_DATA")}
    </span>
  );
}

// 25 cellules de survol (5×5) — tilt 3D sur hover
const TRACKER_COUNT = 25;
function Trackers() {
  return (
    <>
      {Array.from({ length: TRACKER_COUNT }, (_, index) => (
        <div key={index} className={`${styles.tracker} ${styles[`tr${index + 1}`]}`} />
      ))}
    </>
  );
}

export function CompetencyDetailCard({ line }: { line: CompetencyProfileLine }) {
  const t = useTranslations("MyProgress");
  const locale = useLocale();

  const hasStrengths = line.strengths.length > 0;
  const hasWeaknesses = line.weaknesses.length > 0;
  const { cardClassName, dividerClassName } = getCardTone(Number(line.mastery_level));

  return (
    <div className={`${styles.container} h-full ${styles.noselect}`}>
      <div className={`${styles.card} h-full border shadow-sm ${cardClassName}`}>
        <div className={`${styles.cardContent} h-full`}>
          <div className={styles.cardGlare} />
          <div className={styles.cyberLines}>
            <span></span>
            <span></span>
            <span></span>
            <span></span>
          </div>
          <div className={styles.glowingElements}>
            <div className={styles.glow1} />
            <div className={styles.glow2} />
            <div className={styles.glow3} />
          </div>
          <div className={styles.cardParticles}>
            <span></span>
            <span></span>
            <span></span>
            <span></span>
            <span></span>
            <span></span>
          </div>
          <div className={styles.scanLine} />
          <div className={styles.cardGlow} />

          {/* Contenu principal avec typographie lisible et contrastée */}
          <div className="relative z-10 flex h-full flex-col gap-0 p-6">

            {/* En-tête : nom de compétence + tendance + compteur — titre plus affirmé (hiérarchie), plus d'air avant le badge */}
            <div className={`flex flex-col gap-3 pb-4 border-b ${dividerClassName}`}>
              <h3 className="text-xl font-extrabold leading-snug text-slate-900 dark:text-zinc-100">
                {t(`competency_${line.competency}`)}
              </h3>
              <div className="flex items-center justify-between gap-2">
                <TrendBadge trend={line.trend} />
                <span className="text-xs font-semibold text-slate-600 dark:text-zinc-400">
                  {t("evaluationsCount", { count: line.evaluations_count })}
                </span>
              </div>
            </div>

            {/* Score de maîtrise */}
            <div className={`py-4 border-b ${dividerClassName}`}>
              <MasteryRing value={Number(line.mastery_level)} />
            </div>

            {/* Corps : points forts / à améliorer / alertes */}
            <div className="flex flex-col gap-4 pt-4">
              {hasStrengths && (
                <div className="flex flex-col gap-2">
                  <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-emerald-800 dark:text-emerald-400">
                    <IconCircleCheck className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400" stroke={2.5} />
                    {t("strengthsLabel")}
                  </span>
                  <ul className="flex flex-col gap-2 pl-5">
                    {line.strengths.map((strength, index) => (
                      <li
                        key={index}
                        className="list-disc text-sm font-semibold leading-normal text-slate-800 dark:text-zinc-200 marker:text-emerald-600 dark:marker:text-emerald-400"
                      >
                        {formatC2PCTItem(strength, locale)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {hasWeaknesses && (
                <div className="flex flex-col gap-2">
                  <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-amber-800 dark:text-amber-400">
                    <IconTarget className="size-4 shrink-0 text-amber-600 dark:text-amber-400" stroke={2.5} />
                    {t("weaknessesLabel")}
                  </span>
                  {/* Une seule phrase d'intro commune — jamais répétée à chaque puce */}
                  <p className="text-xs font-medium text-slate-500 dark:text-zinc-400">{t("weaknessesIntro")}</p>
                  <ul className="flex flex-col gap-2 pl-5">
                    {line.weaknesses.map((weakness, index) => (
                      <li
                        key={index}
                        className="list-disc text-sm font-semibold leading-normal text-slate-800 dark:text-zinc-200 marker:text-amber-600 dark:marker:text-amber-400"
                      >
                        {formatC2PCTItem(weakness, locale)}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {line.is_persistent_weakness && (
                <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50/90 p-3 dark:border-rose-900/50 dark:bg-rose-950/40">
                  <IconAlertTriangle className="mt-0.5 size-4 shrink-0 text-rose-600 dark:text-rose-400" stroke={2.5} />
                  <p className="text-xs font-semibold leading-relaxed text-rose-800 dark:text-rose-300">
                    {t("persistentWeaknessWarning")}
                  </p>
                </div>
              )}

              {!hasStrengths && !hasWeaknesses && (
                <p className="text-sm font-medium leading-relaxed text-slate-600 dark:text-zinc-400">
                  {t("confidenceEncouragement", { count: line.evaluations_count })}
                </p>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className={styles.canvas}>
        <Trackers />
      </div>
    </div>
  );
}
