import { useTranslations } from "next-intl";

import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import type { RecommendedExerciseRead } from "@/lib/professor-api";

// 3e palier ("faiblesse persistante") — jamais un champ natif de
// RecommendedExercise (seulement 2 catégories : remediation/verification),
// dérivé ici de la jointure is_persistent_weakness déjà faite côté backend
// (EvaluationService... non, RecommendationService._to_recommendation_read).
function resolveTier(rec: RecommendedExerciseRead): { labelKey: string; tone: StatusTone } {
  if (rec.category === "remediation" && rec.is_persistent_weakness) {
    return { labelKey: "tierPersistentWeakness", tone: "danger" };
  }
  if (rec.category === "verification") {
    return { labelKey: "tierToConfirm", tone: "warning" };
  }
  return { labelKey: "tierStandard", tone: "info" };
}

export function RecommendationCard({ recommendation }: { recommendation: RecommendedExerciseRead }) {
  const t = useTranslations("StudentProfilePage");
  const tier = resolveTier(recommendation);

  return (
    <div className="flex flex-col gap-3 rounded-xl border-[0.5px] border-border bg-card p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-base font-medium text-foreground">{recommendation.exercise_title}</h3>
        <StatusBadge tone={tier.tone} status={t(tier.labelKey)} />
      </div>
      <p className="text-sm text-muted-foreground">{recommendation.reason}</p>
      {recommendation.status === "superseded" ? (
        <span className="text-sm text-muted-foreground">{t("statusSuperseded")}</span>
      ) : null}
    </div>
  );
}
