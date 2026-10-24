"use client";

import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";
import { getSystemSettings, type SettingOverrideRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { dataTableFeatures } from "@/lib/data-table-features";

import { DataTable } from "../../_components/data-table";
import { EditSettingDialog } from "./edit-setting-dialog";
import { makeSettingsColumns } from "./settings-columns";

export function SettingsTab() {
  const t = useTranslations("SystemSettings");
  const [settingsList, setSettingsList] = React.useState<SettingOverrideRead[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [editTarget, setEditTarget] = React.useState<SettingOverrideRead | null>(null);

  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 20 });

  const fetchSettings = React.useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await getSystemSettings(session.accessToken);
      setSettingsList(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  React.useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  function handleUpdated(updated: SettingOverrideRead) {
    setSettingsList((prev) => prev.map((s) => (s.key === updated.key ? updated : s)));
    toast.success(t("updateSuccess", { key: updated.key }));
  }

  const columns = React.useMemo(() => makeSettingsColumns({ t, onEdit: setEditTarget }), [t]);

  const table = useTable({
    features: dataTableFeatures,
    data: settingsList,
    columns,
    state: { sorting, columnFilters, columnVisibility, pagination },
    getRowId: (row) => row.key,
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
    <div className="flex flex-col gap-4">
      <Card className="border border-border/80 bg-card shadow-2xs">
        <CardHeader className="border-b border-border/80 pb-4 pt-5 has-data-[slot=card-action]:grid-cols-1 md:has-data-[slot=card-action]:grid-cols-[1fr_auto]">
          <div>
            <CardTitle className="flex items-center gap-2 text-xl font-bold leading-none text-slate-900 dark:text-zinc-100">
              {t("title")}
              <Popover>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    className="text-slate-400 transition-colors hover:text-slate-700 dark:text-zinc-500 dark:hover:text-zinc-200"
                  >
                    <Info className="size-4" />
                  </button>
                </PopoverTrigger>
                <PopoverContent
                  align="start"
                  className="w-80 rounded-xl border-slate-200 text-base leading-relaxed shadow-lg dark:border-zinc-700"
                >
                  <p className="mb-1.5 text-sm font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                    {t("noticeTitle")}
                  </p>
                  <p className="text-slate-700 dark:text-zinc-300">{t("noticeDescription")}</p>
                </PopoverContent>
              </Popover>
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
      </Card>

      <EditSettingDialog
        setting={editTarget}
        open={Boolean(editTarget)}
        onOpenChange={(open) => !open && setEditTarget(null)}
        onUpdated={handleUpdated}
      />
    </div>
  );
}
