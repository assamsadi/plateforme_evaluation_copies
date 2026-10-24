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
import { deleteGroup, type GroupRead, listGroupsByProgram } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { dataTableFeatures } from "@/lib/data-table-features";

import { DataTable } from "../../../_components/data-table";
import { AddGroupDialog } from "./add-group-dialog";
import { makeGroupsColumns } from "./groups-columns";

export function GroupsTab({ programId }: { programId: string }) {
  const t = useTranslations("Groups");
  const [groups, setGroups] = React.useState<GroupRead[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [pendingGroupId, setPendingGroupId] = React.useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<GroupRead | null>(null);

  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });

  const fetchGroups = React.useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listGroupsByProgram(session.accessToken, programId);
      setGroups(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [programId, t]);

  React.useEffect(() => {
    fetchGroups();
  }, [fetchGroups]);

  async function handleConfirmDelete() {
    const session = getStoredSession();
    const target = deleteTarget;
    if (!session || !target) return;

    setPendingGroupId(target.id);
    try {
      await deleteGroup(session.accessToken, target.id);
      setGroups((prev) => prev.filter((g) => g.id !== target.id));
      toast.success(t("deleteSuccess", { label: target.label }));
      setDeleteTarget(null);
    } catch (actionError) {
      toast.error(actionError instanceof AuthApiError ? actionError.message : t("deleteError"));
    } finally {
      setPendingGroupId(null);
    }
  }

  function handleCreated(created: GroupRead) {
    setGroups((prev) => [created, ...prev]);
    toast.success(t("createSuccess", { label: created.label }));
  }

  const columns = React.useMemo(
    () => makeGroupsColumns({ t, onDelete: setDeleteTarget, pendingGroupId }),
    [t, pendingGroupId],
  );

  const table = useTable({
    features: dataTableFeatures,
    data: groups,
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
          <AddGroupDialog programId={programId} onCreated={handleCreated} />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0">
        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>

      <DeleteConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={t("deleteAction")}
        description={deleteTarget ? t("deleteConfirmDescription", { label: deleteTarget.label }) : ""}
        cancelLabel={t("cancel")}
        confirmLabel={t("deleteAction")}
        isPending={Boolean(pendingGroupId)}
        onConfirm={handleConfirmDelete}
      />
    </Card>
  );
}
