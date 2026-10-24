"use client";
import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { Scale } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { StatusBadge } from "@/components/ui/status-badge";
import { dataTableFeatures } from "@/lib/data-table-features";
import type { GradeAppealRead } from "@/lib/professor-api";

import { DataTable } from "../../_components/data-table";
import { makeAppealsColumns } from "./appeals-columns";

export function Appeals({
  appeals,
  onResolve,
}: {
  appeals: GradeAppealRead[];
  onResolve: (appeal: GradeAppealRead) => void;
}) {
  const t = useTranslations("Appeals");
  const locale = useLocale();
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 20 });

  const columns = React.useMemo(() => makeAppealsColumns({ t, onResolve, locale }), [t, onResolve, locale]);

  const table = useTable({
    features: dataTableFeatures,
    data: appeals,
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
  const pendingCount = appeals.filter((a) => a.status === "pending").length;

  return (
    <Card className="overflow-hidden">
      <div className="h-1 w-full bg-primary" />
      <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
              <Scale className="size-4" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold leading-none text-slate-900 dark:text-zinc-100">
                {t("title")}
                {pendingCount > 0 && (
                  <StatusBadge tone="warning" status={`${pendingCount} pending`} className="ml-2" />
                )}
              </CardTitle>
              <CardDescription className="mt-0.5 text-xs">{t("description")}</CardDescription>
            </div>
          </div>
          <SearchInput
            className="h-9 w-full max-w-xs"
            inputClassName="h-9 text-sm"
            placeholder={t("searchPlaceholder")}
            value={searchQuery}
            onChange={(event) => {
              table.getColumn("search")?.setFilterValue(event.target.value || undefined);
              table.setPageIndex(0);
            }}
          />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0 pt-2">
        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>
    </Card>
  );
}
