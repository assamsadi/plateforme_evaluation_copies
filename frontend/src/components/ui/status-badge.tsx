import * as React from "react"

import { cn } from "@/lib/utils"

export type StatusTone = "info" | "success" | "warning" | "danger" | "neutral"

const toneClasses: Record<StatusTone, string> = {
  info: "border-info/30 bg-info/15 text-info font-semibold",
  success: "border-success/30 bg-success/15 text-success font-semibold",
  warning: "border-warning/30 bg-warning/15 text-warning font-semibold",
  danger: "border-danger/30 bg-danger/15 text-danger font-semibold",
  neutral: "border-slate-300 bg-slate-100 text-slate-700 font-semibold dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
}

function StatusBadge({
  status,
  tone,
  className,
  ...props
}: React.ComponentProps<"span"> & {
  status: React.ReactNode
  tone: StatusTone
}) {
  return (
    <span
      data-slot="status-badge"
      className={cn(
        "inline-flex h-7.5 w-fit shrink-0 items-center justify-center gap-1.5 rounded-full border px-3 py-1 text-sm leading-none font-semibold whitespace-nowrap shadow-2xs",
        toneClasses[tone],
        className,
      )}
      {...props}
    >
      {status}
    </span>
  )
}

export { StatusBadge }
