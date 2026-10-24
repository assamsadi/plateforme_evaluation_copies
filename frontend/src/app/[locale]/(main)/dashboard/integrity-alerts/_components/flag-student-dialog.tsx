"use client";

import { type FormEvent, useEffect, useMemo, useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DialogClose, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import {
  flagStudentManually,
  listUsers,
  type IntegrityAlertRead,
  type ManualIntegrityTriggerType,
} from "@/lib/admin-api";
import { AuthApiError, getStoredSession, type UserPublic } from "@/lib/auth-api";
import { cn } from "@/lib/utils";

import {
  formCancelBtnCn,
  formErrorCn,
  formInputCn,
  formLabelCn,
  formSelectTriggerCn,
  formSubmitBtnCn,
  formTextareaCn,
} from "../../_components/form-styles";

const TRIGGER_TYPES: ManualIntegrityTriggerType[] = ["suspected_plagiarism", "suspicious_pattern", "manual_flag"];

export function FlagStudentDialog({
  open,
  onOpenChange,
  onFlagged,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFlagged: (alert: IntegrityAlertRead) => void;
}) {
  const t = useTranslations("FlagStudentDialog");
  const [students, setStudents] = useState<UserPublic[]>([]);
  const [search, setSearch] = useState("");
  const [studentId, setStudentId] = useState("");
  const [triggerType, setTriggerType] = useState<ManualIntegrityTriggerType>("manual_flag");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    const session = getStoredSession();
    if (!session) return;
    listUsers(session.accessToken, { role: "student", limit: 200 })
      .then((page) => setStudents(page.items))
      .catch(() => setStudents([]));
  }, [open]);

  useEffect(() => {
    if (open) {
      setSearch("");
      setStudentId("");
      setTriggerType("manual_flag");
      setReason("");
      setError(null);
    }
  }, [open]);

  const filteredStudents = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return students;
    return students.filter((student) => {
      const fullName = `${student.first_name} ${student.last_name} ${student.email}`.toLowerCase();
      return fullName.includes(query);
    });
  }, [students, search]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !studentId || !reason.trim()) return;

    setIsSubmitting(true);
    try {
      const alert = await flagStudentManually(session.accessToken, {
        student_id: studentId,
        trigger_type: triggerType,
        reason: reason.trim(),
      });
      onFlagged(alert);
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
      contentClassName="sm:max-w-3xl"
      bodyClassName="p-7"
      footer={
        <>
          <DialogClose asChild>
            <Button type="button" variant="outline" className={formCancelBtnCn}>
              {t("cancel")}
            </Button>
          </DialogClose>
          <Button
            type="submit"
            form="flag-student-form"
            disabled={isSubmitting || !studentId || !reason.trim()}
            className={formSubmitBtnCn}
          >
            {isSubmitting ? t("submitting") : t("submit")}
          </Button>
        </>
      }
    >
      <>
        <DialogHeader>
            <DialogTitle className="text-lg font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
          </DialogHeader>

          <form id="flag-student-form" onSubmit={handleSubmit} className="mt-5 flex flex-col gap-5">
            <FieldGroup className="gap-5">
              <Field className="gap-2">
                <FieldLabel htmlFor="flag-student-search" className={cn(formLabelCn, "text-base")}>
                  {t("studentLabel")}
                </FieldLabel>
                <Input
                  id="flag-student-search"
                  placeholder={t("searchPlaceholder")}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className={cn(formInputCn, "h-11 text-base")}
                />
                <Select value={studentId} onValueChange={setStudentId}>
                  <SelectTrigger className={cn(formSelectTriggerCn, "h-11 text-base")}>
                    <SelectValue placeholder={t("choose")} />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                    {filteredStudents.map((student) => (
                      <SelectItem key={student.id} value={student.id} className="text-base font-medium">
                        {student.first_name} {student.last_name} — {student.email}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              <Field className="gap-2">
                <FieldLabel htmlFor="flag-student-trigger" className={cn(formLabelCn, "text-base")}>
                  {t("triggerLabel")}
                </FieldLabel>
                <Select value={triggerType} onValueChange={(value) => setTriggerType(value as ManualIntegrityTriggerType)}>
                  <SelectTrigger id="flag-student-trigger" className={cn(formSelectTriggerCn, "h-11 text-base")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                    {TRIGGER_TYPES.map((value) => (
                      <SelectItem key={value} value={value} className="text-base font-medium">
                        {t(`trigger_${value}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>

              <Field className="gap-2">
                <FieldLabel htmlFor="flag-student-reason" className={cn(formLabelCn, "text-base")}>
                  {t("reasonLabel")}
                </FieldLabel>
                <Textarea
                  id="flag-student-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder={t("reasonPlaceholder")}
                  rows={4}
                  className={cn(formTextareaCn, "text-base")}
                />
              </Field>

              {error ? <div className={formErrorCn}>{error}</div> : null}
            </FieldGroup>
          </form>
      </>
    </TrafficLightDialog>
  );
}
