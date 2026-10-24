"use client";

import { useCallback, useEffect, useState } from "react";

import { History, RefreshCw } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import {
  DecisionDetailDialog,
  validationStatusTone,
} from "@/app/[locale]/(main)/dashboard/_components/decision-detail-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { getAgentLabel, getAgentVisual } from "@/lib/agent-visuals";
import type { AgentDecisionLogRead, CursorPage } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { cn } from "@/lib/utils";

// Journal de décisions IA — était un dialog, déplacé en page dédiée
// (demande explicite professeur) : une timeline de décisions peut être
// longue, une vraie page laisse la place de la lire sans la contrainte de
// hauteur d'un dialog.
export function DecisionLogsView({
  title,
  fetchLogs,
}: {
  title: string;
  fetchLogs: (accessToken: string) => Promise<CursorPage<AgentDecisionLogRead>>;
}) {
  const t = useTranslations("DecisionLogsDialog");
  const tAgents = useTranslations("AgentDecisions");
  const locale = useLocale();
  const [logs, setLogs] = useState<AgentDecisionLogRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailTarget, setDetailTarget] = useState<AgentDecisionLogRead | null>(null);

  const fetchLogsData = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const page = await fetchLogs(session.accessToken);
      setLogs(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [fetchLogs, t]);

  useEffect(() => {
    fetchLogsData();
  }, [fetchLogsData]);

  return (
    <>
      <Card className="overflow-hidden">
        <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <History className="size-5" />
              </div>
              <div>
                <CardTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{title}</CardTitle>
                <p className="mt-0.5 text-sm font-medium text-slate-500 dark:text-zinc-400">{logs.length} journalisation(s)</p>
              </div>
            </div>

            <Button
              size="sm"
              variant="skew"
              onClick={fetchLogsData}
              disabled={isLoading}
              className="h-8 px-3 text-sm font-semibold tracking-wide"
            >
              <RefreshCw className={cn("size-3.5", isLoading && "animate-spin")} />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="pt-5">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-12">
              <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</p>
            </div>
          ) : error ? (
            <div className="rounded-lg border border-danger/20 bg-danger/10 p-3 text-sm font-medium text-danger">{error}</div>
          ) : logs.length === 0 ? (
            <div className="rounded-xl border border-slate-100 bg-slate-50/60 py-8 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
              <p className="text-sm font-medium text-slate-400 dark:text-zinc-500">{t("empty")}</p>
            </div>
          ) : (
            <ol className="relative flex flex-col gap-4">
              {logs.map((log, index) => {
                const { icon: AgentIcon, tone } = getAgentVisual(log.agent_name);
                const isLast = index === logs.length - 1;
                return (
                  <li key={log.id} className="relative flex gap-3">
                    <div className="flex flex-col items-center">
                      <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-full", tone)}>
                        <AgentIcon className="size-4" />
                      </span>
                      {!isLast ? <span className="mt-1 w-px flex-1 bg-border" /> : null}
                    </div>
                    <button
                      type="button"
                      onClick={() => setDetailTarget(log)}
                      className="mb-1 flex min-w-0 flex-1 flex-col gap-1 rounded-lg border border-border bg-muted/40 p-3.5 text-left text-sm transition-colors hover:border-primary/30 hover:bg-primary/5"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-bold text-slate-800 dark:text-zinc-200">{getAgentLabel(log.agent_name, tAgents)}</span>
                        <StatusBadge
                          tone={validationStatusTone[log.professor_validation_status]}
                          status={t(`validation_${log.professor_validation_status}`)}
                        />
                      </div>
                      <p className="line-clamp-2 text-slate-600 dark:text-zinc-400">{log.justification}</p>
                      <span className="text-xs font-semibold text-success">{new Date(log.created_at).toLocaleString(locale)}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          )}
        </CardContent>
      </Card>

      <DecisionDetailDialog
        log={detailTarget}
        open={Boolean(detailTarget)}
        onOpenChange={(dialogOpen) => !dialogOpen && setDetailTarget(null)}
      />
    </>
  );
}
