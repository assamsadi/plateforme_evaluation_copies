"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const STATUS_COLORS: Record<string, { bar: string; badge: string; dot: string }> = {
  submitted: {
    bar: "bg-emerald-500",
    badge:
      "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-900/40",
    dot: "bg-emerald-500",
  },
  evaluating: {
    bar: "bg-blue-500",
    badge: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-900/40",
    dot: "bg-blue-500",
  },
  evaluated: {
    bar: "bg-emerald-600",
    badge:
      "bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950/60 dark:text-emerald-200 dark:border-emerald-800",
    dot: "bg-emerald-600",
  },
  failed: {
    bar: "bg-rose-500",
    badge: "bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900/40",
    dot: "bg-rose-500",
  },
  draft: {
    bar: "bg-slate-400",
    badge: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700",
    dot: "bg-slate-400",
  },
};

function getStatusColor(key: string, idx: number) {
  const normalizedKey = key.toLowerCase();
  for (const [k, v] of Object.entries(STATUS_COLORS)) {
    if (normalizedKey.includes(k)) return v;
  }
  const defaultBarColors = ["bg-emerald-500", "bg-blue-500", "bg-amber-500", "bg-indigo-500", "bg-slate-400"];
  const bar = defaultBarColors[idx % defaultBarColors.length];
  return {
    bar,
    badge: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-zinc-800 dark:text-zinc-300 dark:border-zinc-700",
    dot: bar,
  };
}

export function BreakdownCard({
  title,
  entries,
}: {
  title: string;
  entries: { label: string; value: number; key?: string }[];
}) {
  const total = entries.reduce((sum, entry) => sum + entry.value, 0);

  return (
    <Card className="border-slate-200/90 shadow-2xs dark:border-zinc-800">
      <CardHeader className="flex flex-row items-center justify-between border-b border-slate-100 pb-3.5 dark:border-zinc-800">
        <CardTitle className="text-xl font-bold italic leading-none text-slate-900 dark:text-zinc-100">
          {title}
        </CardTitle>
        <span className="rounded-full border border-slate-200 px-2.5 py-0.5 text-sm font-bold italic text-black dark:border-zinc-700 dark:text-zinc-200">
          Total: {total}
        </span>
      </CardHeader>

      <CardContent className="space-y-4 pt-5 pb-5">
        {/* Multi-segment stacked overview bar */}
        {total > 0 && (
          <div className="flex h-3 w-full overflow-hidden rounded-full bg-slate-100 p-0.5 dark:bg-zinc-800">
            {entries.map((entry, idx) => {
              if (entry.value === 0) return null;
              const percent = (entry.value / total) * 100;
              const colors = getStatusColor(entry.key ?? entry.label, idx);
              return (
                <div
                  key={entry.label}
                  className={`h-full first:rounded-l-full last:rounded-r-full transition-all duration-500 ${colors.bar}`}
                  style={{ width: `${percent}%` }}
                  title={`${entry.label}: ${entry.value} (${Math.round(percent)}%)`}
                />
              );
            })}
          </div>
        )}

        {/* Detailed breakdown list */}
        <div className="space-y-2 pt-1">
          {entries.map((entry, idx) => {
            const percent = total > 0 ? Math.round((entry.value / total) * 100) : 0;
            const colors = getStatusColor(entry.key ?? entry.label, idx);

            return (
              <div
                key={entry.label}
                className="group rounded-xl border border-transparent p-2.5 transition-all hover:border-slate-200/80 hover:bg-slate-50/70 dark:hover:border-zinc-800 dark:hover:bg-zinc-800/40"
              >
                <div className="flex items-center justify-between text-base">
                  <div className="flex items-center gap-2">
                    <span className={`size-2.5 rounded-full ${colors.dot}`} />
                    <span className="font-semibold text-slate-800 dark:text-zinc-200">{entry.label}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-slate-900 tabular-nums dark:text-zinc-100">{entry.value}</span>
                    <span className={`rounded-full border px-2 py-0.5 text-sm font-bold tabular-nums ${colors.badge}`}>
                      {percent}%
                    </span>
                  </div>
                </div>

                <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-zinc-800">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${colors.bar}`}
                    style={{ width: `${percent}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
