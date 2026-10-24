"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Edit3 } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { updateQuestionStatement, type ExerciseRead, type QuestionRead } from "@/lib/professor-api";
import {
  formCancelBtnCn,
  formErrorCn,
  formLabelCn,
  formSubmitBtnCn,
} from "../../../_components/form-styles";

export function EditQuestionDialog({
  exercise,
  question,
  open,
  onOpenChange,
  onUpdated,
}: {
  exercise: ExerciseRead;
  question: QuestionRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (exercise: ExerciseRead) => void;
}) {
  const t = useTranslations("EditQuestionDialog");
  const [statement, setStatement] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (question) {
      setStatement(question.statement);
      setError(null);
    }
  }, [question]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question) return;
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const updated = await updateQuestionStatement(session.accessToken, exercise.id, question.id, statement);
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
      <DialogContent className="max-h-[85vh] overflow-y-auto p-0 sm:max-w-md">
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <Edit3 className="size-5" />
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
                <Field className="gap-2">
                  <FieldLabel htmlFor="edit-question-statement" className={formLabelCn}>
                    {t("statement")}
                  </FieldLabel>
                  <Textarea
                    id="edit-question-statement"
                    className="h-[45vh] max-h-[45vh] resize-none overflow-y-auto rounded-xl border-slate-200 bg-white text-sm text-slate-900 placeholder:text-slate-400 focus-visible:ring-primary/30 focus-visible:border-primary dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
                    value={statement}
                    onChange={(event) => setStatement(event.target.value)}
                    rows={4}
                    required
                  />
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
                  disabled={isSubmitting || !statement.trim()}
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
