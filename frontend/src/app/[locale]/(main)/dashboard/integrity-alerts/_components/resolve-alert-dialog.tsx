"use client";

import { type FormEvent, useEffect, useState } from "react";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DialogClose, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import {
  resolveIntegrityAlert,
  type IntegrityActionTaken,
  type IntegrityAlertRead,
  type IntegrityAlertStatus,
} from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { actionTakenValues, resolvableStatuses } from "./data";

import {
  formCancelBtnCn,
  formErrorCn,
  formLabelCn,
  formSelectTriggerCn,
  formSubmitBtnCn,
  formTextareaCn,
} from "../../_components/form-styles";

export function ResolveAlertDialog({
  alert,
  open,
  onOpenChange,
  onResolved,
}: {
  alert: IntegrityAlertRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResolved: (alert: IntegrityAlertRead) => void;
}) {
  const t = useTranslations("ResolveAlertDialog");
  const [status, setStatus] = useState<IntegrityAlertStatus>("confirmed");
  const [actionTaken, setActionTaken] = useState<IntegrityActionTaken | "">("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (alert) {
      setStatus("confirmed");
      setActionTaken("");
      setNotes("");
      setError(null);
    }
  }, [alert]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !alert) return;

    setIsSubmitting(true);
    try {
      const updated = await resolveIntegrityAlert(session.accessToken, alert.id, {
        status,
        action_taken: actionTaken || undefined,
        review_notes: notes || undefined,
      });
      onResolved(updated);
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
      contentClassName="sm:max-w-xl"
      footer={
        alert ? (
          <>
            <DialogClose asChild>
              <Button type="button" variant="outline" className={formCancelBtnCn}>
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button type="submit" form="resolve-alert-form" disabled={isSubmitting} className={formSubmitBtnCn}>
              {isSubmitting ? t("submitting") : t("submit")}
            </Button>
          </>
        ) : undefined
      }
    >
      <>
        <DialogHeader className="gap-2">
            <DialogTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
          </DialogHeader>

          {alert ? (
            <form id="resolve-alert-form" onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
              <FieldGroup className="gap-4">
                <div className="flex flex-col gap-1 rounded-xl border border-slate-200/80 bg-slate-50/80 p-4 text-sm leading-relaxed dark:border-zinc-800 dark:bg-zinc-800/40">
                  <p className="font-semibold text-slate-900 dark:text-zinc-100">{alert.student_full_name}</p>
                  <p className="text-slate-600 italic dark:text-zinc-400">« {alert.reason} »</p>
                </div>

                <Field className="gap-2">
                  <FieldLabel htmlFor="resolve-alert-status" className={formLabelCn}>
                    {t("status")}
                  </FieldLabel>
                  <Select value={status} onValueChange={(value) => setStatus(value as IntegrityAlertStatus)}>
                    <SelectTrigger id="resolve-alert-status" className={formSelectTriggerCn}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      {resolvableStatuses.map((value) => (
                        <SelectItem key={value} value={value} className="text-sm font-medium">
                          {t(`status_${value}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field className="gap-2">
                  <FieldLabel htmlFor="resolve-alert-action" className={formLabelCn}>
                    {t("actionTaken")}
                  </FieldLabel>
                  <Select
                    value={actionTaken}
                    onValueChange={(value) => setActionTaken(value as IntegrityActionTaken)}
                  >
                    <SelectTrigger id="resolve-alert-action" className={formSelectTriggerCn}>
                      <SelectValue placeholder={t("actionTakenNone")} />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      {actionTakenValues.map((value) => (
                        <SelectItem key={value} value={value} className="text-sm font-medium">
                          {t(`action_${value}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                <Field className="gap-2">
                  <FieldLabel htmlFor="resolve-alert-notes" className={formLabelCn}>
                    {t("notes")}
                  </FieldLabel>
                  <Textarea
                    id="resolve-alert-notes"
                    value={notes}
                    onChange={(event) => setNotes(event.target.value)}
                    rows={3}
                    placeholder="Notes de révision ou justification..."
                    className={formTextareaCn}
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
