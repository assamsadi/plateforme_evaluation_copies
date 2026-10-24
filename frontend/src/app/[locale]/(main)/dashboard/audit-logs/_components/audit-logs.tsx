"use client";
import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { ScrollText } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { FilterPill, filterPillTriggerCn } from "@/components/ui/filter-pill";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { dataTableFeatures } from "@/lib/data-table-features";
import type { AuditLogRead } from "@/lib/admin-api";

import { DataTable } from "../../_components/data-table";
import { makeAuditLogsColumns } from "./audit-logs-columns";
import { severityValues } from "./data";

export function AuditLogs({ logs }: { logs: AuditLogRead[] }) {
  const t = useTranslations("AuditLogs");
  const locale = useLocale();
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 20 });

  const severityOptions = ["All", ...severityValues] as const;
  const severityOptionLabel = (value: (typeof severityOptions)[number]) => {
    if (value === "All") return t("severityAll");
    return t(`severity${value.charAt(0).toUpperCase()}${value.slice(1)}`);
  };

  const columns = React.useMemo(() => makeAuditLogsColumns({ t, locale }), [t, locale]);

  const table = useTable({
    features: dataTableFeatures,
    data: logs,
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
  const severityFilter = (table.getColumn("severity")?.getFilterValue() as string | undefined) ?? severityOptions[0];

  return (
    <Card className="overflow-hidden">
      <div className="h-1 w-full bg-primary" />
      <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
            <ScrollText className="size-5" />
          </div>
          <div>
            <CardTitle className="text-base font-bold leading-none text-slate-900 dark:text-zinc-100">
              {t("title")}
              <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
                {logs.length}
              </span>
            </CardTitle>
            <CardDescription className="mt-1 text-sm font-medium">{t("description")}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0 pt-3">
        <div className="flex flex-wrap items-center gap-3 px-4">
          <SearchInput
            className="w-full md:w-72"
            placeholder={t("searchPlaceholder")}
            value={searchQuery}
            onChange={(event) => {
              table.getColumn("search")?.setFilterValue(event.target.value || undefined);
              table.setPageIndex(0);
            }}
          />

          <FilterPill>
            <Select
              value={severityFilter}
              onValueChange={(value) => {
                table.getColumn("severity")?.setFilterValue(value === "All" ? undefined : value);
                table.setPageIndex(0);
              }}
            >
              <SelectTrigger size="sm" className={filterPillTriggerCn}>
                <span className="font-normal text-slate-400/90 dark:text-zinc-500">{t("severityLabel")}</span>
                <SelectValue />
              </SelectTrigger>
              <SelectContent position="popper" align="start" className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                <SelectGroup>
                  {severityOptions.map((option) => (
                    <SelectItem key={option} value={option} className="text-sm font-medium">
                      {severityOptionLabel(option)}
                    </SelectItem>
                  ))}
                </SelectGroup>
              </SelectContent>
            </Select>
          </FilterPill>
        </div>

        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>
    </Card>
  );
}
