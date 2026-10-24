"use client";

import { type FormEvent, useEffect, useState } from "react";

import { AlertTriangle, Calendar } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DialogClose, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { DateTimePicker } from "@/components/ui/date-time-picker";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { resolveIncident, type IncidentResolution, type SubmissionIncidentRead } from "@/lib/professor-api";

import { incidentResolutionValues } from "./data";

export function ResolveIncidentDialog({
  incident,
  open,
  onOpenChange,
  onResolved,
}: {
  incident: SubmissionIncidentRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResolved: (incident: SubmissionIncidentRead) => void;
}) {
  const t = useTranslations("ResolveIncidentDialog");
  const [resolution, setResolution] = useState<IncidentResolution>("justified_absence");
  const [extendedDeadline, setExtendedDeadline] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (incident) {
      setResolution("justified_absence");
      setExtendedDeadline("");
      setComment("");
      setError(null);
    }
  }, [incident]);

  const requiresDeadline = resolution === "deadline_extended";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !incident) return;

    setIsSubmitting(true);
    try {
      await resolveIncident(session.accessToken, incident.id, {
        resolution,
        resolution_comment: comment || null,
        extended_deadline: requiresDeadline && extendedDeadline ? new Date(extendedDeadline).toISOString() : null,
      });
      onResolved(incident);
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  const canSubmit = !requiresDeadline || Boolean(extendedDeadline);

  return (
    <TrafficLightDialog
      open={open}
      onOpenChange={onOpenChange}
      contentClassName="sm:max-w-md"
      footer={
        incident ? (
          <>
            <DialogClose asChild>
              <Button
                type="button"
                variant="outline"
                className="h-10 rounded-xl border-slate-200 px-4 text-sm font-semibold text-slate-700 hover:border-slate-300 hover:bg-slate-50 dark:border-zinc-700 dark:text-zinc-300"
              >
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button
              type="submit"
              form="resolve-incident-form"
              disabled={isSubmitting || !canSubmit}
              className="h-10 rounded-xl bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-2xs hover:bg-primary/90 disabled:opacity-50"
            >
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
                <AlertTriangle className="size-5" />
              </div>
              <div>
                <DialogTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-sm font-medium text-slate-600 dark:text-zinc-400">{incident?.student_full_name}</p>
              </div>
            </div>
          </DialogHeader>

          {incident ? (
            <form id="resolve-incident-form" onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
              <FieldGroup className="gap-4">
                <div className="flex flex-col gap-1 rounded-xl border border-slate-100 bg-slate-50/80 p-3.5 text-sm leading-relaxed dark:border-zinc-800 dark:bg-zinc-800/40">
                  <p className="font-semibold text-slate-900 dark:text-zinc-100">{incident.student_full_name}</p>
                  <p className="text-slate-600 italic dark:text-zinc-400">« {incident.reason} »</p>
                </div>

                <Field className="gap-2">
                  <FieldLabel htmlFor="resolve-incident-resolution" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                    {t("resolution")}
                  </FieldLabel>
                  <Select value={resolution} onValueChange={(value) => setResolution(value as IncidentResolution)}>
                    <SelectTrigger id="resolve-incident-resolution" className="h-10 w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      {incidentResolutionValues.map((value) => (
                        <SelectItem key={value} value={value} className="text-sm font-medium">
                          {t(`resolution_${value}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                {requiresDeadline ? (
                  <Field className="gap-2">
                    <FieldLabel htmlFor="resolve-incident-deadline" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                      {t("extendedDeadline")}
                    </FieldLabel>
                    <DateTimePicker
                      id="resolve-incident-deadline"
                      value={extendedDeadline}
                      onChange={setExtendedDeadline}
                      placeholder={t("extendedDeadline")}
                    />
                  </Field>
                ) : null}

                <Field className="gap-2">
                  <FieldLabel htmlFor="resolve-incident-comment" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                    {t("comment")}
                  </FieldLabel>
                  <Textarea
                    id="resolve-incident-comment"
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    rows={3}
                    placeholder="Commentaire de résolution..."
                  />
                </Field>

                {error ? (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm font-semibold text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300">
                    {error}
                  </div>
                ) : null}
              </FieldGroup>
            </form>
          ) : null}
      </>
    </TrafficLightDialog>
  );
}
