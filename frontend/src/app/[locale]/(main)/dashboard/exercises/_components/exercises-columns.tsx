"use client";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { DataTableFeatures } from "@/lib/data-table-features";
import type { ExerciseRead } from "@/lib/professor-api";

import { statusTone } from "./data";

export function makeExercisesColumns(options: {
  t: (key: string) => string;
  onView: (exercise: ExerciseRead) => void;
}): ColumnDef<DataTableFeatures, ExerciseRead>[] {
  const { t } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.title} ${row.module_name}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "title",
      header: t("columnTitle"),
      cell: ({ row }) => (
        <span className="font-semibold text-slate-900 text-lg dark:text-zinc-100">{row.original.title}</span>
      ),
    },
    {
      accessorKey: "module_name",
      header: t("columnModule"),
      cell: ({ row }) => (
        <span className="text-base font-medium text-slate-600 dark:text-zinc-400">{row.original.module_name}</span>
      ),
    },
    {
      accessorKey: "questions",
      header: t("columnQuestions"),
      cell: ({ row }) => (
        <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-sm font-semibold text-slate-700 dark:bg-zinc-800 dark:text-zinc-300">
          {row.original.questions.length}
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
            onClick={() => options.onView(row.original)}
          >
            {t("viewAction")}
          </Button>
        </div>
      ),
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
