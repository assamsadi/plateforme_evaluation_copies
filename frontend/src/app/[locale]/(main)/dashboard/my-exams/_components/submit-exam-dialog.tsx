"use client";

import { useState } from "react";

import { FileImage, FileText, UploadCloud, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { formatBytes, useFileUpload } from "@/hooks/use-file-upload";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  createSubmission,
  isAllowedSubmissionFile,
  type AssignedExerciseRead,
  type SubmissionRead,
} from "@/lib/student-api";
import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = "application/pdf,image/png,image/jpeg,image/webp,image/tiff";
const MAX_SIZE = 25 * 1024 * 1024;

export function SubmitExamDialog({
  exercise,
  open,
  onOpenChange,
  onSubmitted,
}: {
  exercise: AssignedExerciseRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmitted: (submission: SubmissionRead) => void;
}) {
  const t = useTranslations("SubmitExamDialog");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [{ files, isDragging, errors: uploadErrors }, { handleDragEnter, handleDragLeave, handleDragOver, handleDrop, openFileDialog, removeFile, clearFiles, getInputProps }] =
    useFileUpload({ multiple: false, accept: ACCEPTED_TYPES, maxSize: MAX_SIZE });

  const selectedFile = files[0]?.file instanceof File ? files[0].file : null;
  const isInvalidType = selectedFile ? !isAllowedSubmissionFile(selectedFile) : false;

  function reset() {
    clearFiles();
    setError(null);
    setIsSubmitting(false);
  }

  async function handleSubmit() {
    const session = getStoredSession();
    if (!session || !exercise || !selectedFile || isInvalidType) return;

    setError(null);
    setIsSubmitting(true);
    try {
      const submission = await createSubmission(session.accessToken, exercise.id, selectedFile);
      onSubmitted(submission);
      reset();
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="overflow-visible p-0 sm:max-w-2xl">
        <div className="h-1.5 w-full bg-emerald-600 rounded-t-2xl" />
        <div className="p-8">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-emerald-500/20 bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400">
                <UploadCloud className="size-5" />
              </div>
              <div>
                <DialogTitle className="text-lg font-bold text-slate-900 dark:text-zinc-100">
                  {t("title")}
                </DialogTitle>
                <p className="mt-0.5 text-xs font-medium text-slate-500 dark:text-zinc-400">{exercise?.title}</p>
              </div>
            </div>
          </DialogHeader>

          <div className="mt-5 flex flex-col gap-3">
            <div
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onClick={() => !selectedFile && openFileDialog()}
              className={cn(
                "relative flex min-h-48 flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed p-6 text-center transition-all",
                isDragging
                  ? "border-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20"
                  : "border-slate-200 hover:border-emerald-500/40 hover:bg-slate-50/60 dark:border-zinc-700 dark:hover:bg-zinc-800/40",
                !selectedFile && "cursor-pointer",
              )}
            >
              <input {...getInputProps()} disabled={isSubmitting} className="sr-only" />

              {selectedFile ? (
                <div className="flex w-full items-center gap-3 rounded-xl border border-slate-200 bg-white p-3.5 text-left shadow-xs dark:border-zinc-700 dark:bg-zinc-900">
                  <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border border-emerald-500/20 bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40 dark:text-emerald-400">
                    {selectedFile.type.startsWith("image/") ? <FileImage className="size-5" /> : <FileText className="size-5" />}
                  </div>
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <p className="truncate text-sm font-semibold text-slate-900 dark:text-zinc-100">{selectedFile.name}</p>
                    <p className="text-xs text-slate-500 dark:text-zinc-400">{formatBytes(selectedFile.size)}</p>
                  </div>
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    disabled={isSubmitting}
                    onClick={(event) => {
                      event.stopPropagation();
                      removeFile(files[0].id);
                    }}
                    aria-label={t("removeFile")}
                  >
                    <X className="size-4" />
                  </Button>
                </div>
              ) : (
                <>
                  <div className="flex size-16 shrink-0 items-center justify-center rounded-full border border-emerald-500/20 bg-emerald-50 text-emerald-600 shadow-inner dark:bg-emerald-950/40 dark:text-emerald-400">
                    <UploadCloud className="size-7" />
                  </div>
                  <div className="mt-1 flex flex-col gap-1">
                    <p className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("dropHint")}</p>
                    <p className="max-w-xs text-xs text-slate-400 dark:text-zinc-500">{t("hint")}</p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    className="mt-2 h-10 rounded-xl bg-emerald-600 px-6 text-sm font-semibold text-white shadow-xs hover:bg-emerald-700"
                    onClick={openFileDialog}
                  >
                    {t("browseAction")}
                  </Button>
                </>
              )}
            </div>

            {selectedFile ? <p className="text-xs text-slate-500 dark:text-zinc-400">{t("hint")}</p> : null}
            {isInvalidType ? <p className="text-destructive text-xs font-medium">{t("invalidFileType")}</p> : null}
            {uploadErrors.length > 0 ? <p className="text-destructive text-xs font-medium">{uploadErrors[0]}</p> : null}
            {error ? <p className="text-destructive text-xs font-medium">{error}</p> : null}
          </div>

          <DialogFooter className="mt-6 mx-0 mb-0 flex-row justify-end gap-3 border-t-0 bg-transparent p-0">
            <Button
              type="button"
              variant="outline"
              className="h-10 rounded-xl border-slate-200 px-5 text-sm font-semibold text-slate-700 hover:bg-slate-100 hover:text-slate-900 dark:border-zinc-700 dark:text-zinc-300"
              onClick={() => onOpenChange(false)}
            >
              {t("cancel")}
            </Button>
            <Button
              type="button"
              disabled={!selectedFile || isInvalidType || isSubmitting}
              className="h-10 rounded-xl bg-emerald-600 px-6 text-sm font-bold text-white shadow-md shadow-emerald-600/20 hover:bg-emerald-700 disabled:opacity-50"
              onClick={handleSubmit}
            >
              {isSubmitting ? t("submitting") : t("submit")}
            </Button>
          </DialogFooter>
        </div>
      </DialogContent>
    </Dialog>
  );
}
