"use client";

import { type FormEvent, useEffect, useState } from "react";

import { CheckCircle2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DialogClose, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  resolveCorrectionArbitration,
  type ArbitrationVerdict,
  type PendingCorrectionArbitrationRead,
} from "@/lib/professor-api";

export function ResolveCorrectionDialog({
  correction,
  open,
  onOpenChange,
  onResolved,
}: {
  correction: PendingCorrectionArbitrationRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onResolved: (correction: PendingCorrectionArbitrationRead, verdict: ArbitrationVerdict) => void;
}) {
  const t = useTranslations("ResolveCorrectionDialog");
  const [verdict, setVerdict] = useState<ArbitrationVerdict>("accepted");
  const [claimedCorrection, setClaimedCorrection] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (correction) {
      setVerdict("accepted");
      setClaimedCorrection(correction.human_correction ?? "");
      setComment("");
      setError(null);
    }
  }, [correction]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const session = getStoredSession();
    if (!session || !correction) return;

    setIsSubmitting(true);
    try {
      await resolveCorrectionArbitration(session.accessToken, correction.extraction_correction_id, {
        verdict,
        comment: comment || null,
        claimed_correction: claimedCorrection || null,
      });
      onResolved(correction, verdict);
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
      contentClassName="sm:max-w-5xl"
      footer={
        correction ? (
          <>
            <DialogClose asChild>
              <Button type="button" variant="outline" className="h-9">
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button type="submit" form="resolve-correction-form" disabled={isSubmitting} className="h-9 px-4">
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
                <CheckCircle2 className="size-5" />
              </div>
              <div>
                <DialogTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-sm font-medium text-slate-600 dark:text-zinc-400">{correction?.student_full_name}</p>
              </div>
            </div>
          </DialogHeader>

          {correction ? (
            <form id="resolve-correction-form" onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
              <FieldGroup className="gap-4">
                <div className="flex flex-col gap-1 rounded-xl border border-slate-200/80 bg-slate-50/80 p-4 text-sm leading-relaxed dark:border-zinc-800 dark:bg-zinc-800/40">
                  <p className="font-semibold text-slate-900 dark:text-zinc-100">{correction.student_full_name}</p>
                  <p className="text-slate-500 dark:text-zinc-400">{correction.exercise_title}</p>
                </div>

                {correction.image_crop_url ? (
                  // Pleine largeur, même correctif que corrections-tab.tsx
                  // (cf. son commentaire) — crops larges et peu hauts,
                  // jamais plafonnés en hauteur.
                  // eslint-disable-next-line @next/next/no-img-element -- blob SAS URL, pas un asset local optimisable
                  <img
                    src={correction.image_crop_url}
                    alt=""
                    className="w-full rounded-xl border border-slate-200 object-contain shadow-2xs dark:border-zinc-700"
                  />
                ) : null}

                <div className="rounded-lg border border-info/20 bg-info/10 p-3 text-sm">
                  <p className="font-semibold text-info">{t("aiReading")}</p>
                  <p className="mt-1 font-mono text-slate-700 dark:text-zinc-300">{correction.prediction_ocr}</p>
                </div>

                {correction.contestation_type === "attachment" ? (
                  <div className="rounded-lg border border-violet-200 bg-violet-50 p-3 text-sm dark:border-violet-900/40 dark:bg-violet-950/20">
                    <p className="font-semibold text-violet-800 dark:text-violet-300">{t("studentClaimsAttachment")}</p>
                    <p className="mt-1 font-mono text-slate-700 dark:text-zinc-300">
                      {correction.claimed_question_order !== null
                        ? t("claimedQuestion", { order: correction.claimed_question_order })
                        : t("claimedQuestionUnknown")}
                    </p>
                  </div>
                ) : correction.human_correction ? (
                  <div className="rounded-lg border border-border bg-muted/50 p-3 text-sm">
                    <p className="font-semibold text-foreground">{t("studentClaim")}</p>
                    <p className="mt-1 font-mono text-slate-700 dark:text-zinc-300">{correction.human_correction}</p>
                  </div>
                ) : null}

                <Field className="gap-1.5">
                  <FieldLabel htmlFor="resolve-correction-verdict" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                    {t("verdict")}
                  </FieldLabel>
                  <Select value={verdict} onValueChange={(value) => setVerdict(value as ArbitrationVerdict)}>
                    <SelectTrigger id="resolve-correction-verdict" className="h-9 w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
                      <SelectItem value="accepted" className="text-sm font-medium">{t("verdict_accepted")}</SelectItem>
                      <SelectItem value="rejected" className="text-sm font-medium">{t("verdict_rejected")}</SelectItem>
                    </SelectContent>
                  </Select>
                </Field>

                {verdict === "accepted" && correction.contestation_type !== "attachment" ? (
                  <Field className="gap-1.5">
                  <FieldLabel htmlFor="resolve-correction-claimed" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                      {t("claimedCorrection")}
                    </FieldLabel>
                    <Textarea
                      id="resolve-correction-claimed"
                      value={claimedCorrection}
                      onChange={(event) => setClaimedCorrection(event.target.value)}
                      rows={2}
                      className="font-mono text-sm"
                    />
                  </Field>
                ) : null}
                {verdict === "accepted" && correction.contestation_type === "attachment" ? (
                  <div className="rounded-lg border border-info/20 bg-info/5 px-3.5 py-2.5 text-sm font-medium text-info">
                    {t("attachmentAcceptHint", {
                      order: correction.claimed_question_order ?? "?",
                    })}
                  </div>
                ) : null}

                <Field className="gap-1.5">
                  <FieldLabel htmlFor="resolve-correction-comment" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                    {t("comment")}
                  </FieldLabel>
                  <Textarea
                    id="resolve-correction-comment"
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    rows={2}
                    placeholder="Commentaire de décision..."
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
