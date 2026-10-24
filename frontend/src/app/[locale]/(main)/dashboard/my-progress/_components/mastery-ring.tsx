// Indicateur de maîtrise — barre de progression simple (une seule couleur,
// celle du palier) + score numérique. Remplace l'ancienne barre à 5
// segments dont le fond "vide" restait teinté émeraude quel que soit le
// palier réel (lu à tort comme un dégradé multicolore, cf. demande) par un
// remplissage continu sur un rail neutre.

import { useTranslations } from "next-intl";

function getMasteryKey(value: number): { color: string; bgFill: string; key: string } {
  if (value >= 80) return { color: "text-emerald-700 dark:text-emerald-400", bgFill: "bg-emerald-500", key: "mastery_excellent" };
  if (value >= 60) return { color: "text-sky-700 dark:text-sky-400", bgFill: "bg-sky-500", key: "mastery_mastered" };
  if (value >= 40) return { color: "text-amber-700 dark:text-amber-400", bgFill: "bg-amber-500", key: "mastery_in_progress" };
  if (value >= 20) return { color: "text-orange-700 dark:text-orange-400", bgFill: "bg-orange-500", key: "mastery_insufficient" };
  return { color: "text-rose-700 dark:text-rose-400", bgFill: "bg-rose-500", key: "mastery_very_low" };
}

export function MasteryRing({ value }: { value: number; size?: number }) {
  const t = useTranslations("MyProgress");
  const clamped = Math.max(0, Math.min(100, value));
  const { color, bgFill, key } = getMasteryKey(clamped);

  return (
    <div className="flex w-full flex-col gap-2.5">
      {/* Score numérique + label de niveau */}
      <div className="flex items-baseline justify-between">
        <span className={`font-mono text-3xl font-bold tracking-tight leading-none ${color}`}>
          {Math.round(clamped)}
          <span className="ml-0.5 text-base font-semibold opacity-75">%</span>
        </span>
        <span className={`text-xs font-bold uppercase tracking-wider ${color}`}>{t(key)}</span>
      </div>

      {/* Barre simple : un seul remplissage, une seule couleur, jamais un dégradé */}
      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-200/70 dark:bg-zinc-700/70">
        <div
          className={`h-full rounded-full transition-all duration-500 ${bgFill}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

