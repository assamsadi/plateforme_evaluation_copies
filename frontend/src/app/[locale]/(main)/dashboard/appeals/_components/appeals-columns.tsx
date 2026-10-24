"use client";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { DataTableFeatures } from "@/lib/data-table-features";
import type { GradeAppealRead } from "@/lib/professor-api";

import { statusTone } from "./data";

// Aperçu tronqué dans la liste — le détail complet reste consultable via
// "Resolve" (ResolveAppealDialog affiche déjà appeal.reason en entier),
// jamais perdu, juste pas répété deux fois en pleine longueur.
function truncateWords(text: string, wordCount: number): string {
  const words = text.trim().split(/\s+/);
  if (words.length <= wordCount) return text;
  return `${words.slice(0, wordCount).join(" ")}...`;
}

export function makeAppealsColumns(options: {
  t: (key: string) => string;
  onResolve: (appeal: GradeAppealRead) => void;
  locale: string;
}): ColumnDef<DataTableFeatures, GradeAppealRead>[] {
  const { t } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.student_full_name} ${row.reason}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "student_full_name",
      header: t("columnStudent"),
      cell: ({ row }) => (
        <span className="font-semibold text-slate-900 text-base dark:text-zinc-100">
          {row.original.student_full_name}
        </span>
      ),
    },
    {
      accessorKey: "reason",
      header: t("columnReason"),
      cell: ({ row }) => (
        <span className="max-w-sm text-base font-medium text-slate-700 dark:text-zinc-300">
          {truncateWords(row.original.reason, 3)}
        </span>
      ),
    },
    {
      accessorKey: "original_score",
      header: t("columnOriginalScore"),
      cell: ({ row }) => (
        <span className="font-mono text-base font-bold text-slate-900 dark:text-zinc-100">
          {row.original.original_score}
        </span>
      ),
    },
    {
      accessorKey: "status",
      header: t("columnStatus"),
      cell: ({ row }) => (
        <StatusBadge
          tone={statusTone[row.original.status]}
          status={t(`status_${row.original.status}`)}
          className="text-sm"
        />
      ),
    },
    {
      id: "actions",
      header: () => (
        <div className="text-right text-sm font-bold text-slate-700 uppercase tracking-wider dark:text-zinc-300">
          {t("columnActions")}
        </div>
      ),
      cell: ({ row }) => (
        <div className="text-right">
          <Button
            size="sm"
            variant="skew"
            className="h-8 px-3 text-base font-semibold tracking-wide"
            onClick={() => options.onResolve(row.original)}
          >
            {t("resolveAction")}
          </Button>
        </div>
      ),
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
