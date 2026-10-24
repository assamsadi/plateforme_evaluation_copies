"use client";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { DataPrivacyRequestRead } from "@/lib/admin-api";
import type { DataTableFeatures } from "@/lib/data-table-features";

import { statusTone } from "./data";

export function makePrivacyRequestsColumns(options: {
  t: (key: string) => string;
  onView: (request: DataPrivacyRequestRead) => void;
  locale: string;
}): ColumnDef<DataTableFeatures, DataPrivacyRequestRead>[] {
  const { t, locale } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => `${row.user_full_name} ${row.request_type}`,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "created_at",
      header: t("columnDate"),
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-base font-semibold text-success">
          {new Date(row.original.created_at).toLocaleString(locale)}
        </span>
      ),
    },
    {
      accessorKey: "user_full_name",
      header: t("columnUser"),
      cell: ({ row }) => <span className="font-medium text-foreground text-base">{row.original.user_full_name}</span>,
    },
    {
      accessorKey: "request_type",
      header: t("columnType"),
      cell: ({ row }) => <span className="text-base">{t(`type_${row.original.request_type}`)}</span>,
    },
    {
      accessorKey: "status",
      header: t("columnStatus"),
      cell: ({ row }) => (
        <StatusBadge tone={statusTone[row.original.status]} status={t(`status_${row.original.status}`)} />
      ),
    },
    {
      accessorKey: "identity_verified",
      header: t("columnIdentity"),
      cell: ({ row }) =>
        row.original.identity_verified ? (
          <span className="text-success text-base">{t("identityVerified")}</span>
        ) : (
          <span className="text-muted-foreground text-base">{t("identityNotVerified")}</span>
        ),
    },
    {
      accessorKey: "legal_deadline",
      header: t("columnDeadline"),
      cell: ({ row }) => (
        <span className="whitespace-nowrap text-base font-semibold text-danger">
          {new Date(row.original.legal_deadline).toLocaleDateString(locale)}
        </span>
      ),
    },
    {
      id: "actions",
      header: () => <div className="text-right">{t("columnActions")}</div>,
      cell: ({ row }) => (
        <div className="text-right">
          <Button
            size="sm"
            variant="skew"
            className="h-8 px-3 text-base font-semibold tracking-wide"
            onClick={() => options.onView(row.original)}
          >
            {t("viewAction")}
          </Button>
        </div>
      ),
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
