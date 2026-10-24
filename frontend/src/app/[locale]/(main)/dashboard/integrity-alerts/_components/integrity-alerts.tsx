"use client";
import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { Flag, ShieldAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { StatusBadge } from "@/components/ui/status-badge";
import { dataTableFeatures } from "@/lib/data-table-features";
import type { IntegrityAlertRead } from "@/lib/admin-api";

import { DataTable } from "../../_components/data-table";
import { makeIntegrityAlertsColumns } from "./integrity-alerts-columns";

export function IntegrityAlerts({
  alerts,
  onResolve,
  onFlagStudent,
}: {
  alerts: IntegrityAlertRead[];
  onResolve: (alert: IntegrityAlertRead) => void;
  onFlagStudent: () => void;
}) {
  const t = useTranslations("IntegrityAlerts");
  const locale = useLocale();
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 20 });

  const columns = React.useMemo(() => makeIntegrityAlertsColumns({ t, onResolve, locale }), [t, onResolve, locale]);

  const table = useTable({
    features: dataTableFeatures,
    data: alerts,
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
      <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
              <ShieldAlert className="size-5" />
            </div>
            <div>
              <CardTitle className="text-base font-bold leading-none text-slate-900 dark:text-zinc-100">
                {t("title")}
                <StatusBadge tone="warning" status={`${alerts.length}`} className="ml-2" />
              </CardTitle>
              <CardDescription className="mt-1 text-sm font-medium">{t("description")}</CardDescription>
            </div>
          </div>
          <Button size="sm" variant="skew" className="h-10 rounded-xl px-4 text-sm font-semibold tracking-wide" onClick={onFlagStudent}>
            <Flag className="size-4" /> {t("flagStudentAction")}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0 pt-3 pb-2">
        <div className="px-4">
          <SearchInput
            className="w-full md:w-72"
            placeholder={t("searchPlaceholder")}
            value={searchQuery}
            onChange={(event) => {
              table.getColumn("search")?.setFilterValue(event.target.value || undefined);
              table.setPageIndex(0);
            }}
          />
        </div>

        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>
    </Card>
  );
}
