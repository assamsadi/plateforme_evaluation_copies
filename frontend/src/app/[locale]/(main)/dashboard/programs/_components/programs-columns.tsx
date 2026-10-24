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
import { Link } from "@/i18n/navigation";
import type { DataTableFeatures } from "@/lib/data-table-features";

import type { ProgramRow } from "./data";

export function makeProgramsColumns(options: {
  t: (key: string) => string;
  onEdit: (program: ProgramRow) => void;
  onDelete: (program: ProgramRow) => void;
  pendingProgramId: string | null;
}): ColumnDef<DataTableFeatures, ProgramRow>[] {
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
        <Link
          href={`/dashboard/programs/${row.original.id}`}
          className="font-medium text-foreground text-base hover:underline"
        >
          {row.original.name}
        </Link>
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
        const program = row.original;
        const isPending = options.pendingProgramId === program.id;
        return (
          <div className="text-right">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  aria-label={`Ouvrir les actions pour ${program.name}`}
                  className="size-8 rounded-md text-muted-foreground hover:bg-muted/50"
                  size="icon-sm"
                  variant="ghost"
                  disabled={isPending}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem asChild>
                  <Link href={`/dashboard/programs/${program.id}`}>{t("viewAction")}</Link>
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => options.onEdit(program)}>{t("editAction")}</DropdownMenuItem>
                <DropdownMenuItem variant="destructive" onClick={() => options.onDelete(program)}>
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
