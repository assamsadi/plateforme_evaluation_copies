"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Edit3 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DialogClose, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { updateCourseSemester, type CourseRead } from "@/lib/professor-api";

import { formCancelBtnCn, formErrorCn, formInputCn, formLabelCn, formSubmitBtnCn } from "../../_components/form-styles";

export function EditCourseDialog({
  course,
  open,
  onOpenChange,
  onUpdated,
}: {
  course: CourseRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (course: CourseRead) => void;
}) {
  const t = useTranslations("EditCourseDialog");
  const [semester, setSemester] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (course) {
      setSemester(course.semester);
      setError(null);
    }
  }, [course]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !course) return;

    setIsSubmitting(true);
    try {
      const updated = await updateCourseSemester(session.accessToken, course.id, semester);
      onUpdated(updated);
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <TrafficLightDialog
      open={open}
      onOpenChange={onOpenChange}
      contentClassName="sm:max-w-sm"
      footer={
        course ? (
          <>
            <DialogClose asChild>
              <Button type="button" variant="outline" className={formCancelBtnCn}>
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button type="submit" form="edit-course-form" disabled={isSubmitting || !semester.trim()} className={formSubmitBtnCn}>
              {isSubmitting ? t("submitting") : t("submit")}
            </Button>
          </>
        ) : undefined
      }
    >
      <>
        <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <Edit3 className="size-5" />
              </div>
              <div>
                <DialogTitle className="text-lg font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-sm font-medium text-slate-500 dark:text-zinc-400">{course?.module_name}</p>
              </div>
            </div>
          </DialogHeader>

          {course ? (
            <form id="edit-course-form" onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
              <FieldGroup className="gap-4">
                <div className="flex flex-col gap-1 rounded-xl border border-slate-200/80 bg-slate-50/80 p-4 text-sm leading-relaxed dark:border-zinc-800 dark:bg-zinc-800/40">
                  <span className="font-semibold text-slate-900 dark:text-zinc-100">{course.module_name}</span>
                  <span className="text-slate-600 dark:text-zinc-400">
                    {t("groupLabel")}: <span className="font-mono font-semibold text-slate-800 dark:text-zinc-200">{course.group_label}</span>
                  </span>
                </div>

                <Field className="gap-2">
                  <FieldLabel htmlFor="edit-course-semester" className={formLabelCn}>
                    {t("semester")}
                  </FieldLabel>
                  <Input
                    id="edit-course-semester"
                    value={semester}
                    onChange={(event) => setSemester(event.target.value)}
                    placeholder="Ex: S1, 2026-S2"
                    className={formInputCn}
                    required
                  />
                </Field>

                {error ? <div className={formErrorCn}>{error}</div> : null}
              </FieldGroup>
            </form>
          ) : null}
      </>
    </TrafficLightDialog>
  );
}
