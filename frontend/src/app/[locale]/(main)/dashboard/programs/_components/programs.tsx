"use client";
import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { GraduationCap } from "lucide-react";
import { useTranslations } from "next-intl";

import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import type { ProgramRead } from "@/lib/admin-api";
import { dataTableFeatures } from "@/lib/data-table-features";

import { DataTable } from "../../_components/data-table";
import { AddProgramDialog } from "./add-program-dialog";
import type { ProgramRow } from "./data";
import { makeProgramsColumns } from "./programs-columns";

export function Programs({
  programs,
  onEdit,
  onDelete,
  onCreated,
  pendingProgramId,
}: {
  programs: ProgramRow[];
  onEdit: (program: ProgramRow) => void;
  onDelete: (program: ProgramRow) => void;
  onCreated: (program: ProgramRead) => void;
  pendingProgramId: string | null;
}) {
  const t = useTranslations("Programs");
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });

  const columns = React.useMemo(
    () => makeProgramsColumns({ t, onEdit, onDelete, pendingProgramId }),
    [t, onEdit, onDelete, pendingProgramId],
  );

  const table = useTable({
    features: dataTableFeatures,
    data: programs,
    columns,
    state: { sorting, columnFilters, columnVisibility, pagination },
    getRowId: (row) => row.id,
    autoResetPageIndex: false,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
  });

  const searchQuery = (table.getColumn("search")?.getFilterValue() as string | undefined) ?? "";

  return (
    <Card className="overflow-hidden">
      <div className="h-1 w-full bg-primary" />
      <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80 has-data-[slot=card-action]:grid-cols-1 md:has-data-[slot=card-action]:grid-cols-[1fr_auto]">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
            <GraduationCap className="size-5" />
          </div>
          <div>
            <CardTitle className="text-base font-bold leading-none text-slate-900 dark:text-zinc-100">
              {t("title")}
              <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-sm font-semibold text-muted-foreground">
                {programs.length}
              </span>
            </CardTitle>
            <CardDescription className="mt-1 text-base font-medium">{t("description")}</CardDescription>
          </div>
        </div>
        <CardAction className="col-start-1 row-start-auto flex w-full flex-wrap justify-start gap-2 justify-self-stretch md:col-start-2 md:row-span-2 md:row-start-1 md:w-auto md:flex-nowrap md:justify-end md:justify-self-end">
          <SearchInput
            className="w-full md:w-72"
            placeholder={t("searchPlaceholder")}
            value={searchQuery}
            onChange={(event) => {
              table.getColumn("search")?.setFilterValue(event.target.value || undefined);
              table.setPageIndex(0);
            }}
          />
          <AddProgramDialog onCreated={onCreated} />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0 pt-3">
        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>
    </Card>
  );
}
