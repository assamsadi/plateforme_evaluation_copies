"use client";

import { useState } from "react";

import { IconSparkles } from "@tabler/icons-react";
import {
  BookOpen,
  ChevronDown,
  ChevronUp,
  Download,
  ExternalLink,
  Send,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SubmitExamDialog } from "@/app/[locale]/(main)/dashboard/my-exams/_components/submit-exam-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { Link } from "@/i18n/navigation";
import type { AssignedExerciseRead, RecommendedExerciseRead } from "@/lib/student-api";
import { cn } from "@/lib/utils";

function resolveTier(rec: RecommendedExerciseRead): {
  labelKey: string;
  tone: StatusTone;
  accent: string;
  bg: string;
  icon: React.ReactNode;
} {
  if (rec.category === "remediation" && rec.is_persistent_weakness) {
    return {
      labelKey: "tierToWorkOn",
      tone: "danger",
      accent: "bg-red-500",
      bg: "bg-red-50/50 dark:bg-red-950/20",
      icon: <Zap className="size-3.5" />,
    };
  }
  if (rec.category === "verification") {
    return {
      labelKey: "tierToConfirm",
      tone: "warning",
      accent: "bg-amber-500",
      bg: "bg-amber-50/50 dark:bg-amber-950/20",
      icon: <Target className="size-3.5" />,
    };
  }
  return {
    labelKey: "tierConsolidated",
    tone: "info",
    accent: "bg-primary",
    bg: "bg-primary/5 dark:bg-primary/10",
    icon: <TrendingUp className="size-3.5" />,
  };
}

export function RecommendationCard({
  recommendation,
  exercise,
}: {
  recommendation: RecommendedExerciseRead;
  exercise: AssignedExerciseRead | null;
}) {
  const t = useTranslations("MyProgress");
  const tier = resolveTier(recommendation);
  const [isExpanded, setIsExpanded] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);

  // Collect all attachment URLs from questions
  const attachments =
    exercise?.questions
      .filter((q) => q.attachment_path)
      .map((q) => ({ questionOrder: q.order, url: q.attachment_path! })) ?? [];

  return (
    <>
      <div
        className={cn(
          "group relative overflow-hidden rounded-2xl border border-slate-200/80 shadow-sm transition-all hover:shadow-md dark:border-zinc-800",
          tier.bg,
        )}
      >
        {/* Top accent bar */}
        <div className={cn("h-1 w-full", tier.accent)} />

        {/* Relevance score pill */}
        <div className="absolute right-4 top-4">
          <span className="inline-flex items-center gap-1 rounded-full border border-slate-200/60 bg-white/80 px-2 py-0.5 text-xs font-semibold text-slate-600 shadow-2xs backdrop-blur-sm dark:border-zinc-700/60 dark:bg-zinc-900/80 dark:text-zinc-300">
            <span className="size-1.5 rounded-full bg-primary" />
            {Math.round(recommendation.relevance_score * 100)}%
          </span>
        </div>

        <div className="flex flex-col gap-4 p-5">
          {/* Header */}
          <div className="flex flex-col gap-2 pr-14">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge
                tone={tier.tone}
                status={
                  <span className="flex items-center gap-1">
                    {tier.icon}
                    {t(tier.labelKey)}
                  </span>
                }
                className="text-xs"
              />
              {recommendation.difficulty_level && (
                <Badge variant="outline" className="text-xs font-medium">
                  {recommendation.difficulty_level}
                </Badge>
              )}
            </div>

            <h3 className="text-base font-bold leading-snug text-slate-900 dark:text-zinc-100">
              {recommendation.exercise_title}
            </h3>
          </div>

          {/* Reason */}
          <p className="text-sm leading-relaxed text-slate-600 dark:text-zinc-300">
            {(() => {
              const compKey = `competency_${recommendation.competency_code}`;
              const compName = t.has(compKey as any) ? t(compKey as any) : recommendation.competency_code;
              if (recommendation.is_persistent_weakness) {
                return t("reasonPersistentWeakness", {
                  competency: compName,
                  difficulty: recommendation.difficulty_level ?? "",
                });
              }
              if (recommendation.category === "remediation") {
                return t("reasonRemediation", {
                  competency: compName,
                  difficulty: recommendation.difficulty_level ?? "",
                });
              }
              return t("reasonVerification", {
                competency: compName,
                difficulty: recommendation.difficulty_level ?? "",
              });
            })()}
          </p>

          {/* Expandable questions section */}
          {exercise && exercise.questions.length > 0 && (
            <div className="overflow-hidden rounded-xl border border-slate-200/70 bg-white/80 dark:border-zinc-700/50 dark:bg-zinc-900/60">
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-sm font-semibold text-slate-800 transition-colors hover:bg-slate-50 dark:text-zinc-200 dark:hover:bg-zinc-800/50"
                onClick={() => setIsExpanded(!isExpanded)}
              >
                <span className="flex items-center gap-2">
                  <BookOpen className="size-4 text-primary" />
                  {t("viewQuestionsLabel", { count: exercise.questions.length })}
                </span>
                {isExpanded ? (
                  <ChevronUp className="size-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="size-4 text-muted-foreground" />
                )}
              </button>

              {isExpanded && (
                <div className="flex flex-col divide-y divide-slate-100 border-t border-slate-100 dark:divide-zinc-800 dark:border-zinc-800">
                  {exercise.questions.map((question) => (
                    <div key={question.id} className="flex flex-col gap-2 px-4 py-3">
                      <span className="text-xs font-bold uppercase tracking-wider text-primary">
                        {t("questionLabel", { order: question.order })}
                      </span>
                      <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-zinc-300 font-sans">
                        {question.statement}
                      </p>
                      {question.bareme && (
                        <span className="text-xs font-semibold text-muted-foreground">
                          {question.bareme.points} pts
                        </span>
                      )}
                      {question.attachment_path && (
                        <a
                          href={question.attachment_path}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex w-fit items-center gap-1.5 rounded-lg border border-primary/20 bg-primary/5 px-2.5 py-1 text-xs font-semibold text-primary transition-colors hover:bg-primary/10"
                        >
                          <Download className="size-3.5" />
                          {t("downloadAttachmentAction")}
                        </a>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Action buttons */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {/* Submit button */}
            {exercise && (
              <Button
                size="sm"
                className="h-9 gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white shadow-sm hover:bg-primary/90"
                onClick={() => setSubmitOpen(true)}
              >
                <Send className="size-3.5" />
                {t("submitExerciseAction")}
              </Button>
            )}

            {/* Download first attachment */}
            {attachments.length > 0 && (
              <a
                href={attachments[0].url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-4 text-sm font-semibold text-slate-700 shadow-2xs transition-colors hover:bg-slate-50 dark:border-zinc-700 dark:bg-zinc-900/60 dark:text-zinc-200 dark:hover:bg-zinc-800"
              >
                <Download className="size-3.5" />
                {t("downloadExerciseAction")}
              </a>
            )}

            {/* View in library */}
            <Link
              href={`/dashboard/library?module_id=${recommendation.module_id}&exercise_id=${recommendation.exercise_id}`}
              className="inline-flex h-9 items-center gap-2 rounded-xl border border-slate-200 bg-white/80 px-4 text-sm font-semibold text-slate-700 shadow-2xs transition-colors hover:bg-slate-50 dark:border-zinc-700 dark:bg-zinc-900/60 dark:text-zinc-200 dark:hover:bg-zinc-800"
            >
              <ExternalLink className="size-3.5" />
              {t("viewExerciseAction")}
            </Link>

            {/* NotebookLM AI */}
            {recommendation.notebook_chat_url && (
              <Link
                href={`/dashboard/my-progress/notebook/${recommendation.id}?module_id=${recommendation.module_id}`}
                className="inline-flex h-9 items-center gap-2 rounded-xl border border-violet-200 bg-violet-50/80 px-4 text-sm font-semibold text-violet-700 shadow-2xs transition-colors hover:bg-violet-100 dark:border-violet-800 dark:bg-violet-950/40 dark:text-violet-300 dark:hover:bg-violet-900/40"
              >
                <IconSparkles className="size-3.5" stroke={2} />
                {t("deepenWithAiAction")}
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* Submit dialog rendered outside card to avoid z-index issues */}
      {exercise && (
        <SubmitExamDialog
          exercise={exercise}
          open={submitOpen}
          onOpenChange={setSubmitOpen}
          onSubmitted={() => {
            toast.success(t("submitSuccess"));
          }}
        />
      )}
    </>
  );
}

