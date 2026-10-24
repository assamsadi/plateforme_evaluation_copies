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

import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FilterPill, filterPillTriggerCn } from "@/components/ui/filter-pill";
import { SearchInput } from "@/components/ui/search-input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { UserPublic } from "@/lib/auth-api";
import { dataTableFeatures } from "@/lib/data-table-features";

import { DataTable } from "../../_components/data-table";
import { AddUserDialog } from "./add-user-dialog";
import { roleValues, type UserRow } from "./data";
import { makeUsersColumns } from "./users-columns";

export function Users({
  users,
  onView,
  onEdit,
  onDeactivate,
  onReactivate,
  onCreated,
  pendingUserId,
}: {
  users: UserRow[];
  onView: (user: UserRow) => void;
  onEdit: (user: UserRow) => void;
  onDeactivate: (user: UserRow) => void;
  onReactivate: (user: UserRow) => void;
  onCreated: (user: UserPublic) => void;
  pendingUserId: string | null;
}) {
  const t = useTranslations("Users");
  const [rowSelection, setRowSelection] = React.useState({});
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({ search: false });
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });

  const roleOptions = ["All", ...roleValues] as const;
  const statusOptions = ["All", "Active", "Deactivated"] as const;

  const roleOptionLabel = (value: (typeof roleOptions)[number]) => {
    if (value === "All") return t("roleAll");
    if (value === "student") return t("roleStudent");
    if (value === "professor") return t("roleProfessor");
    return t("roleAdmin");
  };

  const statusOptionLabel = (value: (typeof statusOptions)[number]) => {
    if (value === "All") return t("statusAll");
    return value === "Active" ? t("statusActive") : t("statusDeactivated");
  };

  const columns = React.useMemo(
    () => makeUsersColumns({ t, onView, onEdit, onDeactivate, onReactivate, pendingUserId }),
    [t, onView, onEdit, onDeactivate, onReactivate, pendingUserId],
  );

  const table = useTable({
    features: dataTableFeatures,
    data: users,
    columns,
    state: { rowSelection, sorting, columnFilters, columnVisibility, pagination },
    getRowId: (row) => row.id,
    autoResetPageIndex: false,
    enableRowSelection: true,
    onRowSelectionChange: setRowSelection,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
  });

  const searchQuery = (table.getColumn("search")?.getFilterValue() as string | undefined) ?? "";
  const roleFilter = (table.getColumn("role")?.getFilterValue() as string | undefined) ?? roleOptions[0];
  const statusFilter = (table.getColumn("status")?.getFilterValue() as string | undefined) ?? statusOptions[0];
  const selectedCount = table.getFilteredSelectedRowModel().rows.length;

  function setColumnSelectFilter(columnId: string, value: string) {
    table.getColumn(columnId)?.setFilterValue(value === "All" ? undefined : value);
    table.setPageIndex(0);
  }

  // Filtre unique combinant rôle et statut — un seul contrôle plutôt que
  // deux pastilles séparées qui se lisaient comme deux barres différentes.
  // Un seul axe actif à la fois (mutuellement exclusifs) : choisir une
  // valeur d'un groupe réinitialise l'autre.
  const combinedFilterValue =
    roleFilter !== roleOptions[0]
      ? `role:${roleFilter}`
      : statusFilter !== statusOptions[0]
        ? `status:${statusFilter}`
        : "All";

  function handleCombinedFilterChange(value: string) {
    if (value === "All") {
      setColumnSelectFilter("role", "All");
      setColumnSelectFilter("status", "All");
      return;
    }
    const [kind, rawValue] = value.split(":");
    if (kind === "role") {
      setColumnSelectFilter("role", rawValue);
      setColumnSelectFilter("status", "All");
    } else {
      setColumnSelectFilter("status", rawValue);
      setColumnSelectFilter("role", "All");
    }
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
          <AddUserDialog onCreated={onCreated} />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-3 px-4">
          <div className="flex flex-wrap items-center gap-3">
            <FilterPill>
              <Select value={combinedFilterValue} onValueChange={handleCombinedFilterChange}>
                <SelectTrigger size="sm" className={filterPillTriggerCn}>
                  <span className="font-normal italic text-black dark:text-white">{t("filterLabel")}</span>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent
                  position="popper"
                  align="start"
                  className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700"
                >
                  <SelectGroup>
                    <SelectItem value="All" className="text-base font-medium">
                      {t("filterAll")}
                    </SelectItem>
                  </SelectGroup>
                  <SelectSeparator />
                  <SelectGroup>
                    <SelectLabel>{t("roleLabel")}</SelectLabel>
                    {roleValues.map((option) => (
                      <SelectItem key={option} value={`role:${option}`} className="text-base font-medium">
                        {roleOptionLabel(option)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                  <SelectSeparator />
                  <SelectGroup>
                    <SelectLabel>{t("statusLabel")}</SelectLabel>
                    {statusOptions
                      .filter((option) => option !== "All")
                      .map((option) => (
                        <SelectItem key={option} value={`status:${option}`} className="text-base font-medium">
                          {statusOptionLabel(option)}
                        </SelectItem>
                      ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </FilterPill>
          </div>

          <div className="text-base font-medium text-muted-foreground tabular-nums">
            {t("selectedCount", { count: selectedCount })}
          </div>
        </div>

        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>
    </Card>
  );
}
