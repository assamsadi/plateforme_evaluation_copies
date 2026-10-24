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

import { DeleteConfirmDialog } from "@/app/[locale]/(main)/dashboard/_components/delete-confirm-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { deleteModule, listModulesByProgram, type ModuleRead } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { dataTableFeatures } from "@/lib/data-table-features";

import { DataTable } from "../../../_components/data-table";
import { AddModuleDialog } from "./add-module-dialog";
import { EditModuleDialog } from "./edit-module-dialog";
import { EnrollmentSheet } from "./enrollment-sheet";
import { makeModulesColumns } from "./modules-columns";

export function ModulesTab({ programId }: { programId: string }) {
  const t = useTranslations("Modules");
  const [modules, setModules] = React.useState<ModuleRead[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [pendingModuleId, setPendingModuleId] = React.useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<ModuleRead | null>(null);
  const [editTarget, setEditTarget] = React.useState<ModuleRead | null>(null);
  const [rosterModule, setRosterModule] = React.useState<ModuleRead | null>(null);

  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });

  const fetchModules = React.useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listModulesByProgram(session.accessToken, programId);
      setModules(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [programId, t]);

  React.useEffect(() => {
    fetchModules();
  }, [fetchModules]);

  async function handleConfirmDelete() {
    const session = getStoredSession();
    const target = deleteTarget;
    if (!session || !target) return;

    setPendingModuleId(target.id);
    try {
      await deleteModule(session.accessToken, target.id);
      setModules((prev) => prev.filter((m) => m.id !== target.id));
      toast.success(t("deleteSuccess", { name: target.name }));
      setDeleteTarget(null);
    } catch (actionError) {
      toast.error(actionError instanceof AuthApiError ? actionError.message : t("deleteError"));
    } finally {
      setPendingModuleId(null);
    }
  }

  function handleCreated(created: ModuleRead) {
    setModules((prev) => [created, ...prev]);
    toast.success(t("createSuccess", { name: created.name }));
  }

  function handleUpdated(updated: ModuleRead) {
    setModules((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
    toast.success(t("updateSuccess", { name: updated.name }));
  }

  const columns = React.useMemo(
    () =>
      makeModulesColumns({
        t,
        onViewEnrollments: setRosterModule,
        onEdit: setEditTarget,
        onDelete: setDeleteTarget,
        pendingModuleId,
      }),
    [t, pendingModuleId],
  );

  const table = useTable({
    features: dataTableFeatures,
    data: modules,
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
          <CardDescription className="mt-1.5 max-w-sm text-base font-medium leading-relaxed">
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
          <AddModuleDialog programId={programId} onCreated={handleCreated} />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0">
        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>

      <EditModuleDialog
        module={editTarget}
        open={Boolean(editTarget)}
        onOpenChange={(open) => !open && setEditTarget(null)}
        onUpdated={handleUpdated}
      />

      <DeleteConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={t("deleteAction")}
        description={deleteTarget ? t("deleteConfirmDescription", { name: deleteTarget.name }) : ""}
        cancelLabel={t("cancel")}
        confirmLabel={t("deleteAction")}
        isPending={Boolean(pendingModuleId)}
        onConfirm={handleConfirmDelete}
      />

      <EnrollmentSheet
        moduleId={rosterModule?.id ?? null}
        moduleName={rosterModule?.name ?? ""}
        open={Boolean(rosterModule)}
        onOpenChange={(open) => !open && setRosterModule(null)}
      />
    </Card>
  );
}
