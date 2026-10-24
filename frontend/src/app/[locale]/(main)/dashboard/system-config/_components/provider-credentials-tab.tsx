"use client";

import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { Info, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SearchInput } from "@/components/ui/search-input";
import { clearProviderCredential, getProviderCredentials, type ProviderCredentialRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { dataTableFeatures } from "@/lib/data-table-features";

import { DataTable } from "../../_components/data-table";
import { DeleteConfirmDialog } from "../../_components/delete-confirm-dialog";
import { AddCredentialDialog } from "./add-credential-dialog";
import { EditCredentialDialog } from "./edit-credential-dialog";
import { makeProviderCredentialsColumns } from "./provider-credentials-columns";

export function ProviderCredentialsTab() {
  const t = useTranslations("ProviderCredentials");
  const [credentials, setCredentials] = React.useState<ProviderCredentialRead[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [editTarget, setEditTarget] = React.useState<ProviderCredentialRead | null>(null);
  const [clearTarget, setClearTarget] = React.useState<ProviderCredentialRead | null>(null);
  const [isClearing, setIsClearing] = React.useState(false);
  const [isAddOpen, setIsAddOpen] = React.useState(false);

  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 20 });

  const fetchCredentials = React.useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await getProviderCredentials(session.accessToken);
      setCredentials(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  React.useEffect(() => {
    fetchCredentials();
  }, [fetchCredentials]);

  function handleUpdated(updated: ProviderCredentialRead) {
    setCredentials((prev) => prev.map((c) => (c.key === updated.key ? updated : c)));
    toast.success(t("updateSuccess", { key: updated.key }));
  }

  function handleCreated(created: ProviderCredentialRead) {
    setCredentials((prev) => [created, ...prev.filter((c) => c.key !== created.key)]);
    toast.success(t("createSuccess", { key: created.key }));
  }

  async function handleConfirmClear() {
    const session = getStoredSession();
    const target = clearTarget;
    if (!session || !target) return;

    setIsClearing(true);
    try {
      await clearProviderCredential(session.accessToken, target.key);
      await fetchCredentials();
      toast.success(t("clearSuccess", { key: target.key }));
      setClearTarget(null);
    } catch (clearError) {
      toast.error(clearError instanceof AuthApiError ? clearError.message : t("clearError"));
    } finally {
      setIsClearing(false);
    }
  }

  const columns = React.useMemo(
    () => makeProviderCredentialsColumns({ t, onEdit: setEditTarget, onClear: setClearTarget }),
    [t],
  );

  const table = useTable({
    features: dataTableFeatures,
    data: credentials,
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
                  className="w-96 overflow-hidden rounded-2xl border-0 bg-[#F8FBFE] p-0 text-base leading-relaxed shadow-2xl ring-1 ring-black/10 dark:bg-zinc-900 dark:ring-white/10"
                >
                  <div className="flex items-center gap-1.5 border-b border-black/5 px-4 py-2.5 dark:border-white/10">
                    <span className="size-2.5 rounded-full bg-[#ff605c]" />
                    <span className="size-2.5 rounded-full bg-[#ffbd44]" />
                    <span className="size-2.5 rounded-full bg-[#00ca4e]" />
                  </div>
                  <div className="flex flex-col gap-3.5 p-4">
                    <div>
                      <p className="mb-1 text-sm font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                        {t("noticeTitle")}
                      </p>
                      <p className="italic text-black dark:text-zinc-200">{t("noticeDescription")}</p>
                    </div>
                    <div>
                      <p className="mb-1 text-sm font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                        {t("statusLegendTitle")}
                      </p>
                      <p className="italic text-black dark:text-zinc-200">{t("statusLegendDescription")}</p>
                    </div>
                  </div>
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
            <Button
              size="sm"
              variant="skew"
              className="h-10 px-4 text-base font-semibold tracking-wide"
              onClick={() => setIsAddOpen(true)}
            >
              <Plus className="size-4" /> {t("addAction")}
            </Button>
          </CardAction>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 px-0">
          <DataTable table={table} emptyMessage={t("noResults")} />
        </CardContent>
      </Card>

      <EditCredentialDialog
        credential={editTarget}
        open={Boolean(editTarget)}
        onOpenChange={(open) => !open && setEditTarget(null)}
        onUpdated={handleUpdated}
      />
      <AddCredentialDialog open={isAddOpen} onOpenChange={setIsAddOpen} onCreated={handleCreated} />
      <DeleteConfirmDialog
        open={Boolean(clearTarget)}
        onOpenChange={(open) => !open && setClearTarget(null)}
        title={t("clearConfirmTitle")}
        description={clearTarget ? t("clearConfirmDescription", { key: clearTarget.key }) : ""}
        cancelLabel={t("cancel")}
        confirmLabel={t("clearAction")}
        isPending={isClearing}
        onConfirm={handleConfirmClear}
      />
    </div>
  );
}
