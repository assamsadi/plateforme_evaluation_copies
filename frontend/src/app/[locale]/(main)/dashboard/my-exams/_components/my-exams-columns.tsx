"use client";
import type { ColumnDef } from "@tanstack/react-table";
import { CalendarClock, CheckCircle2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import type { DataTableFeatures } from "@/lib/data-table-features";
import type { AssignedExerciseRead, SubmissionStatus } from "@/lib/student-api";

import type { ExamRow } from "./my-exams";

const submissionStatusTone: Record<SubmissionStatus, StatusTone> = {
  pending_ocr: "neutral",
  pending_student_verification: "warning",
  pending_arbitration: "warning",
  pending_evaluation: "info",
  evaluated: "success",
  absent: "danger",
};

export function makeMyExamsColumns(options: {
  t: (key: string, values?: Record<string, string | number>) => string;
  locale: string;
  onSubmit: (exercise: AssignedExerciseRead) => void;
  onRowAction: (row: ExamRow) => void;
}): ColumnDef<DataTableFeatures, ExamRow>[] {
  const { t, locale, onSubmit, onRowAction } = options;

  return [
    {
      accessorKey: "exercise.title",
      header: t("columnExercise"),
      cell: ({ row }) => (
        <div className="flex flex-col gap-0.5">
          <span className="font-semibold text-slate-900 text-base dark:text-zinc-100">
            {row.original.exercise.title}
          </span>
          <span className="text-sm font-medium text-slate-500 dark:text-zinc-400">
            {row.original.exercise.module_name} — {row.original.exercise.professor_full_name}
          </span>
        </div>
      ),
    },
    {
      id: "deadline",
      accessorFn: (row) => row.exercise.deadline ?? "",
      header: t("columnDeadline"),
      cell: ({ row }) =>
        row.original.exercise.deadline ? (
          <span className="flex items-center gap-1.5 text-base font-semibold text-emerald-600 dark:text-emerald-400">
            <CalendarClock className="size-3.5 text-emerald-600 dark:text-emerald-400" />
            {new Date(row.original.exercise.deadline).toLocaleString(locale)}
          </span>
        ) : (
          <span className="text-base font-medium text-slate-400 dark:text-zinc-500">{t("noDeadline")}</span>
        ),
    },
    {
      id: "statusDisplay",
      header: t("columnStatus"),
      cell: ({ row }) => {
        const { submission } = row.original;
        if (!submission) {
          return <span className="text-base font-medium text-slate-400 dark:text-zinc-500">{t("noSubmission")}</span>;
        }
        return (
          <StatusBadge
            tone={submissionStatusTone[submission.status]}
            className="text-sm"
            status={
              <>
                {submission.status === "evaluated" ? <CheckCircle2 className="mr-1 size-3.5" /> : null}
                {t(`submissionStatus_${submission.status}`)}
              </>
            }
          />
        );
      },
      enableSorting: false,
    },
    {
      id: "actions",
      header: () => (
        <div className="text-center text-sm font-bold text-slate-700 uppercase tracking-wider dark:text-zinc-300">
          {t("columnActions")}
        </div>
      ),
      cell: ({ row }) => (
        <div className="flex justify-center gap-2">
          {row.original.submission ? (
            <Button
              size="sm"
              variant="skew"
              className="h-8 px-3 text-base font-semibold tracking-wide"
              onClick={() => onRowAction(row.original)}
            >
              {t("viewAction")}
            </Button>
          ) : (
            <Button
              size="sm"
              variant="skew"
              className="h-8 px-3 text-base font-semibold tracking-wide"
              onClick={() => onSubmit(row.original.exercise)}
            >
              {t("submitAction")}
            </Button>
          )}
        </div>
      ),
      enableHiding: false,
      enableSorting: false,
    },
  ];
}
