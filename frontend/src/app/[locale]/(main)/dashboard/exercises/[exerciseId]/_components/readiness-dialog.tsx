"use client";

import { CheckCircle2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { PublicationReadinessRead } from "@/lib/professor-api";

export function ReadinessDialog({
  readiness,
  open,
  onOpenChange,
}: {
  readiness: PublicationReadinessRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("ReadinessDialog");
  const locale = useLocale();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] overflow-y-auto p-0 sm:max-w-lg">
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <CheckCircle2 className="size-4" />
              </div>
              <div>
                <DialogTitle className="text-base font-semibold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                {readiness ? (
                  <p className="mt-0.5 text-xs text-slate-500 dark:text-zinc-400">
                    {t("confirmedAt")}: {new Date(readiness.confirmed_at).toLocaleString(locale)}
                  </p>
                ) : null}
              </div>
            </div>
          </DialogHeader>

          {readiness ? (
            <div className="mt-5 flex flex-col gap-2.5">
              {readiness.questions
                .sort((a, b) => a.order - b.order)
                .map((question) => (
                  <div key={question.question_id} className="flex flex-col gap-1.5 rounded-xl border border-slate-100 bg-slate-50/60 p-3.5 text-sm dark:border-zinc-800 dark:bg-zinc-800/40">
                    <p className="font-semibold text-slate-900 dark:text-zinc-100">
                      Q{question.order}. {question.statement}
                    </p>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 dark:text-zinc-400">
                      <span className="font-medium text-success">
                        {t("bareme")}: {question.bareme_points} {t("points")}
                      </span>
                      {question.reference_variant_summary ? (
                        <span>
                          {t("referenceVariant")}: {question.reference_variant_summary}
                        </span>
                      ) : null}
                    </div>
                  </div>
                ))}
            </div>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
