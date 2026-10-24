"use client";
import type { ColumnDef } from "@tanstack/react-table";
import { Check, X } from "lucide-react";

import { StatusBadge } from "@/components/ui/status-badge";
import type { AuditLogRead } from "@/lib/admin-api";
import type { DataTableFeatures } from "@/lib/data-table-features";
import { cn } from "@/lib/utils";

import { severityTone } from "./data";

function SeverityBadge({ severity, t }: { severity: AuditLogRead["severity"]; t: (key: string) => string }) {
  return (
    <StatusBadge
      tone={severityTone[severity]}
      status={t(`severity${severity.charAt(0).toUpperCase()}${severity.slice(1)}`)}
    />
  );
}

export function makeAuditLogsColumns(options: {
  t: (key: string) => string;
  locale: string;
}): ColumnDef<DataTableFeatures, AuditLogRead>[] {
  const { t, locale } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.user_full_name} ${row.action} ${row.entity_type} ${row.entity_label ?? ""}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "user_id",
      header: t("columnUserId"),
      cell: ({ row }) => (
        <span className="select-all font-mono text-sm text-muted-foreground">{row.original.user_id}</span>
      ),
    },
    {
      accessorKey: "created_at",
      header: t("columnDate"),
      cell: ({ row }) => (
        <span
          className={cn(
            "whitespace-nowrap text-base font-semibold",
            row.original.success ? "text-success" : "text-destructive",
          )}
        >
          {new Date(row.original.created_at).toLocaleString(locale)}
        </span>
      ),
    },
    {
      accessorKey: "user_full_name",
      header: t("columnUser"),
      cell: ({ row }) => <span className="font-medium text-foreground text-base">{row.original.user_full_name}</span>,
    },
    {
      accessorKey: "action",
      header: t("columnAction"),
      cell: ({ row }) => <span className="font-mono text-base font-semibold">{row.original.action}</span>,
    },
    {
      id: "severity",
      accessorKey: "severity",
      header: t("columnSeverity"),
      filterFn: "equalsString",
      cell: ({ row }) => <SeverityBadge severity={row.original.severity} t={t} />,
    },
    {
      accessorKey: "success",
      header: t("columnSuccess"),
      cell: ({ row }) =>
        row.original.success ? (
          <Check className="size-4 text-success" aria-label={t("success")} />
        ) : (
          <X className="size-4 text-destructive" aria-label={t("failure")} />
        ),
    },
  ];
}
