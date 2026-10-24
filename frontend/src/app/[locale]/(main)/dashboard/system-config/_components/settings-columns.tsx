"use client";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import type { SettingOverrideRead } from "@/lib/admin-api";
import type { DataTableFeatures } from "@/lib/data-table-features";

export function makeSettingsColumns(options: {
  t: (key: string) => string;
  onEdit: (setting: SettingOverrideRead) => void;
}): ColumnDef<DataTableFeatures, SettingOverrideRead>[] {
  const { t } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => row.key,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "key",
      header: t("columnKey"),
      cell: ({ row }) => <span className="font-mono text-base">{row.original.key}</span>,
    },
    {
      accessorKey: "default_value",
      header: t("columnDefault"),
      cell: ({ row }) => <span className="text-muted-foreground text-base">{row.original.default_value}</span>,
    },
    {
      accessorKey: "effective_value",
      header: t("columnEffective"),
      cell: ({ row }) => <span className="font-medium text-foreground text-base">{row.original.effective_value}</span>,
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
