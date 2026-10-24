"use client";

import { useState } from "react";

import { Check, Edit2, GitBranch, Trash2, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LatexText } from "@/components/ui/latex-text";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { Textarea } from "@/components/ui/textarea";
import { SubquestionCard } from "@/app/[locale]/(main)/dashboard/exercises/[exerciseId]/_components/questions-list";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  reviewSolutionVariant,
  type SolutionVariantSummaryRead,
  type SubquestionRead,
  type VariantStatus,
} from "@/lib/professor-api";

import { ReasoningGraphSection } from "./reasoning-graph-section";

const statusTone: Record<VariantStatus, StatusTone> = {
  pending_validation: "warning",
  approved: "success",
  rejected: "danger",
};

// Une variante = une carte "Cahier structuré" : statut/provenance en tête,
// contenu rendu (LaTeX inclus), graphe de raisonnement en cartes numérotées
// (repli affiché sur demande), actions de revue en pied de carte — même
// densité/espacement que les cartes de sous-question de l'écran de détail
// d'exercice, jamais un bloc de texte compact empilé.
export function VariantPanel({
  variant,
  subquestions,
  onChanged,
  onDeleteRequested,
}: {
  variant: SolutionVariantSummaryRead;
  // Cartes par sous-question C2PCT (même composant que l'écran de détail
  // d'exercice) — n'a de sens QUE pour la référence : c'est le seul contenu
  // qui correspond 1:1 à Question.subquestions (une variante IA a son propre
  // texte libre, jamais découpé par sous-question officielle).
  subquestions?: SubquestionRead[] | null;
  onChanged: () => void;
  onDeleteRequested: (variant: SolutionVariantSummaryRead) => void;
}) {
  const t = useTranslations("VariantsDialog");
  const locale = useLocale();
  const [isEditing, setIsEditing] = useState(false);
  const [modifiedContent, setModifiedContent] = useState(variant.content);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showReasoning, setShowReasoning] = useState(false);
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);
  const [rejectComment, setRejectComment] = useState("");
  const [rejectMethodHint, setRejectMethodHint] = useState("");
  const [rejectConceptHint, setRejectConceptHint] = useState("");

  async function runAction(action: () => Promise<unknown>) {
    const session = getStoredSession();
    if (!session) return;
    setError(null);
    setIsSubmitting(true);
    try {
      await action();
      onChanged();
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleAccept() {
    const session = getStoredSession();
    if (!session) return;
    runAction(() => reviewSolutionVariant(session.accessToken, variant.id, { action: "ACCEPTED" }));
  }

  function handleReject() {
    setRejectComment("");
    setRejectMethodHint("");
    setRejectConceptHint("");
    setError(null);
    setRejectDialogOpen(true);
  }

  // Le rejet déclenche automatiquement une régénération côté backend (cf.
  // mémoire de session) — review_comment explique à l'agent pourquoi CETTE
  // variante a été rejetée (pour ne pas reproduire l'erreur), method_hint/
  // concept_hint pilotent optionnellement la nouvelle tentative, exactement
  // comme le formulaire de génération guidée.
  async function handleConfirmReject() {
    const session = getStoredSession();
    if (!session) return;
    await runAction(() =>
      reviewSolutionVariant(session.accessToken, variant.id, {
        action: "REJECTED",
        review_comment: rejectComment.trim() || undefined,
        method_hint: rejectMethodHint.trim() || undefined,
        concept_hint: rejectConceptHint.trim()
          ? rejectConceptHint
              .split(",")
              .map((concept) => concept.trim())
              .filter(Boolean)
          : undefined,
      }),
    );
    setRejectDialogOpen(false);
  }

  async function handleSubmitModification() {
    const session = getStoredSession();
    if (!session) return;
    await runAction(() =>
      reviewSolutionVariant(session.accessToken, variant.id, {
        action: "MODIFIED",
        modified_content: modifiedContent,
      }),
    );
    setIsEditing(false);
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="overflow-hidden">
        <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusBadge tone={statusTone[variant.status]} status={t(`status_${variant.status}`)} />
              {variant.is_reference ? <StatusBadge tone="info" status={t("referenceLabel")} /> : null}
              <span className="text-xs text-slate-400 dark:text-zinc-500">{t(`source_${variant.source}`)}</span>
            </div>
            <span className="text-xs text-slate-400 dark:text-zinc-500">
              {new Date(variant.created_at).toLocaleDateString(locale)}
            </span>
          </div>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 pt-4">
          {variant.reasoning_summary ? (
            <p className="text-xs font-medium italic text-slate-500 dark:text-zinc-400">{variant.reasoning_summary}</p>
          ) : null}

          {isEditing ? (
            <div className="flex flex-col gap-2">
              <Textarea
                value={modifiedContent}
                onChange={(event) => setModifiedContent(event.target.value)}
                rows={12}
                className="[field-sizing:fixed]"
              />
              <div className="flex justify-end gap-1.5">
                <Button size="sm" variant="outline" className="h-8 text-sm" onClick={() => setIsEditing(false)}>
                  {t("cancel")}
                </Button>
                <Button size="sm" className="h-8 text-sm" disabled={isSubmitting} onClick={handleSubmitModification}>
                  {isSubmitting ? t("submitting") : t("saveModification")}
                </Button>
              </div>
            </div>
          ) : variant.is_reference && subquestions && subquestions.length > 0 ? (
            <div className="flex flex-col gap-2">
              {subquestions.map((sq) => (
                <SubquestionCard key={sq.id} subquestion={sq} />
              ))}
            </div>
          ) : (
            <LatexText text={variant.content} className="text-sm text-slate-700 dark:text-zinc-300" />
          )}

          {variant.strategy_name ? (
            <p className="border-t border-slate-100/80 pt-2.5 text-xs text-slate-500 dark:border-zinc-800/80 dark:text-zinc-400">
              <span className="font-semibold">{t("strategy")}:</span> {variant.strategy_name}
              {variant.distinction_score !== null ? ` (${t("distinctionScore")}: ${variant.distinction_score})` : ""}
            </p>
          ) : null}

          {error ? <p className="text-xs font-medium text-danger">{error}</p> : null}

          {!isEditing ? (
            <div className="flex flex-wrap justify-end gap-1.5 border-t border-slate-100 pt-3 dark:border-zinc-800">
              <Button
                size="sm"
                variant="outline"
                className="h-7 border-slate-200 px-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:border-zinc-700 dark:text-zinc-400"
                onClick={() => setShowReasoning((prev) => !prev)}
              >
                <GitBranch className="mr-1 size-3" />
                {showReasoning ? t("hideReasoningAction") : t("showReasoningAction")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 border-success/20 px-2 text-sm font-medium text-success hover:bg-success/10"
                disabled={isSubmitting}
                onClick={handleAccept}
              >
                <Check className="mr-1 size-3" />
                {t("acceptAction")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 border-danger/20 px-2 text-sm font-medium text-danger hover:bg-danger/10"
                disabled={isSubmitting}
                onClick={handleReject}
              >
                <X className="mr-1 size-3" />
                {t("rejectAction")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 border-slate-200 px-2 text-sm font-medium text-slate-600 hover:bg-slate-100 dark:border-zinc-700 dark:text-zinc-400"
                disabled={isSubmitting}
                onClick={() => setIsEditing(true)}
              >
                <Edit2 className="mr-1 size-3" />
                {t("modifyAction")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 border-danger/20 px-2 text-sm font-medium text-danger hover:bg-danger/10"
                disabled={isSubmitting}
                onClick={() => onDeleteRequested(variant)}
              >
                <Trash2 className="size-3" />
              </Button>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {showReasoning ? (
        <Card className="overflow-hidden">
          <CardHeader className="border-b border-slate-100/80 pb-3 pt-3.5 dark:border-zinc-800/80">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-zinc-400">
              {t("showReasoningAction")}
            </p>
          </CardHeader>
          <CardContent className="pt-4">
            <ReasoningGraphSection variantId={variant.id} />
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={rejectDialogOpen} onOpenChange={setRejectDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("rejectDialogTitle")}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-4 py-1">
            <p className="text-xs text-slate-500 dark:text-zinc-400">{t("rejectAutoRegenerateInfo")}</p>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="reject-comment" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                {t("reviewCommentLabel")}
              </Label>
              <Textarea
                id="reject-comment"
                value={rejectComment}
                onChange={(event) => setRejectComment(event.target.value)}
                placeholder={t("reviewCommentPlaceholder")}
                rows={3}
                className="min-h-20 text-sm leading-relaxed"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="reject-method-hint" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                {t("methodHintLabel")}
              </Label>
              <Textarea
                id="reject-method-hint"
                value={rejectMethodHint}
                onChange={(event) => setRejectMethodHint(event.target.value)}
                placeholder={t("methodHintPlaceholder")}
                rows={3}
                className="min-h-20 text-sm leading-relaxed"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="reject-concept-hint" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                {t("conceptHintLabel")}
              </Label>
              <Input
                id="reject-concept-hint"
                value={rejectConceptHint}
                onChange={(event) => setRejectConceptHint(event.target.value)}
                placeholder={t("conceptHintPlaceholder")}
                className="h-9 rounded-lg text-sm"
              />
            </div>
            {error ? <p className="text-xs font-medium text-danger">{error}</p> : null}
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="outline">
                {t("cancel")}
              </Button>
            </DialogClose>
            <Button type="button" disabled={isSubmitting} onClick={handleConfirmReject}>
              {isSubmitting ? t("submitting") : t("confirmRejectAction")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
