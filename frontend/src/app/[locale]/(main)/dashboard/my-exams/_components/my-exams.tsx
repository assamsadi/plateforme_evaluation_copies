"use client";
import * as React from "react";

import {
  type ColumnFiltersState,
  type ColumnVisibilityState,
  type PaginationState,
  type SortingState,
  useTable,
} from "@tanstack/react-table";
import { FileEdit } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { useRouter } from "@/i18n/navigation";
import { dataTableFeatures } from "@/lib/data-table-features";
import type { AssignedExerciseRead, SubmissionRead } from "@/lib/student-api";

import { DataTable } from "../../_components/data-table";
import { makeMyExamsColumns } from "./my-exams-columns";

export interface ExamRow {
  exercise: AssignedExerciseRead;
  submission: SubmissionRead | null;
}

export function MyExams({
  rows,
  onSubmit,
  onViewSubmission,
}: {
  rows: ExamRow[];
  onSubmit: (exercise: AssignedExerciseRead) => void;
  onViewSubmission: (submission: SubmissionRead) => void;
}) {
  const t = useTranslations("MyExams");
  const locale = useLocale();
  const router = useRouter();

  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([]);
  const [columnVisibility, setColumnVisibility] = React.useState<ColumnVisibilityState>({});
  const [pagination, setPagination] = React.useState<PaginationState>({ pageIndex: 0, pageSize: 10 });
  const [searchQuery, setSearchQuery] = React.useState("");

  const filteredRows = React.useMemo(() => {
    if (!searchQuery.trim()) return rows;
    const lowerQuery = searchQuery.toLowerCase();
    return rows.filter((row) => {
      const searchStr = `${row.exercise.title} ${row.exercise.module_name} ${row.exercise.professor_full_name}`.toLowerCase();
      return searchStr.includes(lowerQuery);
    });
  }, [rows, searchQuery]);

  function handleRowAction(row: ExamRow) {
    const { submission } = row;
    if (!submission) return;
    // Bug réel corrigé (2026-09-06) : pending_arbitration/pending_evaluation
    // routaient vers la modale de détail (quasi vide tant que la copie n'est
    // pas encore notée) au lieu de /verify — une fois l'arbitrage professeur
    // résolu, le statut quitte pending_student_verification SANS que
    // l'étudiant ait jamais cliqué "Confirmer ma copie" (deux étapes
    // distinctes, cf. ExtractionService.confirm_submission). L'étudiant se
    // retrouvait alors dans une impasse : plus aucun moyen de revenir sur
    // l'écran de vérification pour confirmer et débloquer la notation.
    // /verify reste correct à afficher ici : il ne dépend jamais de
    // submission.status en interne, seulement des ExtractionCorrection
    // réelles de la soumission (déjà toutes résolues à ce stade).
    if (
      submission.status === "pending_student_verification" ||
      submission.status === "pending_arbitration" ||
      submission.status === "pending_evaluation"
    ) {
      router.push(`/dashboard/my-exams/${submission.id}/verify`);
    } else if (submission.status === "evaluated") {
      router.push(`/dashboard/my-exams/${submission.id}/results`);
    } else {
      onViewSubmission(submission);
    }
  }

  const columns = React.useMemo(
    () => makeMyExamsColumns({ t, locale, onSubmit, onRowAction: handleRowAction }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, locale, onSubmit],
  );

  const table = useTable({
    features: dataTableFeatures,
    data: filteredRows,
    columns,
    state: { sorting, columnFilters, columnVisibility, pagination },
    getRowId: (row) => row.exercise.id,
    autoResetPageIndex: false,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
  });

  return (
    <Card className="overflow-hidden">
      <div className="h-1 w-full bg-primary" />
      <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80 has-data-[slot=card-action]:grid-cols-1 md:has-data-[slot=card-action]:grid-cols-[1fr_auto]">
        <div className="flex items-center gap-2.5">
          <div className="flex size-8 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
            <FileEdit className="size-4" />
          </div>
          <div>
            <CardTitle className="text-base font-semibold leading-none text-slate-900 dark:text-zinc-100">
              {t("title")}
              <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                {rows.length}
              </span>
            </CardTitle>
            <CardDescription className="mt-0.5 text-xs">{t("description")}</CardDescription>
          </div>
        </div>
        <CardAction className="col-start-1 row-start-auto flex w-full flex-wrap justify-start gap-2 justify-self-stretch md:col-start-2 md:row-span-2 md:row-start-1 md:w-auto md:flex-nowrap md:justify-end md:justify-self-end md:self-center">
          <SearchInput
            className="w-full md:w-64"
            placeholder={t("searchPlaceholder")}
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value);
              table.setPageIndex(0);
            }}
          />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 px-0 pt-2">
        <DataTable table={table} emptyMessage={t("noResults")} />
      </CardContent>
    </Card>
  );
}
