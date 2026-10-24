"use client";

import { useState } from "react";

import { Gavel } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { DialogClose, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { fileGradeAppeal, type EvaluationRead, type GradeAppealRead, type SubmissionRead } from "@/lib/student-api";

import {
  formCancelBtnCn,
  formLabelCn,
  formSelectTriggerCn,
  formSubmitBtnCn,
  formTextareaCn,
} from "../../_components/form-styles";

const WHOLE_COPY_VALUE = "__whole_copy__";

export function FileAppealDialog({
  submission,
  evaluations,
  open,
  onOpenChange,
  onFiled,
}: {
  submission: SubmissionRead | null;
  evaluations: EvaluationRead[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onFiled: (appeal: GradeAppealRead) => void;
}) {
  const t = useTranslations("FileAppealDialog");
  const [scope, setScope] = useState<string>(WHOLE_COPY_VALUE);
  const [reason, setReason] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit() {
    const session = getStoredSession();
    if (!session || !submission || !reason.trim()) return;
    setIsSubmitting(true);
    try {
      const appeal = await fileGradeAppeal(session.accessToken, {
        submission_id: submission.id,
        evaluation_id: scope === WHOLE_COPY_VALUE ? null : scope,
        reason: reason.trim(),
      });
      onFiled(appeal);
      toast.success(t("success"));
      setReason("");
      setScope(WHOLE_COPY_VALUE);
      onOpenChange(false);
    } catch (fileError) {
      toast.error(fileError instanceof AuthApiError ? fileError.message : t("error"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <TrafficLightDialog
      open={open}
      onOpenChange={onOpenChange}
      contentClassName="sm:max-w-lg"
      footer={
        <>
          <DialogClose asChild>
            <Button type="button" variant="outline" className={formCancelBtnCn} disabled={isSubmitting}>
              {t("cancel")}
            </Button>
          </DialogClose>
          <Button onClick={handleSubmit} disabled={isSubmitting || !reason.trim()} className={formSubmitBtnCn}>
            {isSubmitting ? t("submitting") : t("submit")}
          </Button>
        </>
      }
    >
      <DialogHeader className="gap-2">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
            <Gavel className="size-5" />
          </div>
          <DialogTitle className="text-lg font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
        </div>
      </DialogHeader>

      <div className="mt-5 flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label className={formLabelCn}>{t("scopeLabel")}</Label>
          <Select value={scope} onValueChange={setScope}>
            <SelectTrigger className={formSelectTriggerCn}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="rounded-xl border-slate-200 shadow-lg dark:border-zinc-700">
              <SelectItem value={WHOLE_COPY_VALUE} className="text-sm font-medium">
                {t("scopeWholeCopy")}
              </SelectItem>
              {[...evaluations]
                .sort((a, b) => a.question_order - b.question_order)
                .map((evaluation) => (
                  <SelectItem key={evaluation.id} value={evaluation.id} className="text-sm font-medium">
                    {t("scopeQuestion", { order: evaluation.question_order })}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="appeal-reason" className={formLabelCn}>
            {t("reasonLabel")}
          </Label>
          <Textarea
            id="appeal-reason"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t("reasonPlaceholder")}
            className={`min-h-28 ${formTextareaCn}`}
          />
        </div>
      </div>
    </TrafficLightDialog>
  );
}
