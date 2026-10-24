"use client";
import type { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { GroupRead } from "@/lib/admin-api";
import type { DataTableFeatures } from "@/lib/data-table-features";

export function makeGroupsColumns(options: {
  t: (key: string) => string;
  onDelete: (group: GroupRead) => void;
  pendingGroupId: string | null;
}): ColumnDef<DataTableFeatures, GroupRead>[] {
  const { t } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.label} ${row.academic_year}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "id",
      header: t("columnId"),
      cell: ({ row }) => <span className="select-all font-mono text-sm text-muted-foreground">{row.original.id}</span>,
    },
    {
      accessorKey: "label",
      header: t("columnLabel"),
      cell: ({ row }) => <span className="font-medium text-foreground text-base">{row.original.label}</span>,
    },
    {
      accessorKey: "academic_year",
      header: t("columnAcademicYear"),
    },
    {
      id: "actions",
      header: () => <div className="text-right">{t("columnActions")}</div>,
      cell: ({ row }) => {
        const group = row.original;
        const isPending = options.pendingGroupId === group.id;
        return (
          <div className="text-right">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  aria-label={`Ouvrir les actions pour ${group.label}`}
                  className="size-8 rounded-md text-muted-foreground hover:bg-muted/50"
                  size="icon-sm"
                  variant="ghost"
                  disabled={isPending}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem variant="destructive" onClick={() => options.onDelete(group)}>
                  {t("deleteAction")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        );
      },
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
