"use client";
import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { dataTableFeatures } from "@/lib/data-table-features";
import type { DataPrivacyRequestRead } from "@/lib/admin-api";

import { DataTable } from "../../_components/data-table";
import { makePrivacyRequestsColumns } from "./privacy-requests-columns";

export function PrivacyRequests({
  requests,
  onView,
}: {
  requests: DataPrivacyRequestRead[];
  onView: (request: DataPrivacyRequestRead) => void;
}) {
  const t = useTranslations("PrivacyRequests");
  const locale = useLocale();
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 20 });

  const columns = React.useMemo(() => makePrivacyRequestsColumns({ t, onView, locale }), [t, onView, locale]);

  const table = useTable({
    features: dataTableFeatures,
    data: requests,
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
    <Card className="border border-border/80 bg-card shadow-2xs">
      <CardHeader className="border-b border-border/80 pb-4 pt-5">
        <CardTitle className="text-xl font-bold leading-none text-slate-900 dark:text-zinc-100">{t("title")}</CardTitle>
        <CardDescription className="mt-1.5 max-w-sm text-sm font-medium leading-relaxed">{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0 pt-4">
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
