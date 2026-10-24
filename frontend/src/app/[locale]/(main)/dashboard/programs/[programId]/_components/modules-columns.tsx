"use client";
import type { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ModuleRead } from "@/lib/admin-api";
import type { DataTableFeatures } from "@/lib/data-table-features";

export function makeModulesColumns(options: {
  t: (key: string) => string;
  onViewEnrollments: (module: ModuleRead) => void;
  onEdit: (module: ModuleRead) => void;
  onDelete: (module: ModuleRead) => void;
  pendingModuleId: string | null;
}): ColumnDef<DataTableFeatures, ModuleRead>[] {
  const { t } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.name} ${row.code}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "id",
      header: t("columnId"),
      cell: ({ row }) => <span className="select-all font-mono text-sm text-muted-foreground">{row.original.id}</span>,
    },
    {
      accessorKey: "name",
      header: t("columnName"),
      cell: ({ row }) => (
        <button
          type="button"
          className="text-left font-medium text-foreground text-base hover:underline"
          onClick={() => options.onViewEnrollments(row.original)}
        >
          {row.original.name}
        </button>
      ),
    },
    {
      accessorKey: "code",
      header: t("columnCode"),
      cell: ({ row }) => (
        <Badge className="font-mono" variant="outline">
          {row.original.code}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: () => <div className="text-right">{t("columnActions")}</div>,
      cell: ({ row }) => {
        const module_ = row.original;
        const isPending = options.pendingModuleId === module_.id;
        return (
          <div className="text-right">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  aria-label={`Ouvrir les actions pour ${module_.name}`}
                  className="size-8 rounded-md text-muted-foreground hover:bg-muted/50"
                  size="icon-sm"
                  variant="ghost"
                  disabled={isPending}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => options.onViewEnrollments(module_)}>
                  {t("viewEnrollmentsAction")}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => options.onEdit(module_)}>{t("editAction")}</DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={() => options.onDelete(module_)}>
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
