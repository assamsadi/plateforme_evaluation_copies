"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Calculator, Plus, Trash2 } from "lucide-react";
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
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { setQuestionBareme, type ExerciseRead, type QuestionRead } from "@/lib/professor-api";
import {
  formCancelBtnCn,
  formContextBlockCn,
  formErrorCn,
  formInputCn,
  formLabelCn,
  formSubmitBtnCn,
} from "../../../_components/form-styles";

interface CriterionInput {
  label: string;
  points: string;
}

export function EditBaremeDialog({
  exercise,
  question,
  open,
  onOpenChange,
  onUpdated,
}: {
  exercise: ExerciseRead;
  question: QuestionRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (exercise: ExerciseRead) => void;
}) {
  const t = useTranslations("EditBaremeDialog");
  const [points, setPoints] = useState("");
  const [criteria, setCriteria] = useState<CriterionInput[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (question) {
      setPoints(question.bareme ? String(question.bareme.points) : "");
      setCriteria(
        (question.bareme?.criteria ?? []).map((c) => ({
          label: c.label,
          points: String(c.points),
        })),
      );
      setError(null);
    }
  }, [question]);

  function addCriterion() {
    setCriteria((prev) => [...prev, { label: "", points: "" }]);
  }

  function removeCriterion(index: number) {
    setCriteria((prev) => prev.filter((_, i) => i !== index));
  }

  function updateCriterion(index: number, patch: Partial<CriterionInput>) {
    setCriteria((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question) return;
    setError(null);

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const updated = await setQuestionBareme(session.accessToken, exercise.id, question.id, {
        points: Number(points || 0),
        criteria: criteria
          .filter((c) => c.label.trim())
          .map((c) => ({ label: c.label, points: Number(c.points || 0) })),
      });
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
      <DialogContent className="max-h-[85vh] overflow-y-auto p-0 sm:max-w-lg">
        <div className="p-6">
          <DialogHeader className="gap-2">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <Calculator className="size-5" />
              </div>
              <div>
                <DialogTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
                <p className="mt-0.5 text-sm font-medium text-slate-600 dark:text-zinc-400">
                  {question ? `Question ${question.order}` : ""}
                </p>
              </div>
            </div>
          </DialogHeader>

          {question ? (
            <form onSubmit={handleSubmit} className="mt-5 flex flex-col gap-4">
              <FieldGroup className="gap-4">
                <div className={formContextBlockCn}>
                  <span className="font-bold text-slate-900 dark:text-zinc-100">Énoncé : </span>
                  {question.statement}
                </div>

                <Field className="gap-2">
                  <FieldLabel htmlFor="edit-bareme-points" className={formLabelCn}>
                    {t("points")} total
                  </FieldLabel>
                  <Input
                    id="edit-bareme-points"
                    type="number"
                    step="0.25"
                    value={points}
                    onChange={(event) => setPoints(event.target.value)}
                    placeholder="Ex: 5"
                    className="h-10 w-36 font-mono text-sm font-bold"
                    required
                  />
                </Field>

                <div className="flex flex-col gap-2.5">
                  <div className="flex items-center justify-between">
                    <FieldLabel className={formLabelCn}>{t("criteria")}</FieldLabel>
                    <span className="text-xs font-semibold text-slate-500 dark:text-zinc-400">
                      {criteria.length} critère{criteria.length > 1 ? "s" : ""}
                    </span>
                  </div>

                  <div className="space-y-2">
                    {criteria.map((criterion, index) => (
                      <div key={index} className="flex items-center gap-2 rounded-xl border border-slate-200/90 bg-slate-50/50 p-2.5 dark:border-zinc-800 dark:bg-zinc-800/30">
                        <Input
                          className="h-9 flex-1 rounded-lg border-slate-200 bg-white text-sm font-medium text-slate-900 placeholder:text-slate-400 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
                          placeholder={t("criterionLabel")}
                          value={criterion.label}
                          onChange={(event) => updateCriterion(index, { label: event.target.value })}
                        />
                        <Input
                          className="h-9 w-24 rounded-lg border-slate-200 bg-white font-mono text-sm font-bold text-slate-900 placeholder:text-slate-400 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
                          type="number"
                          step="0.25"
                          placeholder="Pts"
                          value={criterion.points}
                          onChange={(event) => updateCriterion(index, { points: event.target.value })}
                        />
                        <Button
                          type="button"
                          size="icon-sm"
                          variant="ghost"
                          className="size-9 text-slate-400 hover:bg-danger/10 hover:text-danger"
                          onClick={() => removeCriterion(index)}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </div>
                    ))}
                  </div>

                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={addCriterion}
                    className="h-9 w-full border-dashed text-sm font-semibold text-primary hover:bg-primary/5"
                  >
                    <Plus className="mr-1.5 size-4" /> {t("addCriterion")}
                  </Button>
                </div>

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
                  disabled={isSubmitting || !points}
                  className={formSubmitBtnCn}
                >
                  {isSubmitting ? t("submitting") : t("submit")}
                </Button>
              </DialogFooter>
            </form>
          ) : null}
        </div>
      </DialogContent>
    </Dialog>
  );
}
