"use client";
import type { ColumnDef } from "@tanstack/react-table";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { ModelConfigurationRead } from "@/lib/admin-api";
import type { DataTableFeatures } from "@/lib/data-table-features";

export function makeModelConfigsColumns(options: {
  t: (key: string) => string;
  onEdit: (config: ModelConfigurationRead) => void;
}): ColumnDef<DataTableFeatures, ModelConfigurationRead>[] {
  const { t } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.task_type} ${row.provider} ${row.model_name}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "task_type",
      header: t("columnTask"),
      cell: ({ row }) => <span className="font-medium text-foreground text-base">{row.original.task_type}</span>,
    },
    {
      accessorKey: "provider",
      header: t("columnProvider"),
      cell: ({ row }) => (
        <Badge variant="outline" className="font-mono">
          {row.original.provider}
        </Badge>
      ),
    },
    {
      accessorKey: "model_name",
      header: t("columnModel"),
      cell: ({ row }) => <span className="font-mono text-base">{row.original.model_name}</span>,
    },
    {
      accessorKey: "timeout_seconds",
      header: t("columnTimeout"),
      cell: ({ row }) => <span className="text-base">{row.original.timeout_seconds}s</span>,
    },
    {
      accessorKey: "is_overridden",
      header: t("columnOverridden"),
      cell: ({ row }) =>
        row.original.is_overridden ? (
          <StatusBadge tone="info" status={t("overridden")} />
        ) : (
          <StatusBadge tone="neutral" status={t("default")} />
        ),
    },
    {
      id: "actions",
      header: () => <div className="text-right">{t("columnActions")}</div>,
      cell: ({ row }) => (
        <div className="text-right">
          <Button
            size="sm"
            variant="skew"
            className="h-8 px-3 text-base font-semibold tracking-wide"
            onClick={() => options.onEdit(row.original)}
          >
            {t("editAction")}
          </Button>
        </div>
      ),
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
