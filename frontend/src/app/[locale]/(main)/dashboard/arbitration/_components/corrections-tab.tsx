"use client";

import * as React from "react";
import { useCallback, useEffect, useState } from "react";

import {
  type ColumnDef,
  type ColumnFiltersState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { Bot, CheckCircle2, ExternalLink, FileEdit, FileText, RefreshCw, User } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/ui/status-badge";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { dataTableFeatures, type DataTableFeatures } from "@/lib/data-table-features";
import {
  getStudentArbitrationHistory,
  listAllCorrectionArbitrations,
  type ArbitrationVerdict,
  type PendingCorrectionArbitrationRead,
} from "@/lib/professor-api";
import { cn } from "@/lib/utils";

import { DataTable } from "../../_components/data-table";
import { ResolveCorrectionDialog } from "./resolve-correction-dialog";

interface GroupedCorrection {
  student_id: string;
  student_full_name: string;
  latest_date: string;
  exercise_titles: string[];
  pendingCount: number;
  totalCount: number;
  corrections: PendingCorrectionArbitrationRead[];
}

export function CorrectionsTab() {
  const t = useTranslations("CorrectionsTab");
  const locale = useLocale();
  const [corrections, setCorrections] = useState<PendingCorrectionArbitrationRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [viewingStudentId, setViewingStudentId] = useState<string | null>(null);
  const [viewingStudentName, setViewingStudentName] = useState<string | null>(null);
  const [resolveTarget, setResolveTarget] = useState<PendingCorrectionArbitrationRead | null>(null);
  // Traçabilité réelle (2026-09-06, gap réel signalé) : listPendingCorrection
  // Arbitrations ne renvoie QUE les PENDING — une contestation tranchée y
  // disparaît immédiatement, sans laisser de trace consultable après un
  // rechargement de page. Le détail étudiant charge donc SÉPARÉMENT
  // l'historique COMPLET (pending + resolved, avec le vrai verdict persisté
  // en base) via getStudentArbitrationHistory, jamais un suivi local qui se
  // perdrait au refresh.
  const [studentHistory, setStudentHistory] = useState<PendingCorrectionArbitrationRead[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);

  const fetchCorrections = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const result = await listAllCorrectionArbitrations(session.accessToken);
      setCorrections(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchCorrections();
  }, [fetchCorrections]);

  const fetchStudentHistory = useCallback(async (studentId: string) => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoadingHistory(true);
    try {
      const result = await getStudentArbitrationHistory(session.accessToken, studentId);
      setStudentHistory(result);
    } catch (fetchError) {
      toast.error(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoadingHistory(false);
    }
  }, [t]);

  function handleViewStudent(studentId: string, studentName: string) {
    setViewingStudentId(studentId);
    setViewingStudentName(studentName);
    fetchStudentHistory(studentId);
  }

  async function handleResolved(resolved: PendingCorrectionArbitrationRead, _verdict: ArbitrationVerdict) {
    toast.success(t("resolveSuccess", { name: resolved.student_full_name }));
    // Rafraîchit les DEUX vues depuis le backend — jamais un patch local de
    // l'état : la file d'attente (compteurs) ET l'historique du détail
    // étudiant doivent refléter le verdict réellement persisté.
    await Promise.all([fetchCorrections(), fetchStudentHistory(resolved.student_id)]);
  }

  const groupedCorrections = React.useMemo(() => {
    const map = new Map<string, GroupedCorrection>();
    for (const c of corrections) {
      if (!map.has(c.student_id)) {
        map.set(c.student_id, {
          student_id: c.student_id,
          student_full_name: c.student_full_name,
          latest_date: c.created_at,
          exercise_titles: [],
          pendingCount: 0,
          totalCount: 0,
          corrections: [],
        });
      }
      const group = map.get(c.student_id)!;
      group.corrections.push(c);
      group.totalCount++;
      if (c.status === "pending") {
        group.pendingCount++;
      }
      if (new Date(c.created_at).getTime() > new Date(group.latest_date).getTime()) {
        group.latest_date = c.created_at;
      }
      if (!group.exercise_titles.includes(c.exercise_title)) {
        group.exercise_titles.push(c.exercise_title);
      }
    }
    return Array.from(map.values()).sort(
      (a, b) => new Date(b.latest_date).getTime() - new Date(a.latest_date).getTime()
    );
  }, [corrections]);

  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: 10 });

  const columns = React.useMemo<ColumnDef<DataTableFeatures, GroupedCorrection>[]>(
    () => [
      {
        accessorKey: "student_id",
        header: t("studentIdColumn"),
        cell: ({ row }) => (
          <span className="font-mono text-sm font-semibold text-slate-700 dark:text-zinc-300">
            {row.original.student_id}
          </span>
        ),
      },
      {
        accessorKey: "student_full_name",
        header: t("fullNameColumn"),
        cell: ({ row }) => (
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-bold text-slate-900 dark:text-zinc-100">{row.original.student_full_name}</span>
            <span className="text-xs font-medium text-slate-500 dark:text-zinc-400">
              {row.original.exercise_titles.join(", ")}
            </span>
          </div>
        ),
      },
      {
        id: "count",
        header: t("contestationsColumn"),
        cell: ({ row }) =>
          row.original.pendingCount > 0 ? (
            <span className="rounded-full bg-amber-100 px-2.5 py-1 text-xs font-bold text-amber-800 dark:bg-amber-900/50 dark:text-amber-400">
              {row.original.pendingCount}
            </span>
          ) : (
            <StatusBadge tone="success" status={t("allResolvedBadge")} className="text-xs font-semibold" />
          ),
      },
      {
        accessorKey: "latest_date",
        header: t("lastColumn"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap rounded-lg bg-slate-100 px-2.5 py-1 font-mono text-xs font-semibold text-slate-700 dark:bg-zinc-800 dark:text-zinc-300">
            {new Date(row.original.latest_date).toLocaleString(locale)}
          </span>
        ),
      },
      {
        id: "actions",
        header: () => <div className="text-right">{t("actionsColumn")}</div>,
        cell: ({ row }) => (
          <div className="flex justify-end">
            <Button
              size="sm"
              variant="skew"
              className="h-10 px-4 text-sm font-semibold tracking-wide"
              onClick={() => handleViewStudent(row.original.student_id, row.original.student_full_name)}
            >
              {t("viewAction")}
            </Button>
          </div>
        ),
        enableSorting: false,
      },
    ],
    [locale, t],
  );

  const table = useTable({
    features: dataTableFeatures,
    data: groupedCorrections,
    columns,
    state: { sorting, columnFilters, pagination },
    getRowId: (row) => row.student_id,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onPaginationChange: setPagination,
  });

  if (error) {
    return (
      <Alert variant="destructive" className="rounded-2xl">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  return (
    <>
      <Card className="overflow-hidden border-slate-200/90 shadow-2xs dark:border-zinc-800">
        <div className="h-1 w-full bg-primary" />
        
        <CardHeader className="border-b border-slate-100 pb-4 pt-4 dark:border-zinc-800">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <FileEdit className="size-4.5" />
              </div>
              <div>
                <CardTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">
                  {viewingStudentId ? t("contestationsOf", { name: viewingStudentName ?? "" }) : t("title")}
                  {!viewingStudentId && groupedCorrections.length > 0 && (
                    <StatusBadge
                      tone="warning"
                      status={t("pendingBadge", { count: groupedCorrections.reduce((sum, g) => sum + g.pendingCount, 0) })}
                      className="ml-2 text-xs"
                    />
                  )}
                </CardTitle>
                <CardDescription className="mt-1 text-sm font-medium">
                  {viewingStudentId ? t("studentIdLabel", { id: viewingStudentId }) : t("description")}
                </CardDescription>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {viewingStudentId && (
                <Button
                  size="sm"
                  variant="skew"
                  onClick={() => {
                    setViewingStudentId(null);
                    setViewingStudentName(null);
                    setStudentHistory([]);
                  }}
                  className="h-10 px-4 text-sm font-semibold tracking-wide"
                >
                  {t("backAction")}
                </Button>
              )}
              <Button
                size="sm"
                variant="skew"
                onClick={fetchCorrections}
                disabled={isLoading}
                className="h-10 px-4 text-sm font-semibold tracking-wide"
              >
                <RefreshCw className={cn("mr-1.5 size-3.5", isLoading && "animate-spin")} />
                {t("refreshAction")}
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="flex flex-col gap-4 p-0 pt-2 pb-2">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-center">
              <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</p>
            </div>
          ) : !viewingStudentId && groupedCorrections.length === 0 ? (
            <div className="m-5 flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/50 py-12 text-center dark:border-zinc-800 dark:bg-zinc-800/20">
              <div className="flex size-10 items-center justify-center rounded-full bg-success/10 text-success">
                <CheckCircle2 className="size-5" />
              </div>
              <p className="mt-2 text-sm font-bold text-slate-900 dark:text-zinc-100">{t("noPendingTitle")}</p>
              <p className="mt-0.5 text-xs font-medium text-slate-500 dark:text-zinc-400">{t("noResults")}</p>
            </div>
          ) : viewingStudentId ? (
            isLoadingHistory ? (
              <div className="flex items-center justify-center gap-2 py-12 text-center">
                <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</p>
              </div>
            ) : (
            <div className="flex flex-col gap-4 p-4">
              {/*
                Copie complète de l'étudiant — UNE SEULE FOIS en haut de la
                vue, jamais répétée par bloc contesté (bug réel signalé
                2026-09-06 : le document_url est identique pour tous les
                blocs d'une même soumission, l'afficher dans la boucle le
                dupliquait autant de fois qu'il y avait de contestations).
                Bandeau distinct, avant la liste des blocs à trancher.
              */}
              {studentHistory[0]?.document_url ? (
                <div className="flex flex-col gap-3 rounded-xl border border-emerald-200/70 bg-emerald-50/50 p-4 dark:border-emerald-900/40 dark:bg-emerald-950/20">
                  <div className="flex items-center gap-2">
                    <FileText className="size-4 text-emerald-700 dark:text-emerald-400" />
                    <p className="text-xs font-bold uppercase tracking-wider text-emerald-800 dark:text-emerald-400">
                      {t("fullCopyLabel")}
                    </p>
                  </div>
                  {studentHistory[0].document_url.endsWith(".pdf") ||
                  studentHistory[0].document_url.includes("application/pdf") ? (
                    <a
                      href={studentHistory[0].document_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2.5 text-sm font-semibold text-emerald-700 shadow-xs ring-1 ring-emerald-200 transition-all hover:bg-emerald-50 hover:text-emerald-800 dark:bg-zinc-900 dark:text-emerald-300 dark:ring-emerald-900/50 dark:hover:bg-zinc-800 w-fit"
                    >
                      <FileText className="size-4" />
                      {t("openPdfAction")}
                      <ExternalLink className="size-3.5 opacity-60" />
                    </a>
                  ) : (
                    <div className="overflow-hidden rounded-lg border border-emerald-200/50 bg-white dark:border-zinc-700 dark:bg-zinc-900">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={studentHistory[0].document_url}
                        alt=""
                        className="max-h-96 w-full object-contain"
                      />
                      <a
                        href={studentHistory[0].document_url}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-center justify-center gap-2 border-t border-emerald-100 py-2 text-xs font-semibold text-emerald-700 hover:bg-emerald-50 dark:border-zinc-700 dark:text-emerald-400 dark:hover:bg-zinc-800"
                      >
                        <ExternalLink className="size-3.5" />
                        {t("openFullscreenAction")}
                      </a>
                    </div>
                  )}
                </div>
              ) : null}

              {studentHistory.map((correction) => {
                const verdict = correction.verdict;
                return (
                <div
                  key={correction.arbitration_id}
                  className={cn(
                    "flex flex-col gap-3.5 rounded-xl border p-4.5 transition-colors",
                    verdict === "accepted"
                      ? "border-emerald-300/70 bg-emerald-50/40 dark:border-emerald-900/40 dark:bg-emerald-950/20"
                      : verdict === "rejected"
                        ? "border-slate-200/80 bg-slate-50/60 opacity-80 dark:border-zinc-800 dark:bg-zinc-900/40"
                        : "border-amber-300/80 bg-amber-50/60 hover:bg-amber-50/90 dark:border-amber-900/50 dark:bg-amber-950/30",
                  )}
                >
                  {/*
                    Titre d'exercice + ID étudiant retirés d'ici (2026-09-06,
                    signalé par l'utilisateur) : déjà affichés UNE SEULE FOIS
                    dans l'en-tête de la vue détail (juste au-dessus de cette
                    liste) — les répéter sur CHAQUE bloc était redondant,
                    même logique que le correctif "Copie complète de
                    l'étudiant" déjà fait plus haut sur ce même écran.
                  */}
                  <div className="flex justify-end">
                    <span className="whitespace-nowrap rounded-lg bg-slate-100 px-2.5 py-1 font-mono text-xs font-semibold text-slate-700 dark:bg-zinc-800 dark:text-zinc-300">
                      {new Date(correction.created_at).toLocaleString(locale)}
                    </span>
                  </div>

                  {correction.image_crop_url ? (
                    <div className="rounded-xl border border-slate-200/90 bg-white p-2.5 dark:border-zinc-700/60 dark:bg-zinc-900">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={correction.image_crop_url}
                        alt="Crop OCR"
                        className="w-full rounded-lg object-contain"
                      />
                    </div>
                  ) : null}

                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="flex flex-col gap-1.5 rounded-xl border border-sky-300/70 bg-sky-50/80 p-3.5 dark:border-sky-900/50 dark:bg-sky-950/40">
                      <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-sky-800 dark:text-sky-300">
                        <Bot className="size-4 text-sky-600 dark:text-sky-400" />
                        <span>{t("aiReading")}</span>
                      </div>
                      <p className="font-mono text-sm font-semibold text-slate-900 dark:text-zinc-100">{correction.prediction_ocr}</p>
                    </div>

                    {correction.contestation_type === "attachment" ? (
                      <div className="flex flex-col gap-1.5 rounded-xl border border-violet-300/70 bg-violet-50/80 p-3.5 dark:border-violet-900/50 dark:bg-violet-950/40">
                        <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-violet-800 dark:text-violet-300">
                          <User className="size-4 text-violet-600 dark:text-violet-400" />
                          <span>{t("studentClaimsAttachment")}</span>
                        </div>
                        <p className="font-mono text-sm font-semibold text-slate-900 dark:text-zinc-100">
                          {correction.claimed_question_order !== null
                            ? t("claimedQuestion", { order: correction.claimed_question_order })
                            : t("claimedQuestionUnknown")}
                        </p>
                      </div>
                    ) : correction.human_correction ? (
                      <div className="flex flex-col gap-1.5 rounded-xl border border-slate-200/90 bg-white p-3.5 dark:border-zinc-700/60 dark:bg-zinc-900">
                        <div className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-zinc-200">
                          <User className="size-4 text-slate-500" />
                          <span>{t("studentClaim")}</span>
                        </div>
                        <p className="font-mono text-sm font-semibold text-slate-900 dark:text-zinc-100">{correction.human_correction}</p>
                      </div>
                    ) : null}
                  </div>

                  <div className="flex justify-end border-t border-amber-200/60 pt-3 dark:border-zinc-800">
                    {verdict === "accepted" ? (
                      <StatusBadge tone="success" status={t("verdictAccepted")} className="text-xs font-semibold" />
                    ) : verdict === "rejected" ? (
                      <StatusBadge tone="neutral" status={t("verdictRejected")} className="text-xs font-semibold" />
                    ) : (
                      <Button
                        size="sm"
                        variant="skew"
                        className="h-10 px-4 text-sm font-semibold tracking-wide"
                        onClick={() => setResolveTarget(correction)}
                      >
                        {t("resolveAction")}
                      </Button>
                    )}
                  </div>
                </div>
                );
              })}
            </div>
            )
          ) : (
            <DataTable table={table} emptyMessage={t("noResults")} />
          )}
        </CardContent>
      </Card>

      <ResolveCorrectionDialog
        correction={resolveTarget}
        open={Boolean(resolveTarget)}
        onOpenChange={(open) => !open && setResolveTarget(null)}
        onResolved={handleResolved}
      />
    </>
  );
}
