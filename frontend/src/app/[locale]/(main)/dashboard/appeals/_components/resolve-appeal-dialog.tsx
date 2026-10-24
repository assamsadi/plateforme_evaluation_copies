"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Scale } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DialogClose, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { type AppealResolution, type GradeAppealRead, resolveGradeAppeal } from "@/lib/professor-api";
import { cn } from "@/lib/utils";

import {
  formCancelBtnCn,
  formErrorCn,
  formLabelCn,
  formSelectTriggerCn,
  formSubmitBtnCn,
  formTextareaCn,
} from "../../_components/form-styles";
import { resolutionValues } from "./data";

export function ResolveAppealDialog({
  appeal,
  open,
  onOpenChange,
  onResolved,
}: {
  appeal: GradeAppealRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResolved: (appeal: GradeAppealRead) => void;
}) {
  const t = useTranslations("ResolveAppealDialog");
  const [resolution, setResolution] = useState<AppealResolution>("grade_upheld");
  const [revisedScore, setRevisedScore] = useState("");
  const [reviewComment, setReviewComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (appeal) {
      setResolution("grade_upheld");
      setRevisedScore("");
      setReviewComment("");
      setError(null);
    }
  }, [appeal]);

  const requiresRevisedScore = resolution !== "grade_upheld";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !appeal) return;

    setIsSubmitting(true);
    try {
      const updated = await resolveGradeAppeal(session.accessToken, appeal.id, {
        resolution,
        review_comment: reviewComment || null,
        revised_score: requiresRevisedScore && revisedScore ? Number(revisedScore) : null,
      });
      onResolved(updated);
      onOpenChange(false);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  const canSubmit = !requiresRevisedScore || Boolean(revisedScore);

  return (
    <TrafficLightDialog
      open={open}
      onOpenChange={onOpenChange}
      // Élargi (demande explicite "Trancher la contestation" côté prof,
      // 2026-09-11) : sm:max-w-md (448px) était trop étroit pour un
      // formulaire à plusieurs champs — passe à sm:max-w-2xl, scopé à ce
      // seul dialog (TrafficLightDialog reste inchangé pour les ~5 autres
      // usages de ce composant partagé).
      contentClassName="sm:max-w-2xl"
      footer={
        appeal ? (
          <>
            <DialogClose asChild>
              <Button type="button" variant="outline" className={cn(formCancelBtnCn, "h-11")}>
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button
              type="submit"
              form="resolve-appeal-form"
              disabled={isSubmitting || !canSubmit}
              className={cn(formSubmitBtnCn, "h-11")}
            >
              {isSubmitting ? t("submitting") : t("submit")}
            </Button>
          </>
        ) : undefined
      }
    >
      <>
        <DialogHeader className="gap-2">
          <div className="flex items-center gap-3.5">
            <div className="flex size-12 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
              <Scale className="size-6" />
            </div>
            <div>
              <DialogTitle className="text-xl font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
              <p className="mt-0.5 text-base font-medium text-slate-600 dark:text-zinc-400">
                {appeal?.student_full_name ?? "Recours de note"}
              </p>
            </div>
          </div>
        </DialogHeader>

        {appeal ? (
          <form id="resolve-appeal-form" onSubmit={handleSubmit} className="mt-6 flex flex-col gap-5">
            <FieldGroup className="gap-5">
              {/* Context block: student + reason */}
              <div className="flex flex-col gap-2.5 rounded-2xl border border-slate-200/80 bg-slate-50/80 p-5 text-base leading-relaxed dark:border-zinc-800 dark:bg-zinc-800/40">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-slate-900 dark:text-zinc-100">{appeal.student_full_name}</span>
                  <span className="font-mono font-bold text-slate-700 dark:text-zinc-300">
                    {t("originalScore")}: {appeal.original_score}
                  </span>
                </div>
                <p className="text-slate-600 italic dark:text-zinc-400">« {appeal.reason} »</p>
                {appeal.ai_reevaluation_score !== null ? (
                  <div className="mt-1 flex items-center justify-between rounded-lg border border-info/20 bg-info/10 px-3.5 py-2 text-base text-info">
                    <span className="font-medium">{t("aiReevaluation")}</span>
                    <span className="font-mono font-bold">{appeal.ai_reevaluation_score}</span>
                  </div>
                ) : null}
              </div>

              {/* Décision + Nouvelle note côte à côte : la largeur gagnée
                    par contentClassName ci-dessus servait à rien tant que ces
                    2 champs restaient empilés en pleine largeur chacun. */}
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <Field className="gap-2">
                  <FieldLabel htmlFor="resolve-appeal-resolution" className={formLabelCn}>
                    {t("resolution")}
                  </FieldLabel>
                  <Select value={resolution} onValueChange={(value) => setResolution(value as AppealResolution)}>
                    <SelectTrigger id="resolve-appeal-resolution" className={cn(formSelectTriggerCn, "h-11")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      {resolutionValues.map((value) => (
                        <SelectItem key={value} value={value} className="text-sm font-medium">
                          {t(`resolution_${value}`)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>

                {requiresRevisedScore ? (
                  <Field className="gap-2">
                    <FieldLabel htmlFor="resolve-appeal-score" className={formLabelCn}>
                      {t("revisedScore")}
                    </FieldLabel>
                    <Input
                      id="resolve-appeal-score"
                      type="number"
                      step="0.01"
                      value={revisedScore}
                      onChange={(event) => setRevisedScore(event.target.value)}
                      placeholder="Ex: 14.5"
                      className="h-11 w-full font-mono text-base font-bold"
                      required
                    />
                  </Field>
                ) : null}
              </div>

              <Field className="gap-2">
                <FieldLabel htmlFor="resolve-appeal-comment" className={formLabelCn}>
                  {t("reviewComment")}
                </FieldLabel>
                <Textarea
                  id="resolve-appeal-comment"
                  value={reviewComment}
                  onChange={(event) => setReviewComment(event.target.value)}
                  rows={4}
                  placeholder="Commentaire ou justification de la décision finale..."
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
