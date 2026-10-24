"use client";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import type { DataTableFeatures } from "@/lib/data-table-features";
import type { CourseRead } from "@/lib/professor-api";

export function makeMyCoursesColumns(options: {
  t: (key: string) => string;
  onEdit: (course: CourseRead) => void;
  onDelete: (course: CourseRead) => void;
  onViewStudents: (course: CourseRead) => void;
}): ColumnDef<DataTableFeatures, CourseRead>[] {
  const { t } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.module_name} ${row.group_label} ${row.semester}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "module_name",
      header: t("columnModule"),
      cell: ({ row }) => (
        <span className="font-semibold text-slate-900 text-base dark:text-zinc-100">{row.original.module_name}</span>
      ),
    },
    {
      accessorKey: "group_label",
      header: t("columnGroup"),
      cell: ({ row }) => (
        <span className="inline-flex items-center rounded-full bg-emerald-100/80 px-2.5 py-0.5 text-sm font-semibold text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300">
          {row.original.group_label}
        </span>
      ),
    },
    {
      accessorKey: "semester",
      header: t("columnSemester"),
      cell: ({ row }) => (
        <span className="font-mono text-sm font-semibold text-slate-600 dark:text-zinc-300">
          {row.original.semester}
        </span>
      ),
    },
    {
      id: "actions",
      header: () => (
        <div className="text-center text-sm font-bold text-slate-700 uppercase tracking-wider dark:text-zinc-300">
          {t("columnActions")}
        </div>
      ),
      cell: ({ row }) => (
        <div className="flex justify-center gap-2">
          <Button
            size="sm"
            variant="skew"
            className="h-8 px-3 text-base font-semibold tracking-wide"
            onClick={() => options.onViewStudents(row.original)}
          >
            {t("studentsAction")}
          </Button>
          <Button
            size="sm"
            variant="skew"
            className="h-8 px-3 text-base font-semibold tracking-wide"
            onClick={() => options.onEdit(row.original)}
          >
            {t("editAction")}
          </Button>
          <Button
            size="sm"
            variant="skew-destructive"
            className="h-8 px-3 text-base font-semibold tracking-wide"
            onClick={() => options.onDelete(row.original)}
          >
            {t("deleteAction")}
          </Button>
        </div>
      ),
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
