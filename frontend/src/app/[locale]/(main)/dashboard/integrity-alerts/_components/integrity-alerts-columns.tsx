"use client";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { IntegrityAlertRead } from "@/lib/admin-api";
import type { DataTableFeatures } from "@/lib/data-table-features";

import { statusTone } from "./data";

export function makeIntegrityAlertsColumns(options: {
  t: (key: string) => string;
  onResolve: (alert: IntegrityAlertRead) => void;
  locale: string;
}): ColumnDef<DataTableFeatures, IntegrityAlertRead>[] {
  const { t, locale } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.student_full_name} ${row.reason} ${row.trigger_type}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "student_id",
      header: t("columnStudentId"),
      cell: ({ row }) => (
        <span className="select-all font-mono text-sm text-muted-foreground">{row.original.student_id}</span>
      ),
    },
    {
      accessorKey: "created_at",
      header: t("columnDate"),
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-sm font-semibold text-success">
          {new Date(row.original.created_at).toLocaleString(locale)}
        </span>
      ),
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
      accessorKey: "trigger_type",
      header: t("columnTrigger"),
      cell: ({ row }) => (
        <span className="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-sm font-semibold text-slate-700 dark:bg-zinc-800 dark:text-zinc-300">
          {row.original.trigger_type}
        </span>
      ),
    },
    {
      accessorKey: "reason",
      header: t("columnReason"),
      cell: ({ row }) => (
        <span className="line-clamp-2 max-w-sm text-base font-medium text-slate-700 dark:text-zinc-300">
          {row.original.reason}
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
