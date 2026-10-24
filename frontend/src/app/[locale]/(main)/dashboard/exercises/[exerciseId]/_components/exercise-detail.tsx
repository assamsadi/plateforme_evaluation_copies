"use client";

import { useState } from "react";

import {
  Archive,
  BookOpen,
  CalendarClock,
  CheckCheck,
  History,
  MoreVertical,
  Pencil,
  Rocket,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { DeleteConfirmDialog } from "@/app/[locale]/(main)/dashboard/_components/delete-confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { StatusBadge } from "@/components/ui/status-badge";
import { Link, useRouter } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  confirmPublicationReadiness,
  deleteExercise,
  deleteQuestion,
  type ExerciseRead,
  type PublicationReadinessRead,
  publishExercise,
  type QuestionRead,
} from "@/lib/professor-api";

import { statusTone } from "../../_components/data";
import { AddQuestionDialog } from "./add-question-dialog";
import { AddVariantDialog } from "./add-variant-dialog";
import { ArchiveDialog } from "./archive-dialog";
import { CorrectionBlocksPanel } from "./correction-blocks-panel";
import { EditBaremeDialog } from "./edit-bareme-dialog";
import { EditC2PCTBaremeDialog } from "./edit-c2pct-bareme-dialog";
import { EditDeadlineDialog } from "./edit-deadline-dialog";
import { EditQuestionDialog } from "./edit-question-dialog";
import { PublishDialog } from "./publish-dialog";
import { QuestionsList } from "./questions-list";
import { ReadinessDialog } from "./readiness-dialog";
import { SubmissionsPanel } from "./submissions-panel";

export function ExerciseDetail({
  exercise,
  onUpdated,
}: {
  exercise: ExerciseRead;
  onUpdated: (exercise: ExerciseRead) => void;
}) {
  const t = useTranslations("ExerciseDetail");
  const locale = useLocale();
  const router = useRouter();
  const [variantTarget, setVariantTarget] = useState<QuestionRead | null>(null);
  const [baremeTarget, setBaremeTarget] = useState<QuestionRead | null>(null);
  const [c2pctBaremeTarget, setC2PCTBaremeTarget] = useState<QuestionRead | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [editDeadlineOpen, setEditDeadlineOpen] = useState(false);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [revertToDraftOpen, setRevertToDraftOpen] = useState(false);
  const [isRevertingToDraft, setIsRevertingToDraft] = useState(false);
  const [addQuestionOpen, setAddQuestionOpen] = useState(false);
  const [editQuestionTarget, setEditQuestionTarget] = useState<QuestionRead | null>(null);
  const [deleteQuestionTarget, setDeleteQuestionTarget] = useState<QuestionRead | null>(null);
  const [isDeletingQuestion, setIsDeletingQuestion] = useState(false);
  const [readiness, setReadiness] = useState<PublicationReadinessRead | null>(null);
  const [readinessOpen, setReadinessOpen] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);

  async function handleConfirmReadiness() {
    const session = getStoredSession();
    if (!session) return;

    setIsConfirming(true);
    try {
      const result = await confirmPublicationReadiness(session.accessToken, exercise.id);
      setReadiness(result);
      setReadinessOpen(true);
    } catch (confirmError) {
      toast.error(confirmError instanceof AuthApiError ? confirmError.message : t("readinessError"));
    } finally {
      setIsConfirming(false);
    }
  }

  async function handleConfirmDelete() {
    const session = getStoredSession();
    if (!session) return;

    setIsDeleting(true);
    try {
      await deleteExercise(session.accessToken, exercise.id);
      toast.success(t("deleteSuccess", { title: exercise.title }));
      router.push("/dashboard/exercises");
    } catch (deleteError) {
      toast.error(deleteError instanceof AuthApiError ? deleteError.message : t("deleteError"));
      setIsDeleting(false);
    }
  }

  async function handleConfirmRevertToDraft() {
    const session = getStoredSession();
    if (!session) return;

    setIsRevertingToDraft(true);
    try {
      const updated = await publishExercise(session.accessToken, exercise.id, { status: "draft" });
      onUpdated(updated);
      setRevertToDraftOpen(false);
      toast.success(t("revertToDraftSuccess", { title: exercise.title }));
    } catch (revertError) {
      toast.error(revertError instanceof AuthApiError ? revertError.message : t("revertToDraftError"));
    } finally {
      setIsRevertingToDraft(false);
    }
  }

  async function handleConfirmDeleteQuestion() {
    const session = getStoredSession();
    const target = deleteQuestionTarget;
    if (!session || !target) return;

    setIsDeletingQuestion(true);
    try {
      const updated = await deleteQuestion(session.accessToken, exercise.id, target.id);
      onUpdated(updated);
      toast.success(t("questionDeletedSuccess"));
      setDeleteQuestionTarget(null);
    } catch (deleteError) {
      toast.error(deleteError instanceof AuthApiError ? deleteError.message : t("questionDeleteError"));
    } finally {
      setIsDeletingQuestion(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Exercise Header Card */}
      <Card className="overflow-hidden">
        <CardHeader className="border-b pt-4 pb-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <BookOpen className="size-5" />
              </div>
              <div>
                <div className="flex flex-wrap items-center gap-2.5">
                  <h1 className="font-serif text-lg font-bold text-slate-900 dark:text-zinc-100">{exercise.title}</h1>
                  <StatusBadge tone={statusTone[exercise.status]} status={t(`status_${exercise.status}`)} />
                </div>
                <p className="mt-0.5 text-sm font-medium text-slate-500 dark:text-zinc-400">{exercise.module_name}</p>
              </div>
            </div>

            <Button size="sm" variant="skew" className="h-10 px-4 text-base font-semibold tracking-wide" asChild>
              <Link href={`/dashboard/exercises/${exercise.id}/decision-logs`}>
                <History className="mr-1.5 size-3.5" />
                {t("decisionLogsAction")}
              </Link>
            </Button>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 pt-4">
          {exercise.description ? (
            <p className="max-w-prose text-sm font-medium italic leading-relaxed text-black dark:text-white">
              {exercise.description}
            </p>
          ) : null}

          {exercise.status === "draft" ? (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100/80 pt-3 dark:border-zinc-800">
              {/* Hiérarchie des actions : "Publier" seul en primaire (bg
                  forêt) — c'est l'action qui compte le plus dans cet état ;
                  "Confirmer la complétude"/"Archiver" en outline (actions
                  secondaires) ; "Supprimer" sort de la rangée, déplacé dans
                  ce menu ⋮ pour qu'une action destructive irréversible ne
                  soit jamais au même niveau visuel que les 3 autres. */}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="forest"
                  className="h-10 px-4 text-base font-semibold tracking-wide"
                  onClick={() => setPublishOpen(true)}
                >
                  <Rocket className="mr-1.5 size-3.5" />
                  {t("publishAction")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-10 px-4 text-base font-semibold tracking-wide"
                  disabled={isConfirming}
                  onClick={handleConfirmReadiness}
                >
                  <CheckCheck className="mr-1.5 size-3.5" />
                  {isConfirming ? t("submitting") : t("confirmReadinessAction")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-10 px-4 text-base font-semibold tracking-wide"
                  onClick={() => setArchiveOpen(true)}
                >
                  <Archive className="mr-1.5 size-3.5" />
                  {t("archiveAction")}
                </Button>
              </div>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="icon" variant="ghost" aria-label={t("moreActionsLabel")}>
                    <MoreVertical className="size-4" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    variant="destructive"
                    className="data-[variant=destructive]:text-coral data-[variant=destructive]:focus:bg-coral-bg data-[variant=destructive]:focus:text-coral data-[variant=destructive]:*:[svg]:text-coral dark:data-[variant=destructive]:focus:bg-coral/20"
                    onClick={() => setDeleteOpen(true)}
                  >
                    <Trash2 />
                    {t("deleteAction")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : null}

          {exercise.status === "published_as_exam" || exercise.status === "published_as_homework" ? (
            // Gap fermé (demande explicite professeur) : aucun moyen de
            // revoir/modifier la deadline d'un examen/devoir déjà publié
            // depuis cet écran — PublishDialog ne concerne que la
            // publication initiale (cf. EditDeadlineDialog, endpoint dédié
            // qui ne redemande jamais une confirmation de complétude).
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100/80 pt-3 dark:border-zinc-800">
              <div className="flex items-center gap-2 text-sm font-medium text-slate-600 dark:text-zinc-400">
                <CalendarClock className="size-3.5 text-slate-400 dark:text-zinc-500" />
                {exercise.deadline
                  ? t("deadlineLabel", { date: new Date(exercise.deadline).toLocaleString(locale) })
                  : t("noDeadline")}
              </div>
              <Button
                size="sm"
                variant="skew"
                className="h-10 px-4 text-base font-semibold tracking-wide"
                onClick={() => setEditDeadlineOpen(true)}
              >
                <Pencil className="mr-1.5 size-3.5" />
                {t("editDeadlineAction")}
              </Button>
            </div>
          ) : null}

          {exercise.status === "archived_in_library" ? (
            // Gap fermé (demande explicite professeur, 2026-09-07) : un
            // exercice de bibliothèque créé sans jamais passer par l'OCR
            // (aucune Question réelle, cf. constat du même jour) n'avait
            // aucun moyen d'y déposer un document pour lancer le pipeline —
            // upload_reference_document exige DRAFT (cf. son docstring).
            // Retour arrière déjà supporté sans restriction côté backend
            // (ExerciseService.publish, point 3 de son docstring module) :
            // pur câblage UI ici, aucune règle métier nouvelle.
            <div className="flex flex-wrap items-center gap-2 border-t border-slate-100/80 pt-3 dark:border-zinc-800">
              <Button
                size="sm"
                variant="skew"
                className="h-10 px-4 text-base font-semibold tracking-wide"
                onClick={() => setRevertToDraftOpen(true)}
              >
                <RotateCcw className="mr-1.5 size-3.5" />
                {t("revertToDraftAction")}
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <QuestionsList
        questions={exercise.questions}
        canEditStructure={exercise.status === "draft"}
        onAddVariant={setVariantTarget}
        onEditBareme={setBaremeTarget}
        onEditC2PCTBareme={setC2PCTBaremeTarget}
        onAddQuestion={() => setAddQuestionOpen(true)}
        onEditQuestion={setEditQuestionTarget}
        onDeleteQuestion={setDeleteQuestionTarget}
      />

      <CorrectionBlocksPanel exercise={exercise} />

      <SubmissionsPanel exercise={exercise} />

      <AddVariantDialog
        question={variantTarget}
        open={Boolean(variantTarget)}
        onOpenChange={(open) => !open && setVariantTarget(null)}
        onCreated={() => toast.success(t("variantCreatedSuccess"))}
      />

      <EditBaremeDialog
        exercise={exercise}
        question={baremeTarget}
        open={Boolean(baremeTarget)}
        onOpenChange={(open) => !open && setBaremeTarget(null)}
        onUpdated={(updated) => {
          onUpdated(updated);
          toast.success(t("baremeUpdatedSuccess"));
        }}
      />

      <EditC2PCTBaremeDialog
        exercise={exercise}
        question={c2pctBaremeTarget}
        open={Boolean(c2pctBaremeTarget)}
        onOpenChange={(open) => !open && setC2PCTBaremeTarget(null)}
        onUpdated={(updated) => {
          onUpdated(updated);
          toast.success(t("c2pctBaremeUpdatedSuccess"));
        }}
      />

      <EditDeadlineDialog
        exercise={exercise}
        open={editDeadlineOpen}
        onOpenChange={setEditDeadlineOpen}
        onUpdated={(updated) => {
          onUpdated(updated);
          toast.success(t("deadlineUpdatedSuccess"));
        }}
      />

      <PublishDialog
        exercise={exercise}
        open={publishOpen}
        onOpenChange={setPublishOpen}
        onUpdated={(updated) => {
          onUpdated(updated);
          toast.success(t("publishSuccess"));
        }}
      />

      <ArchiveDialog
        exercise={exercise}
        open={archiveOpen}
        onOpenChange={setArchiveOpen}
        onUpdated={(updated) => {
          onUpdated(updated);
          toast.success(t("archiveSuccess"));
        }}
      />

      <ReadinessDialog readiness={readiness} open={readinessOpen} onOpenChange={setReadinessOpen} />

      <DeleteConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t("deleteConfirmTitle")}
        description={t("deleteConfirmDescription", { title: exercise.title })}
        cancelLabel={t("cancel")}
        confirmLabel={t("deleteAction")}
        isPending={isDeleting}
        onConfirm={handleConfirmDelete}
      />

      <DeleteConfirmDialog
        open={revertToDraftOpen}
        onOpenChange={setRevertToDraftOpen}
        title={t("revertToDraftConfirmTitle")}
        description={t("revertToDraftConfirmDescription", { title: exercise.title })}
        cancelLabel={t("cancel")}
        confirmLabel={t("revertToDraftAction")}
        isPending={isRevertingToDraft}
        onConfirm={handleConfirmRevertToDraft}
      />

      <AddQuestionDialog
        exercise={exercise}
        open={addQuestionOpen}
        onOpenChange={setAddQuestionOpen}
        onUpdated={(updated) => {
          onUpdated(updated);
          toast.success(t("questionAddedSuccess"));
        }}
      />

      <EditQuestionDialog
        exercise={exercise}
        question={editQuestionTarget}
        open={Boolean(editQuestionTarget)}
        onOpenChange={(open) => !open && setEditQuestionTarget(null)}
        onUpdated={(updated) => {
          onUpdated(updated);
          toast.success(t("questionUpdatedSuccess"));
        }}
      />

      <DeleteConfirmDialog
        open={Boolean(deleteQuestionTarget)}
        onOpenChange={(open) => !open && setDeleteQuestionTarget(null)}
        title={t("deleteQuestionConfirmTitle")}
        description={t("deleteQuestionConfirmDescription")}
        cancelLabel={t("cancel")}
        confirmLabel={t("deleteQuestionAction")}
        isPending={isDeletingQuestion}
        onConfirm={handleConfirmDeleteQuestion}
      />
    </div>
  );
}
