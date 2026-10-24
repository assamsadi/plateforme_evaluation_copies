"use client";

import { type FormEvent, useEffect, useState } from "react";

import { CalendarClock } from "lucide-react";
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
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { updateExerciseDeadline, type ExerciseRead } from "@/lib/professor-api";
import {
  formCancelBtnCn,
  formErrorCn,
  formInputCn,
  formLabelCn,
  formSubmitBtnCn,
} from "../../../_components/form-styles";

function toDatetimeLocalValue(iso: string): string {
  const date = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function EditDeadlineDialog({
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
  const t = useTranslations("EditDeadlineDialog");
  const [deadline, setDeadline] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDeadline(exercise.deadline ? toDatetimeLocalValue(exercise.deadline) : "");
    setError(null);
  }, [open, exercise.deadline]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !deadline) return;

    setIsSubmitting(true);
    try {
      const updated = await updateExerciseDeadline(session.accessToken, exercise.id, new Date(deadline).toISOString());
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
      <DialogContent className="overflow-hidden p-0 sm:max-w-sm">
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <CalendarClock className="size-5" />
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
                <FieldLabel htmlFor="edit-deadline" className={formLabelCn}>
                  {t("deadline")}
                </FieldLabel>
                <DateTimePicker
                  id="edit-deadline"
                  value={deadline}
                  onChange={setDeadline}
                  placeholder={t("deadline")}
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
                disabled={isSubmitting || !deadline}
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
