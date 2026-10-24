"use client";

import { type FormEvent, useEffect, useState } from "react";

import { MessageSquarePlus } from "lucide-react";
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
import { addQuestion, type ExerciseRead } from "@/lib/professor-api";
import {
  formCancelBtnCn,
  formErrorCn,
  formLabelCn,
  formSubmitBtnCn,
  formTextareaCn,
} from "../../../_components/form-styles";

export function AddQuestionDialog({
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
  const t = useTranslations("AddQuestionDialog");
  const [statement, setStatement] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (open) {
      setStatement("");
      setError(null);
    }
  }, [open]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const updated = await addQuestion(session.accessToken, exercise.id, statement);
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
              <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <MessageSquarePlus className="size-5" />
              </div>
              <div>
                <DialogTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-sm font-medium text-slate-600 dark:text-zinc-400">{exercise.title}</p>
              </div>
            </div>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
            <FieldGroup className="gap-4">
              <Field className="gap-2">
                <FieldLabel htmlFor="add-question-statement" className={formLabelCn}>
                  {t("statement")}
                </FieldLabel>
                <Textarea
                  id="add-question-statement"
                  value={statement}
                  onChange={(event) => setStatement(event.target.value)}
                  rows={4}
                  placeholder="Ex: Calculer la dérivée de la fonction f(x) = ..."
                  className={formTextareaCn}
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
        </div>
      </DialogContent>
    </Dialog>
  );
}
