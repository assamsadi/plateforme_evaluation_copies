import type { LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"

// Composant réutilisable — créé pour la refonte de la page Exercice
// (C2PCTAssess, 2026-09-11), remplace le texte gris plat répété dans
// QuestionsList / CorrectionBlocksPanel / SubmissionsPanel.
function EmptyState({
  icon: Icon,
  title,
  description,
  className,
}: {
  icon: LucideIcon
  title: React.ReactNode
  description?: React.ReactNode
  className?: string
}) {
  return (
    <div
      data-slot="empty-state"
      className={cn(
        "flex flex-col items-center gap-3 rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-6 py-10 text-center dark:border-zinc-800 dark:bg-zinc-800/30",
        className,
      )}
    >
      <div className="flex size-12 items-center justify-center rounded-full border border-primary/20 bg-primary/10 text-primary">
        <Icon className="size-5.5" />
      </div>
      <div className="flex flex-col gap-1">
        <p className="text-sm font-bold text-slate-900 dark:text-zinc-100">{title}</p>
        {description ? (
          <p className="max-w-sm text-sm font-medium text-slate-500 dark:text-zinc-400">{description}</p>
        ) : null}
      </div>
    </div>
  )
}

export { EmptyState }
