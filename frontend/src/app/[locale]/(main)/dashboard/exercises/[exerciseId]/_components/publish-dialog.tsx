"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Rocket } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { listMyCourses, publishExercise, type CourseRead, type ExerciseRead } from "@/lib/professor-api";
import {
  formCancelBtnCn,
  formErrorCn,
  formInputCn,
  formLabelCn,
  formSelectTriggerCn,
  formSubmitBtnCn,
} from "../../../_components/form-styles";

export function PublishDialog({
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
  const t = useTranslations("PublishDialog");
  const [courses, setCourses] = useState<CourseRead[]>([]);
  const [status, setStatus] = useState<"published_as_exam" | "published_as_homework">("published_as_exam");
  const [courseId, setCourseId] = useState("");
  const [deadline, setDeadline] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setStatus("published_as_exam");
    setCourseId("");
    setDeadline("");
    setError(null);

    const session = getStoredSession();
    if (!session) return;
    listMyCourses(session.accessToken, { limit: 200 })
      .then((page) => setCourses(page.items.filter((c) => c.module_id === exercise.module_id)))
      .catch(() => setCourses([]));
  }, [open, exercise.module_id]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const updated = await publishExercise(session.accessToken, exercise.id, {
        status,
        course_id: courseId,
        deadline: new Date(deadline).toISOString(),
      });
      onUpdated(updated);
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  const canSubmit = Boolean(courseId && deadline);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-hidden p-0 sm:max-w-md">
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <Rocket className="size-5" />
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
                <FieldLabel htmlFor="publish-status" className={formLabelCn}>
                  {t("status")}
                </FieldLabel>
                <Select value={status} onValueChange={(value) => setStatus(value as typeof status)}>
                  <SelectTrigger id="publish-status" className={formSelectTriggerCn}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                    <SelectItem value="published_as_exam" className="text-sm font-medium">
                      {t("status_published_as_exam")}
                    </SelectItem>
                    <SelectItem value="published_as_homework" className="text-sm font-medium">
                      {t("status_published_as_homework")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </Field>

              <Field className="gap-2">
                <FieldLabel htmlFor="publish-course" className={formLabelCn}>
                  {t("course")}
                </FieldLabel>
                <Select value={courseId} onValueChange={setCourseId}>
                  <SelectTrigger id="publish-course" className={formSelectTriggerCn}>
                    <SelectValue placeholder={t("coursePlaceholder")} />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                    {courses.map((course) => (
                      <SelectItem key={course.id} value={course.id} className="text-sm font-medium">
                        {course.group_label} — {course.semester}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {courses.length === 0 ? (
                  <p className="text-sm font-medium text-warning">{t("noCourseHint")}</p>
                ) : null}
              </Field>

              <Field className="gap-2">
                <FieldLabel htmlFor="publish-deadline" className={formLabelCn}>
                  {t("deadline")}
                </FieldLabel>
                <DateTimePicker
                  id="publish-deadline"
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
                disabled={isSubmitting || !canSubmit}
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
