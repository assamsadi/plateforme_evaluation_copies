"use client"

import * as React from "react"
import { cn } from "@/lib/utils"

// Icône loupe — tracé exact du snippet Uiverse.io by Smit-Prajapati
function SearchGlyph(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor" {...props}>
      <path d="M21.53 20.47l-3.66-3.66C19.195 15.24 20 13.214 20 11c0-4.97-4.03-9-9-9s-9 4.03-9 9 4.03 9 9 9c2.215 0 4.24-.804 5.808-2.13l3.66 3.66c.147.146.34.22.53.22s.385-.073.53-.22c.295-.293.295-.767.002-1.06zM3.5 11c0-4.135 3.365-7.5 7.5-7.5s7.5 3.365 7.5 7.5-3.365 7.5-7.5 7.5-7.5-3.365-7.5-7.5z" />
    </svg>
  )
}

/**
 * Barre de recherche stylisée — Adaptée du design Uiverse.io (by Smit-Prajapati)
 * Intègre le container pill à double gradient, le champ fluide et l'icône à droite
 * avec séparateur visuel, tout en s'adaptant parfaitement aux modes clair et sombre.
 */
const SearchInput = React.forwardRef<
  HTMLInputElement,
  React.ComponentProps<"input"> & { inputClassName?: string }
>(({ className, inputClassName, disabled, ...props }, ref) => {
  return (
    <div
      className={cn(
        "group relative flex h-10 w-full md:w-80 lg:w-96 items-center rounded-full p-[2.5px]",
        "bg-gradient-to-br from-emerald-200/90 via-teal-100/70 to-emerald-300/80 shadow-xs transition-all duration-300",
        "hover:from-emerald-300 hover:to-teal-300 hover:shadow-sm",
        "focus-within:from-emerald-400 focus-within:to-teal-400 focus-within:ring-2 focus-within:ring-primary/30 focus-within:shadow-md",
        "dark:from-emerald-950/80 dark:via-zinc-800 dark:to-emerald-900/60 dark:hover:from-emerald-900 dark:dark:hover:to-teal-900",
        "dark:focus-within:from-emerald-700 dark:focus-within:to-teal-800 dark:focus-within:ring-primary/40",
        disabled && "opacity-50 pointer-events-none",
        className
      )}
    >
      <div className="relative flex w-full items-center rounded-full bg-gradient-to-br from-slate-50 via-white to-slate-100/90 px-4 py-2 transition-all dark:from-zinc-900 dark:via-zinc-900 dark:to-zinc-950">
        <input
          ref={ref}
          type="text"
          disabled={disabled}
          className={cn(
            "w-full min-w-0 appearance-none border-0 bg-transparent text-sm font-medium text-slate-800 placeholder:text-slate-400/90 outline-none focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0 dark:text-zinc-100 dark:placeholder:text-zinc-500",
            inputClassName
          )}
          {...props}
        />
        <div className="flex shrink-0 items-center border-l border-emerald-200/80 pl-3 ml-2 transition-colors group-focus-within:border-primary/60 dark:border-zinc-700 dark:group-focus-within:border-primary/50">
          <SearchGlyph className="size-4.5 text-emerald-600 transition-transform duration-200 group-hover:scale-110 group-focus-within:text-primary dark:text-emerald-400" />
        </div>
      </div>
    </div>
  )
})

SearchInput.displayName = "SearchInput"

export { SearchInput }
