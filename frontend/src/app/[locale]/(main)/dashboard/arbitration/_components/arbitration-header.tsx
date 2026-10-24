"use client";

import { useState } from "react";

import { Flag, Scale } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import type { IntegrityAlertRead } from "@/lib/professor-api";

import { FlagStudentDialog } from "./flag-student-dialog";

// Bandeau commun aux 3 sous-pages d'Arbitrage (Corrections/Incidents/
// Appeals, désormais des routes distinctes plutôt que des onglets internes,
// cf. sidebar-items.ts) — le signalement d'étudiant n'est lié à aucune
// sous-vue en particulier, il reste donc disponible partout.
export function ArbitrationHeader() {
  const tFlag = useTranslations("FlagStudentDialog");
  const tAlerts = useTranslations("IntegrityAlerts");
  const [isFlagDialogOpen, setIsFlagDialogOpen] = useState(false);

  function handleFlagged(alert: IntegrityAlertRead) {
    toast.success(tAlerts("flagSuccess", { name: alert.student_full_name }));
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <div className="flex size-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
          <Scale className="size-5" />
        </div>
        <h1 className="text-lg font-bold tracking-tight text-slate-900 dark:text-zinc-100">
          Arbitrage & Gestion des Incidents
        </h1>
      </div>
      <Button size="sm" variant="skew" className="h-10 px-4 text-sm font-semibold tracking-wide" onClick={() => setIsFlagDialogOpen(true)}>
        <Flag className="size-3.5" /> {tFlag("title")}
      </Button>

      <FlagStudentDialog open={isFlagDialogOpen} onOpenChange={setIsFlagDialogOpen} onFlagged={handleFlagged} />
    </div>
  );
}
