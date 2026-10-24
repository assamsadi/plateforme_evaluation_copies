import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Enveloppe à double dégradé — même thème que SearchInput (barre de
 * recherche) — pour qu'un filtre Select à côté d'une recherche partage la
 * même esthétique de pilule plutôt qu'un style de bouton générique séparé.
 */
export function FilterPill({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div
      className={cn(
        "group relative flex w-full items-center rounded-full p-[2.5px] sm:w-auto",
        "bg-gradient-to-br from-emerald-200/90 via-teal-100/70 to-emerald-300/80 shadow-xs transition-all duration-300",
        "hover:from-emerald-300 hover:to-teal-300 hover:shadow-sm",
        "focus-within:from-emerald-400 focus-within:to-teal-400 focus-within:ring-2 focus-within:ring-primary/30 focus-within:shadow-md",
        "dark:from-emerald-950/80 dark:via-zinc-800 dark:to-emerald-900/60 dark:hover:from-emerald-900 dark:hover:to-teal-900",
        "dark:focus-within:from-emerald-700 dark:focus-within:to-teal-800 dark:focus-within:ring-primary/40",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Style à poser sur le SelectTrigger enveloppé par <FilterPill>. */
export const filterPillTriggerCn =
  "h-9 w-full rounded-full border-0 bg-gradient-to-br from-slate-50 via-white to-slate-100/90 px-4 text-sm font-medium shadow-none dark:from-zinc-900 dark:via-zinc-900 dark:to-zinc-950";
