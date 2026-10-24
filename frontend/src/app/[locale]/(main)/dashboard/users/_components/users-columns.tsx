"use client";
import type { ColumnDef } from "@tanstack/react-table";
import { Subscribe } from "@tanstack/react-table";
import { MoreHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { StatusBadge } from "@/components/ui/status-badge";
import type { DataTableFeatures } from "@/lib/data-table-features";
import { getInitials } from "@/lib/utils";

import type { UserRow } from "./data";

function RoleBadge({ role }: { role: UserRow["role"] }) {
  const t = useTranslations("Users");
  // Un rôle n'est jamais un statut/feedback — pas de couleur libre par
  // rôle (violet/sky/amber), une seule teinte neutre pour les 3, cf.
  // unification design system.
  const labels: Record<UserRow["role"], string> = {
    student: t("roleStudent"),
    professor: t("roleProfessor"),
    admin: t("roleAdmin"),
  };
  return <StatusBadge tone="neutral" status={labels[role]} />;
}

function AccountStatusBadge({ isActive }: { isActive: boolean }) {
  const t = useTranslations("Users");
  return (
    <StatusBadge
      tone={isActive ? "success" : "danger"}
      status={isActive ? t("statusActive") : t("statusDeactivated")}
    />
  );
}

export function makeUsersColumns(options: {
  t: (key: string) => string;
  onView: (user: UserRow) => void;
  onEdit: (user: UserRow) => void;
  onDeactivate: (user: UserRow) => void;
  onReactivate: (user: UserRow) => void;
  pendingUserId: string | null;
}): ColumnDef<DataTableFeatures, UserRow>[] {
  const { t } = options;

  return [
    {
      id: "select",
      header: ({ table }) => (
        <div className="flex items-center justify-center">
          <Subscribe
            source={table.atoms.rowSelection}
            selector={() =>
              table.getIsAllPageRowsSelected() ||
              (table.getIsSomePageRowsSelected() && !table.getIsAllPageRowsSelected() && "indeterminate")
            }
          >
            {(checked) => (
              <Checkbox
                aria-label="Select all users"
                checked={checked}
                onCheckedChange={(value) => table.toggleAllPageRowsSelected(!!value)}
              />
            )}
          </Subscribe>
        </div>
      ),
      cell: ({ row }) => (
        <div className="flex items-center justify-center">
          <Subscribe source={row.table.atoms.rowSelection} selector={(selection) => Boolean(selection?.[row.id])}>
            {(checked) => (
              <Checkbox
                aria-label={`Select ${row.original.firstName} ${row.original.lastName}`}
                checked={checked}
                onCheckedChange={(value) => row.toggleSelected(!!value)}
              />
            )}
          </Subscribe>
        </div>
      ),
      enableHiding: false,
      enableSorting: false,
    },
    {
      id: "search",
      accessorFn: (row) => `${row.firstName} ${row.lastName} ${row.email}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "id",
      header: t("columnUserId"),
      cell: ({ row }) => <span className="select-all font-mono text-sm text-muted-foreground">{row.original.id}</span>,
    },
    {
      accessorKey: "firstName",
      header: t("columnUser"),
      cell: ({ row }) => {
        const fullName = `${row.original.firstName} ${row.original.lastName}`;
        return (
          <div className="flex items-center gap-3">
            <Avatar size="lg">
              <AvatarFallback>{getInitials(fullName)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <div className="truncate font-semibold text-foreground text-base">{fullName}</div>
              <div className="truncate text-muted-foreground text-base">{row.original.email}</div>
            </div>
          </div>
        );
      },
    },
    {
      accessorKey: "role",
      header: t("columnRole"),
      filterFn: "equalsString",
      cell: ({ row }) => <RoleBadge role={row.original.role} />,
    },
    {
      id: "status",
      accessorFn: (row) => (row.isActive ? "Active" : "Deactivated"),
      header: t("columnStatus"),
      filterFn: "equalsString",
      cell: ({ row }) => <AccountStatusBadge isActive={row.original.isActive} />,
    },
    {
      id: "actions",
      header: () => <div className="text-right">{t("columnActions")}</div>,
      cell: ({ row }) => {
        const user = row.original;
        const isPending = options.pendingUserId === user.id;
        return (
          <div className="text-right">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  aria-label={`Ouvrir les actions pour ${user.firstName} ${user.lastName}`}
                  className="size-8 rounded-md text-muted-foreground hover:bg-muted/50"
                  size="icon-sm"
                  variant="ghost"
                  disabled={isPending}
                >
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => options.onView(user)}>{t("viewAction")}</DropdownMenuItem>
                <DropdownMenuItem onClick={() => options.onEdit(user)}>{t("editAction")}</DropdownMenuItem>
                {user.isActive ? (
                  <DropdownMenuItem variant="destructive" onClick={() => options.onDeactivate(user)}>
                    {t("deactivateAction")}
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem onClick={() => options.onReactivate(user)}>
                    {t("reactivateAction")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        );
      },
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
