"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { History, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { DeleteConfirmDialog } from "@/app/[locale]/(main)/dashboard/_components/delete-confirm-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LatexText } from "@/components/ui/latex-text";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Link } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  generateGuidedSolutionVariant,
  listQuestionSolutionVariants,
  reviewSolutionVariant,
  type QuestionRead,
  type SolutionVariantSummaryRead,
} from "@/lib/professor-api";

import { VariantPanel } from "./variant-panel";

const GENERIC_PREFIX_PATTERN = /^m[ée]thode?s?\s+(des?\s+|du\s+|d['’]|la\s+|le\s+|les\s+)?/i;
const TRAILING_PARENTHESIS_PATTERN = /\s*\([^)]*\)\s*$/;
const FRENCH_FILLER_WORDS = new Set(["de", "du", "des", "d'", "d’", "la", "le", "les", "et"]);

function shortStrategyLabel(name: string): string {
  const withoutPrefix = name.replace(GENERIC_PREFIX_PATTERN, "").trim();
  const withoutParenthesis = withoutPrefix.replace(TRAILING_PARENTHESIS_PATTERN, "").trim();
  const words = withoutParenthesis.split(/\s+/).filter(Boolean);
  let tail = words.slice(-2);
  while (tail.length > 1 && FRENCH_FILLER_WORDS.has(tail[0].toLowerCase())) {
    tail = tail.slice(1);
  }
  const result = tail.join(" ") || withoutParenthesis || name;
  return result.charAt(0).toUpperCase() + result.slice(1);
}

function variantFullLabel(variant: SolutionVariantSummaryRead, index: number, t: (key: string) => string): string {
  if (variant.is_reference) return t("referenceLabel");
  return variant.strategy_name || `${t("variantFallbackLabel")} ${index}`;
}

function variantTabLabel(variant: SolutionVariantSummaryRead, index: number, t: (key: string) => string): string {
  if (variant.is_reference) return t("referenceLabel");
  return variant.strategy_name ? shortStrategyLabel(variant.strategy_name) : `${t("variantFallbackLabel")} ${index}`;
}

export function VariantsPageContent({ question }: { question: QuestionRead }) {
  const t = useTranslations("VariantsDialog");
  const [variants, setVariants] = useState<SolutionVariantSummaryRead[]>([]);
  const [activeTab, setActiveTab] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SolutionVariantSummaryRead | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [generationFormOpen, setGenerationFormOpen] = useState(false);
  const [methodHint, setMethodHint] = useState("");
  const [conceptHint, setConceptHint] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [pendingGeneration, setPendingGeneration] = useState(false);
  const baselineVariantCountRef = useRef(0);

  const fetchVariants = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const result = await listQuestionSolutionVariants(session.accessToken, question.id);
      setVariants(result);
      setActiveTab((prev) => (prev && result.some((v) => v.id === prev) ? prev : (result[0]?.id ?? null)));
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [question.id, t]);

  useEffect(() => {
    fetchVariants();
  }, [fetchVariants]);

  // La génération guidée est asynchrone côté serveur (Celery) — l'appel ne
  // renvoie qu'un accusé de réception {question_id, status}, jamais la
  // variante elle-même. On referme le formulaire tout de suite et on
  // rafraîchit périodiquement jusqu'à ce qu'elle apparaisse (ou un délai
  // maximum), plutôt que d'espérer un id de variante qui n'existe pas encore.
  useEffect(() => {
    if (!pendingGeneration) return;
    let attempts = 0;
    const interval = setInterval(() => {
      attempts += 1;
      fetchVariants();
      if (attempts >= 6) {
        clearInterval(interval);
        setPendingGeneration(false);
      }
    }, 10_000);
    return () => clearInterval(interval);
  }, [pendingGeneration, fetchVariants]);

  useEffect(() => {
    if (pendingGeneration && variants.length > baselineVariantCountRef.current) {
      setPendingGeneration(false);
    }
  }, [variants, pendingGeneration]);

  async function handleGenerateGuided() {
    const session = getStoredSession();
    if (!session) return;

    setIsGenerating(true);
    try {
      await generateGuidedSolutionVariant(session.accessToken, question.id, {
        method_hint: methodHint.trim() || undefined,
        concept_hint: conceptHint.trim()
          ? conceptHint
              .split(",")
              .map((concept) => concept.trim())
              .filter(Boolean)
          : undefined,
      });
      baselineVariantCountRef.current = variants.length;
      setPendingGeneration(true);
      setGenerationFormOpen(false);
      setMethodHint("");
      setConceptHint("");
      toast.success(t("generationQueuedSuccess"));
    } catch (genError) {
      toast.error(genError instanceof AuthApiError ? genError.message : t("genericError"));
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleConfirmDelete() {
    const session = getStoredSession();
    const target = deleteTarget;
    if (!session || !target) return;

    setIsDeleting(true);
    try {
      await reviewSolutionVariant(session.accessToken, target.id, { action: "REJECTED" });
      toast.success(t("deleteSuccess"));
      setVariants((prev) => prev.filter((v) => v.id !== target.id));
      setActiveTab((prev) => (prev === target.id ? (variants.find((v) => v.id !== target.id)?.id ?? null) : prev));
      setDeleteTarget(null);
    } catch (deleteError) {
      toast.error(deleteError instanceof AuthApiError ? deleteError.message : t("genericError"));
    } finally {
      setIsDeleting(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Énoncé de la question — toujours visible en tête de page */}
      <Card className="overflow-hidden border-slate-200/90 shadow-2xs dark:border-zinc-800">
        <div className="h-1 w-full bg-primary" />
        <CardHeader className="pb-3 pt-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">
                {t("questionOrderTitle", { order: question.order })}
              </CardTitle>
              <div className="mt-2 text-sm font-semibold leading-relaxed text-slate-800 dark:text-zinc-200">
                <LatexText text={question.statement} />
              </div>
            </div>

            <div className="flex shrink-0 flex-wrap items-center gap-2">
              <Button size="sm" variant="outline" className="h-8 px-3 text-sm font-semibold" asChild>
                <Link href={`/dashboard/exercises/${question.exercise_id}/questions/${question.id}/variants/decision-logs`}>
                  <History className="mr-1.5 size-3.5" />
                  {t("decisionLogsAction")}
                </Link>
              </Button>
              <Button
                size="sm"
                className="h-8 bg-primary px-3 text-sm font-semibold text-primary-foreground shadow-2xs hover:bg-primary/90"
                onClick={() => setGenerationFormOpen((prev) => !prev)}
              >
                <Sparkles className="mr-1.5 size-3.5" />
                {t("generateGuidedAction")}
              </Button>
            </div>
          </div>
        </CardHeader>

        <CardContent className="pt-0 pb-4">
          {generationFormOpen ? (
            <div className="mt-3 flex flex-col gap-3.5 rounded-xl border border-primary/30 bg-primary/5 p-4">
              <p className="text-xs font-bold uppercase tracking-wider text-primary">{t("guidedFormTitle")}</p>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="method-hint" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                  {t("methodHintLabel")}
                </Label>
                <Textarea
                  id="method-hint"
                  value={methodHint}
                  onChange={(event) => setMethodHint(event.target.value)}
                  placeholder={t("methodHintPlaceholder")}
                  rows={4}
                  className="min-h-24 rounded-lg border-slate-200 bg-white text-sm leading-relaxed dark:border-zinc-700 dark:bg-zinc-800"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="concept-hint" className="text-sm font-semibold text-slate-800 dark:text-zinc-200">
                  {t("conceptHintLabel")}
                </Label>
                <Input
                  id="concept-hint"
                  value={conceptHint}
                  onChange={(event) => setConceptHint(event.target.value)}
                  placeholder={t("conceptHintPlaceholder")}
                  className="h-9 rounded-lg border-slate-200 bg-white text-sm dark:border-zinc-700 dark:bg-zinc-800"
                />
              </div>
              <div className="flex justify-end">
                <Button size="sm" disabled={isGenerating} onClick={handleGenerateGuided} className="h-9 rounded-lg px-4 text-sm font-semibold">
                  {isGenerating ? t("submitting") : t("generateAction")}
                </Button>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {isLoading ? (
        <div className="flex items-center justify-center gap-2 py-12">
          <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</p>
        </div>
      ) : error ? (
        <div className="rounded-lg border border-danger/20 bg-danger/10 p-3 text-sm font-medium text-danger">{error}</div>
      ) : variants.length === 0 ? (
        <div className="rounded-xl border border-slate-100 bg-slate-50/60 py-10 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
          <p className="text-sm font-medium text-slate-400 dark:text-zinc-500">{t("noVariants")}</p>
        </div>
      ) : (
        <Tabs value={activeTab ?? undefined} onValueChange={setActiveTab}>
          <div className="overflow-x-auto pb-1">
            <TabsList className="h-auto w-full flex-nowrap justify-start gap-1.5 bg-slate-100/70 p-1.5 dark:bg-zinc-800/50">
              {variants.map((variant, index) => (
                <TabsTrigger
                  key={variant.id}
                  value={variant.id}
                  title={variantFullLabel(variant, index + 1, t)}
                  className="max-w-[160px] shrink-0 truncate px-3.5 py-1.5 text-sm font-semibold data-active:bg-primary/15 data-active:text-primary dark:data-active:bg-primary/20 dark:data-active:text-primary"
                >
                  <span className="truncate">{variantTabLabel(variant, index + 1, t)}</span>
                </TabsTrigger>
              ))}
            </TabsList>
          </div>

          {variants.map((variant) => (
            <TabsContent key={variant.id} value={variant.id} className="pt-4">
              <VariantPanel
                variant={variant}
                subquestions={question.subquestions}
                onChanged={fetchVariants}
                onDeleteRequested={setDeleteTarget}
              />
            </TabsContent>
          ))}
        </Tabs>
      )}

      <DeleteConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(next) => !next && setDeleteTarget(null)}
        title={t("deleteConfirmTitle")}
        description={t("deleteConfirmDescription")}
        cancelLabel={t("cancel")}
        confirmLabel={t("deleteAction")}
        isPending={isDeleting}
        onConfirm={handleConfirmDelete}
      />
    </div>
  );
}
