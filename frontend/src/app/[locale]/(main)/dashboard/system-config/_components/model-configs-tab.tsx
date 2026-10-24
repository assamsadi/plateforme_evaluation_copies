"use client";

import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { getModelConfigurations, type ModelConfigurationRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { dataTableFeatures } from "@/lib/data-table-features";

import { DataTable } from "../../_components/data-table";
import { EditModelConfigDialog } from "./edit-model-config-dialog";
import { makeModelConfigsColumns } from "./model-configs-columns";

export function ModelConfigsTab() {
  const t = useTranslations("ModelConfigs");
  const [configs, setConfigs] = React.useState<ModelConfigurationRead[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [editTarget, setEditTarget] = React.useState<ModelConfigurationRead | null>(null);

  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 20 });

  const fetchConfigs = React.useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await getModelConfigurations(session.accessToken);
      setConfigs(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  React.useEffect(() => {
    fetchConfigs();
  }, [fetchConfigs]);

  function handleUpdated(updated: ModelConfigurationRead) {
    setConfigs((prev) => prev.map((c) => (c.task_type === updated.task_type ? updated : c)));
    toast.success(t("updateSuccess", { taskType: updated.task_type }));
  }

  const columns = React.useMemo(() => makeModelConfigsColumns({ t, onEdit: setEditTarget }), [t]);

  const table = useTable({
    features: dataTableFeatures,
    data: configs,
    columns,
    state: { sorting, columnFilters, columnVisibility, pagination },
    getRowId: (row) => row.task_type,
    autoResetPageIndex: false,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
  });

  const searchQuery = (table.getColumn("search")?.getFilterValue() as string | undefined) ?? "";

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading) {
    return <div className="text-muted-foreground text-base">{t("loading")}</div>;
  }

  return (
    <Card className="border border-border/80 bg-card shadow-2xs">
      <CardHeader className="border-b border-border/80 pb-4 pt-5 has-data-[slot=card-action]:grid-cols-1 md:has-data-[slot=card-action]:grid-cols-[1fr_auto]">
        <div>
          <CardTitle className="text-xl font-bold leading-none text-slate-900 dark:text-zinc-100">
            {t("title")}
          </CardTitle>
          <CardDescription className="mt-1.5 max-w-md text-base font-medium leading-snug">
            {t("description")}
          </CardDescription>
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
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0">
        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>

      <EditModelConfigDialog
        config={editTarget}
        open={Boolean(editTarget)}
        onOpenChange={(open) => !open && setEditTarget(null)}
        onUpdated={handleUpdated}
      />
    </Card>
  );
}
