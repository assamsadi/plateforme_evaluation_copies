"use client";

import { type FormEvent, useState } from "react";

import { Archive } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { archiveExerciseToLibrary, type ExerciseDifficulty, type ExerciseRead } from "@/lib/professor-api";

const difficultyValues: ExerciseDifficulty[] = ["facile", "intermediaire", "avance"];

export function ArchiveDialog({
  exercise,
  open,
  onOpenChange,
  onUpdated,
}: {
  exercise: ExerciseRead;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (exercise: ExerciseRead) => void;
}) {
  const t = useTranslations("ArchiveDialog");
  const [difficultyLevel, setDifficultyLevel] = useState<ExerciseDifficulty>("intermediaire");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const updated = await archiveExerciseToLibrary(session.accessToken, exercise.id, difficultyLevel);
      onUpdated(updated);
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0 sm:max-w-md">
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <Archive className="size-4" />
              </div>
              <div>
                <DialogTitle className="text-base font-semibold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-xs text-slate-500 dark:text-zinc-400">{exercise.title}</p>
              </div>
            </div>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
            <FieldGroup className="gap-4">
              <Field className="gap-1.5">
                <FieldLabel htmlFor="archive-difficulty" className="text-xs font-semibold">
                  {t("difficulty")}
                </FieldLabel>
                <Select value={difficultyLevel} onValueChange={(value) => setDifficultyLevel(value as ExerciseDifficulty)}>
                  <SelectTrigger id="archive-difficulty" className="h-9 w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                    {difficultyValues.map((value) => (
                      <SelectItem key={value} value={value} className="text-xs">
                        {t(`difficulty_${value}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              {error ? (
                <div className="rounded-lg border border-danger/20 bg-danger/10 px-3.5 py-2.5 text-xs font-medium text-danger">
                  {error}
                </div>
              ) : null}
            </FieldGroup>

            <DialogFooter className="mt-2 -mx-6 -mb-6 rounded-b-xl border-t bg-muted/50 p-4 sm:justify-end">
              <DialogClose asChild>
                <Button type="button" variant="outline" className="h-9">
                  {t("cancel")}
                </Button>
              </DialogClose>
              <Button
                type="submit"
                disabled={isSubmitting}
                className="h-9 px-4"
              >
                {isSubmitting ? t("submitting") : t("submit")}
              </Button>
            </DialogFooter>
          </form>
        </div>
      </DialogContent>
    </Dialog>
  );
}
