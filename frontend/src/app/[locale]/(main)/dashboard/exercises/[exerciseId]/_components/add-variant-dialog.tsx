"use client";

import { type FormEvent, useEffect, useState } from "react";

import { FileCode } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { createSolutionVariant, type QuestionRead, type VariantDifficulty } from "@/lib/professor-api";
import {
  formCancelBtnCn,
  formContextBlockCn,
  formErrorCn,
  formLabelCn,
  formSelectTriggerCn,
  formSubmitBtnCn,
  formTextareaCn,
} from "../../../_components/form-styles";

const difficultyValues: VariantDifficulty[] = ["facile", "intermediaire", "avance"];

export function AddVariantDialog({
  question,
  open,
  onOpenChange,
  onCreated,
}: {
  question: QuestionRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}) {
  const t = useTranslations("AddVariantDialog");
  const [content, setContent] = useState("");
  const [difficultyLevel, setDifficultyLevel] = useState<VariantDifficulty>("intermediaire");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setContent("");
      setDifficultyLevel("intermediaire");
      setError(null);
    }
  }, [open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question) return;
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      await createSolutionVariant(session.accessToken, {
        question_id: question.id,
        content,
        source: "teacher_manual",
        difficulty_level: difficultyLevel,
        is_reference: false,
      });
      onCreated();
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto p-0 sm:max-w-lg">
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <FileCode className="size-5" />
              </div>
              <div>
                <DialogTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-sm font-medium text-slate-600 dark:text-zinc-400">
                  {question ? `Question ${question.order}` : ""}
                </p>
              </div>
            </div>
          </DialogHeader>

          {question ? (
            <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
              <FieldGroup className="gap-4">
                <div className={formContextBlockCn}>
                  <span className="font-bold text-slate-900 dark:text-zinc-100">Énoncé : </span>
                  {question.statement}
                </div>

                <Field className="gap-2">
                  <FieldLabel htmlFor="add-variant-content" className={formLabelCn}>
                    {t("content")}
                  </FieldLabel>
                  <Textarea
                    id="add-variant-content"
                    value={content}
                    onChange={(event) => setContent(event.target.value)}
                    rows={6}
                    placeholder="Rédigez la solution de référence ou les étapes de résolution..."
                    className={`font-mono ${formTextareaCn}`}
                    required
                  />
                </Field>

                <Field className="gap-2">
                  <FieldLabel htmlFor="add-variant-difficulty" className={formLabelCn}>
                    {t("difficulty")}
                  </FieldLabel>
                  <Select value={difficultyLevel} onValueChange={(value) => setDifficultyLevel(value as VariantDifficulty)}>
                    <SelectTrigger id="add-variant-difficulty" className={formSelectTriggerCn}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      {difficultyValues.map((value) => (
                        <SelectItem key={value} value={value} className="text-sm font-medium">
                          {t(`difficulty_${value}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                {error ? <div className={formErrorCn}>{error}</div> : null}
              </FieldGroup>

              <DialogFooter className="mt-2 -mx-6 -mb-6 rounded-b-xl border-t bg-muted/50 p-4 sm:justify-end gap-2">
                <DialogClose asChild>
                  <Button type="button" variant="outline" className={formCancelBtnCn}>
                    {t("cancel")}
                  </Button>
                </DialogClose>
                <Button
                  type="submit"
                  disabled={isSubmitting || !content.trim()}
                  className={formSubmitBtnCn}
                >
                  {isSubmitting ? t("submitting") : t("submit")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
