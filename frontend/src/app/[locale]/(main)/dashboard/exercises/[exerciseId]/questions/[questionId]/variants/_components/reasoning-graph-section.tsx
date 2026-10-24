"use client";

import { useEffect, useState } from "react";

import { Check, Pencil, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LatexInline } from "@/components/ui/latex-text";
import { Textarea } from "@/components/ui/textarea";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { getVariantReasoningGraph, type ReasoningStepRead, updateReasoningStep } from "@/lib/professor-api";

// Une carte par étape du graphe de raisonnement — même langage visuel que
// les cartes de sous-question C2PCT (écran de détail d'exercice).
export function ReasoningGraphSection({ variantId }: { variantId: string }) {
  const t = useTranslations("VariantsDialog");
  const [steps, setSteps] = useState<ReasoningStepRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  // Correction ciblée d'UNE étape (cf. mémoire de session) — distinct d'une
  // édition globale du contenu de la variante : un seul step_id ouvert à la
  // fois, jamais un formulaire par étape monté en permanence.
  const [editingStepId, setEditingStepId] = useState<string | null>(null);
  const [editDescription, setEditDescription] = useState("");
  const [editFormula, setEditFormula] = useState("");
  const [isSavingStep, setIsSavingStep] = useState(false);
  const [stepError, setStepError] = useState<string | null>(null);

  useEffect(() => {
    const session = getStoredSession();
    if (!session) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    getVariantReasoningGraph(session.accessToken, variantId)
      .then((result) => {
        if (!cancelled) setSteps(result);
      })
      .catch((fetchError) => {
        if (!cancelled) setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [variantId, t]);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-3 text-xs text-slate-500">
        <div className="size-3 animate-spin rounded-full border border-primary border-t-transparent" />
        {t("loading")}
      </div>
    );
  }
  if (error) return <p className="text-xs font-medium text-danger">{error}</p>;
  if (!steps || steps.length === 0) return <p className="text-xs text-slate-400">{t("noReasoningSteps")}</p>;

  function startEditing(step: ReasoningStepRead) {
    setEditingStepId(step.id);
    setEditDescription(step.description);
    setEditFormula(step.formula ?? "");
    setStepError(null);
  }

  function cancelEditing() {
    setEditingStepId(null);
    setStepError(null);
  }

  async function saveEditing(stepId: string) {
    const session = getStoredSession();
    if (!session) return;
    setStepError(null);
    setIsSavingStep(true);
    try {
      const updated = await updateReasoningStep(session.accessToken, stepId, {
        description: editDescription.trim(),
        formula: editFormula.trim() || null,
      });
      setSteps((prev) =>
        prev
          ? prev.map((s) =>
              s.id === stepId ? { ...s, description: updated.description, formula: updated.formula } : s,
            )
          : prev,
      );
      setEditingStepId(null);
    } catch (saveError) {
      setStepError(saveError instanceof AuthApiError ? saveError.message : t("genericError"));
    } finally {
      setIsSavingStep(false);
    }
  }

  return (
    <ol className="flex flex-col gap-2.5">
      {steps.map((step) => (
        <li
          key={step.id}
          className="flex gap-2.5 rounded-xl border border-slate-200/60 bg-white/80 p-3 text-xs dark:border-zinc-700/60 dark:bg-zinc-800/80"
        >
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
            {step.order}
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-zinc-500">
                {step.step_type}
              </span>
              <div className="flex items-center gap-1.5">
                {step.related_competency_code ? (
                  <Badge variant="secondary" className="text-xs">
                    {t(`competency_${step.related_competency_code}`)}
                  </Badge>
                ) : null}
                {editingStepId !== step.id ? (
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="size-6 text-slate-400 hover:text-primary"
                    onClick={() => startEditing(step)}
                  >
                    <Pencil className="size-3" />
                  </Button>
                ) : null}
              </div>
            </div>

            {editingStepId === step.id ? (
              <div className="flex flex-col gap-2">
                <Textarea
                  value={editDescription}
                  onChange={(event) => setEditDescription(event.target.value)}
                  rows={3}
                  className="min-h-16 text-sm leading-relaxed"
                />
                <Input
                  value={editFormula}
                  onChange={(event) => setEditFormula(event.target.value)}
                  placeholder={t("stepFormulaPlaceholder")}
                  className="h-8 font-mono text-xs"
                />
                {stepError ? <p className="text-xs font-medium text-danger">{stepError}</p> : null}
                <div className="flex justify-end gap-1.5">
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={cancelEditing}>
                    <X className="mr-1 size-3" />
                    {t("cancel")}
                  </Button>
                  <Button
                    size="sm"
                    className="h-7 text-xs"
                    disabled={isSavingStep}
                    onClick={() => saveEditing(step.id)}
                  >
                    <Check className="mr-1 size-3" />
                    {isSavingStep ? t("submitting") : t("saveStepAction")}
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <p className="text-sm text-slate-600 dark:text-zinc-400">{step.description}</p>
                {step.formula ? (
                  <LatexInline text={step.formula} className="text-[14px] font-semibold text-foreground" />
                ) : null}
              </>
            )}
            {step.concept_tags.length > 0 ? (
              <div className="mt-0.5 flex flex-wrap gap-1">
                {step.concept_tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-md bg-slate-100 px-1.5 py-0.5 text-xs font-medium text-slate-600 dark:bg-zinc-700 dark:text-zinc-300"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
