"use client";

import { useCallback, useEffect, useState } from "react";

import { CheckCircle2, FileStack, FileUp, ImageIcon, Layers, Sigma, Type, UploadCloud } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { LatexText } from "@/components/ui/latex-text";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/ui/status-badge";
import { type FileWithPreview, useFileUpload } from "@/hooks/use-file-upload";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  type ExerciseRead,
  type ExtractionContentType,
  listExerciseCorrectionBlocks,
  type QuestionRead,
  resolveCorrectionBlocks,
  type TeacherCorrectionBlockRead,
  uploadExerciseReferenceDocument,
} from "@/lib/professor-api";
import { cn } from "@/lib/utils";

const ACCEPTED_REFERENCE_TYPES = "application/pdf,image/png,image/jpeg,image/webp,image/tiff";

const CONTENT_TYPE_VISUAL: Record<ExtractionContentType, { icon: typeof Type }> = {
  TEXT: { icon: Type },
  EQUATION: { icon: Sigma },
  DIAGRAM: { icon: ImageIcon },
  STRUCTURE: { icon: ImageIcon },
};

function BlockResolutionRow({
  block,
  questions,
  onResolved,
}: {
  block: TeacherCorrectionBlockRead;
  questions: QuestionRead[];
  onResolved: (block: TeacherCorrectionBlockRead) => void;
}) {
  const t = useTranslations("ExerciseDetail");
  const [questionId, setQuestionId] = useState("");
  const [justification, setJustification] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleResolve() {
    const session = getStoredSession();
    if (!session) return;

    setError(null);
    setIsSubmitting(true);
    try {
      const updated = await resolveCorrectionBlocks(session.accessToken, block.exercise_id, [
        { block_id: block.id, question_id: questionId || null, professor_resolution: justification },
      ]);
      const resolvedBlock = updated.find((b) => b.id === block.id);
      if (resolvedBlock) onResolved(resolvedBlock);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("blockResolveError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  const { icon: TypeIcon } = CONTENT_TYPE_VISUAL[block.content_type];

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-amber-300/80 bg-amber-50/70 p-4 dark:border-amber-800 dark:bg-amber-950/30">
      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-amber-800 dark:text-amber-300">
        <TypeIcon className="size-3.5" />
        {t(`contentType_${block.content_type}`)}
      </div>
      {block.is_low_ocr_confidence ? (
        <StatusBadge tone="warning" status={t("lowOcrConfidence")} className="w-fit text-xs" />
      ) : null}
      {block.raw_text ? (
        <LatexText
          text={block.raw_text}
          className="text-sm font-semibold leading-relaxed text-slate-900 dark:text-zinc-100"
        />
      ) : (
        <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("noRawText")}</p>
      )}
      {block.image_crop_url ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={block.image_crop_url} alt="" className="max-h-48 w-auto rounded-lg border object-contain" />
      ) : null}
      <div className="flex flex-wrap items-center gap-2.5">
        <Select value={questionId} onValueChange={setQuestionId}>
          <SelectTrigger className="h-9 w-60 text-sm">
            <SelectValue placeholder={t("selectQuestion")} />
          </SelectTrigger>
          <SelectContent>
            {[...questions]
              .sort((a, b) => a.order - b.order)
              .map((question) => (
                <SelectItem key={question.id} value={question.id} className="text-sm">
                  Q{question.order}. {question.statement.slice(0, 40)}
                </SelectItem>
              ))}
          </SelectContent>
        </Select>
        <Input
          className="h-9 min-w-48 flex-1 text-sm"
          placeholder={t("justificationPlaceholder")}
          value={justification}
          onChange={(event) => setJustification(event.target.value)}
        />
        <Button
          size="sm"
          className="h-9 bg-amber-600 px-3.5 text-sm font-semibold text-white hover:bg-amber-700"
          disabled={isSubmitting || !questionId || !justification}
          onClick={handleResolve}
        >
          {isSubmitting ? t("submitting") : t("resolveBlockAction")}
        </Button>
      </div>
      {error ? <p className="text-xs font-semibold text-danger">{error}</p> : null}
    </div>
  );
}

export function CorrectionBlocksPanel({ exercise }: { exercise: ExerciseRead }) {
  const t = useTranslations("ExerciseDetail");
  const [blocks, setBlocks] = useState<TeacherCorrectionBlockRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<{ name: string; at: Date } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchBlocks = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    try {
      const result = await listExerciseCorrectionBlocks(session.accessToken, exercise.id);
      setBlocks(result);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("blocksFetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [exercise, t]);

  useEffect(() => {
    fetchBlocks();
  }, [fetchBlocks]);

  async function handleUpload(file: File) {
    const session = getStoredSession();
    if (!session) return;

    setIsUploading(true);
    setUploadedFile(null);
    try {
      await uploadExerciseReferenceDocument(session.accessToken, exercise.id, file);
      toast.success(t("uploadSuccess"));
      setUploadedFile({ name: file.name, at: new Date() });
    } catch (uploadError) {
      toast.error(uploadError instanceof AuthApiError ? uploadError.message : t("uploadError"));
    } finally {
      setIsUploading(false);
    }
  }

  const [
    { isDragging },
    { handleDragEnter, handleDragLeave, handleDragOver, handleDrop, openFileDialog, clearFiles, getInputProps },
  ] = useFileUpload({
    multiple: false,
    accept: ACCEPTED_REFERENCE_TYPES,
    onFilesAdded: (added: FileWithPreview[]) => {
      const file = added[0]?.file;
      if (file instanceof File) handleUpload(file);
      clearFiles();
    },
  });

  function handleBlockResolved(resolved: TeacherCorrectionBlockRead) {
    setBlocks((prev) => prev.map((b) => (b.id === resolved.id ? resolved : b)));
    toast.success(t("blockResolveSuccess"));
  }

  const unresolved = blocks.filter((b) => b.evidence_level === "unresolved_no_label");
  const resolved = blocks.filter((b) => b.evidence_level !== "unresolved_no_label");

  return (
    <Card className="overflow-hidden border-slate-200/90 shadow-2xs dark:border-zinc-800">
      <CardHeader className="border-b border-slate-100 pb-4 pt-4 dark:border-zinc-800">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
            <Layers className="size-4.5" />
          </div>
          <div>
            <CardTitle className="font-serif text-base font-bold text-slate-900 dark:text-zinc-100">
              {t("blocksTitle")}
              {unresolved.length > 0 && (
                <StatusBadge tone="warning" status={t("unresolvedCountBadge", { count: unresolved.length })} className="ml-2 text-xs" />
              )}
            </CardTitle>
            <p className="mt-1 text-sm font-medium text-slate-500 dark:text-zinc-400">{t("blocksDescription")}</p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 pt-4">
        {exercise.status === "draft" ? (
          <div className="flex flex-col gap-2.5 rounded-xl border border-dashed border-slate-200 bg-slate-50/60 p-4 dark:border-zinc-700 dark:bg-zinc-800/30">
            <div className="flex items-center gap-2 text-sm font-bold text-slate-800 dark:text-zinc-200">
              <FileUp className="size-4 text-primary" />
              {t("uploadLabel")}
            </div>

            <div
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDragOver={handleDragOver}
              onDrop={handleDrop}
              onClick={() => !isUploading && openFileDialog()}
              className={cn(
                "relative flex min-h-40 flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed p-5 text-center transition-colors",
                // Drag-over (fichier survolant la zone, prêt à être déposé) :
                // état le plus marqué — bordure pleine forêt + fond teinté
                // nettement plus visible que le simple hover ci-dessous.
                isDragging
                  ? "border-forest-700 bg-forest-700/10 dark:border-forest-500 dark:bg-forest-500/10"
                  : "border-slate-200 hover:border-forest-500/50 hover:bg-forest-700/[0.03] dark:border-zinc-700 dark:hover:border-forest-500/40 dark:hover:bg-forest-500/[0.06]",
                isUploading ? "pointer-events-none opacity-60" : "cursor-pointer",
              )}
            >
              <input {...getInputProps()} disabled={isUploading} className="sr-only" />
              <div
                className={cn(
                  "flex size-12 shrink-0 items-center justify-center rounded-full border shadow-inner transition-colors",
                  isDragging
                    ? "border-forest-700/30 bg-forest-700/15 text-forest-700 dark:border-forest-500/30 dark:bg-forest-500/15 dark:text-forest-500"
                    : "border-primary/20 bg-primary/10 text-primary",
                )}
              >
                <UploadCloud className="size-5.5" />
              </div>
              <p className="mt-1 text-base font-bold text-slate-900 dark:text-zinc-100">{t("dropHint")}</p>
              <Button
                type="button"
                size="sm"
                variant="skew"
                className="mt-1 h-9 px-5 text-sm font-semibold tracking-wide"
                onClick={(e) => {
                  e.stopPropagation();
                  openFileDialog();
                }}
              >
                {t("browseAction")}
              </Button>
            </div>

            {isUploading ? (
              <div className="flex items-center gap-2 text-sm font-medium text-primary">
                <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                {t("uploadInProgress")}
              </div>
            ) : uploadedFile ? (
              <div className="flex items-center gap-2 rounded-lg border border-success/20 bg-success/5 px-3 py-2 text-sm font-semibold text-success">
                <CheckCircle2 className="size-4 shrink-0" />
                {t("uploadConfirmed", {
                  name: uploadedFile.name,
                  time: uploadedFile.at.toLocaleTimeString(),
                })}
              </div>
            ) : (
              <p className="text-xs font-medium text-slate-500 dark:text-zinc-400">{t("uploadHint")}</p>
            )}
          </div>
        ) : null}

        {isLoading ? (
          <div className="flex items-center gap-2 py-2">
            <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("blocksLoading")}</p>
          </div>
        ) : error ? (
          <p className="text-sm font-medium text-danger">{error}</p>
        ) : blocks.length === 0 ? (
          <EmptyState icon={FileStack} title={t("emptyBlocksTitle")} description={t("noBlocks")} />
        ) : (
          <>
            {unresolved.length > 0 ? (
              <div className="flex flex-col gap-2.5">
                <p className="text-xs font-bold uppercase tracking-wider text-amber-800 dark:text-amber-300">
                  {t("unresolvedBlocks", { count: unresolved.length })}
                </p>
                {unresolved.map((block) => (
                  <BlockResolutionRow
                    key={block.id}
                    block={block}
                    questions={exercise.questions}
                    onResolved={handleBlockResolved}
                  />
                ))}
              </div>
            ) : null}

            {resolved.length > 0 ? (
              <div className="flex flex-col gap-2.5">
                <p className="text-xs font-bold uppercase tracking-wider text-emerald-800 dark:text-emerald-300">
                  {t("resolvedBlocks", { count: resolved.length })}
                </p>
                {resolved.map((block) => {
                  const { icon: TypeIcon } = CONTENT_TYPE_VISUAL[block.content_type];
                  return (
                    <div
                      key={block.id}
                      className="flex flex-col gap-2.5 rounded-xl border border-emerald-200/80 bg-emerald-50/60 p-3.5 dark:border-emerald-900/50 dark:bg-emerald-950/30"
                    >
                      <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-emerald-800 dark:text-emerald-400">
                        <TypeIcon className="size-3.5" />
                        {t(`contentType_${block.content_type}`)}
                      </div>
                      {block.is_low_ocr_confidence ? (
                        <StatusBadge tone="warning" status={t("lowOcrConfidence")} className="w-fit text-xs" />
                      ) : null}
                      {block.raw_text ? (
                        <LatexText
                          text={block.raw_text}
                          className="text-sm font-semibold leading-relaxed text-slate-800 dark:text-zinc-200"
                        />
                      ) : (
                        <p className="text-sm text-muted-foreground">{t("noRawText")}</p>
                      )}
                      {block.image_crop_url ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={block.image_crop_url}
                          alt=""
                          className="max-h-48 w-auto rounded-lg border object-contain"
                        />
                      ) : null}
                      <p className="text-xs font-bold text-emerald-800 dark:text-emerald-400">
                        ✓ {t(`evidence_${block.evidence_level}`)}
                      </p>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
