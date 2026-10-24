"use client";
import type { ColumnDef } from "@tanstack/react-table";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/status-badge";
import type { ProviderCredentialRead } from "@/lib/admin-api";
import type { DataTableFeatures } from "@/lib/data-table-features";

// Clés connues -> clé de traduction du libellé lisible (cf. le même
// pattern pour les noms d'agents, lib/agent-visuals.ts::getAgentLabel) —
// une clé personnalisée (nom libre, cf. add-credential-dialog.tsx) retombe
// sur un libellé humanisé automatique, jamais une erreur i18n.
const CREDENTIAL_KEY_LABEL_KEYS: Record<string, string> = {
  GROQ_API_KEY: "keyLabel_GROQ_API_KEY",
  OPENAI_API_KEY: "keyLabel_OPENAI_API_KEY",
  GOOGLE_API_KEY: "keyLabel_GOOGLE_API_KEY",
  GOOGLE_API_KEY_2: "keyLabel_GOOGLE_API_KEY_2",
  GOOGLE_API_KEY_3: "keyLabel_GOOGLE_API_KEY_3",
  GOOGLE_API_KEY_4: "keyLabel_GOOGLE_API_KEY_4",
  OPENROUTER_API_KEY: "keyLabel_OPENROUTER_API_KEY",
  ANTHROPIC_API_KEY: "keyLabel_ANTHROPIC_API_KEY",
  MISTRAL_API_KEY: "keyLabel_MISTRAL_API_KEY",
  LANGFUSE_SECRET_KEY: "keyLabel_LANGFUSE_SECRET_KEY",
  LANGFUSE_PUBLIC_KEY: "keyLabel_LANGFUSE_PUBLIC_KEY",
  LANGFUSE_BASE_URL: "keyLabel_LANGFUSE_BASE_URL",
};

function getCredentialLabel(key: string, t: (key: string) => string): string {
  const translationKey = CREDENTIAL_KEY_LABEL_KEYS[key];
  if (translationKey) return t(translationKey);
  return key
    .replace(/_/g, " ")
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function makeProviderCredentialsColumns(options: {
  t: (key: string) => string;
  onEdit: (credential: ProviderCredentialRead) => void;
  onClear: (credential: ProviderCredentialRead) => void;
}): ColumnDef<DataTableFeatures, ProviderCredentialRead>[] {
  const { t } = options;

  return [
    {
      id: "search",
      accessorFn: (row) => row.key,
      filterFn: "includesString",
      enableHiding: true,
    },
    {
      accessorKey: "key",
      header: t("columnKey"),
      cell: ({ row }) => (
        <div className="flex items-center gap-1.5">
          <span className="text-base font-bold text-slate-900 dark:text-zinc-100">
            {getCredentialLabel(row.original.key, t)}
          </span>
          {row.original.is_wired ? <StatusBadge tone="info" status={t("wiredBadge")} /> : null}
        </div>
      ),
    },
    {
      accessorKey: "source",
      header: t("columnStatus"),
      cell: ({ row }) => {
        const source = row.original.source;
        const tone = source === "database" ? "success" : source === "environment" ? "neutral" : "warning";
        return <StatusBadge tone={tone} status={t(`source_${source}`)} />;
      },
    },
    {
      accessorKey: "updated_at",
      header: t("columnUpdatedAt"),
      cell: ({ row }) =>
        row.original.updated_at ? (
          <span className="text-base font-semibold text-success">
            {new Date(row.original.updated_at).toLocaleString()}
          </span>
        ) : (
          <span className="text-muted-foreground text-base">—</span>
        ),
    },
    {
      id: "actions",
      header: () => <div className="text-right">{t("columnActions")}</div>,
      cell: ({ row }) => (
        <div className="flex justify-end gap-1.5">
          <Button
            size="sm"
            variant="skew"
            className="h-8 px-3 text-base font-semibold tracking-wide"
            onClick={() => options.onEdit(row.original)}
          >
            {t("editAction")}
          </Button>
          {row.original.source === "database" ? (
            <Button
              size="sm"
              variant="outline"
              className="border-danger/20 text-danger hover:bg-danger/10"
              onClick={() => options.onClear(row.original)}
            >
              {t("clearAction")}
            </Button>
          ) : null}
        </div>
      ),
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
