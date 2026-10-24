"use client";

import { useCallback, useEffect, useState } from "react";

import { AlertTriangle, CheckCircle2, Clock, Gavel, Info, Minus, PieChart, RefreshCcw, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge, type StatusTone } from "@/components/ui/status-badge";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  getMySubmissionResults,
  getSubmissionFeedback,
  listSubmissionAppeals,
  listSubmissionEvaluations,
  type AppealResolution,
  type AppealStatus,
  type EvaluationRead,
  type FeedbackReportRead,
  type GradeAppealRead,
  type QuestionResultRead,
  type SubmissionRead,
} from "@/lib/student-api";

import { FileAppealDialog } from "../../../_components/file-appeal-dialog";

const appealStatusTone: Record<AppealStatus, StatusTone> = {
  pending: "warning",
  under_review: "info",
  resolved: "success",
};

// Icône + teinte par résolution — exprime visuellement le sens de chaque
// issue (note maintenue / révisée / partiellement révisée), même traitement
// icon-box que l'en-tête "Appeals" plutôt qu'un simple texte gras.
const appealResolutionVisual: Record<AppealResolution, { icon: typeof ShieldCheck; boxClassName: string }> = {
  grade_upheld: { icon: ShieldCheck, boxClassName: "border-primary/20 bg-primary/10 text-primary" },
  grade_revised: { icon: RefreshCcw, boxClassName: "border-success/20 bg-success/10 text-success" },
  partial_revision: { icon: PieChart, boxClassName: "border-warning/20 bg-warning/10 text-warning" },
};

function initials(fullName: string) {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? parts[0]?.[1] ?? "");
}

// 3 zones visuellement distinctes (séparateurs "border-t" nets, jamais un
// flux continu) : (a) message étudiant avec auteur+horodatage, (b) statut
// bien visible avec le score contesté associé au même badge plutôt
// qu'isolé, (c) réponse du professeur avec son propre auteur+horodatage —
// demande explicite après relecture du rendu précédent.
function AppealRow({ appeal }: { appeal: GradeAppealRead }) {
  const t = useTranslations("SubmissionDetailDialog");
  const locale = useLocale();
  const ResolutionIcon = appeal.resolution ? appealResolutionVisual[appeal.resolution].icon : null;

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border bg-muted/30">
      {/* (a) Message étudiant */}
      <div className="flex flex-col gap-2.5 p-3.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/15 text-xs font-bold text-primary">
              {initials(appeal.student_full_name)}
            </span>
            <span className="text-sm font-semibold text-foreground">{appeal.student_full_name}</span>
          </div>
          <span className="text-xs text-muted-foreground">{new Date(appeal.created_at).toLocaleString(locale)}</span>
        </div>
        <div className="flex flex-col gap-2 pl-9">
          {appeal.reason
            .split(/\n\s*\n/)
            .map((paragraph) => paragraph.trim())
            .filter(Boolean)
            .map((paragraph, index) => (
              <p key={index} className="text-sm italic leading-relaxed text-foreground">
                {paragraph}
              </p>
            ))}
        </div>
      </div>

      {/* (b) Statut — score contesté rattaché directement au badge, plus relégué en petit texte gris isolé */}
      <div className="flex items-center justify-between gap-2 border-t bg-card/60 px-3.5 py-2.5">
        <StatusBadge tone={appealStatusTone[appeal.status]} status={t(`appealStatus_${appeal.status}`)} />
        <span className="flex items-center gap-1.5 font-mono text-sm font-bold text-foreground">
          <span className="text-xs font-medium text-muted-foreground">{t("appealOriginalScoreLabel")}</span>
          {appeal.original_score} pts
        </span>
      </div>

      {/* (c) Réponse du professeur */}
      {appeal.status === "resolved" && appeal.resolution ? (
        <div className="flex flex-col gap-2.5 border-t p-3.5">
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2.5">
              <span
                className={`flex size-9 shrink-0 items-center justify-center rounded-xl border ${appealResolutionVisual[appeal.resolution].boxClassName}`}
              >
                {ResolutionIcon ? <ResolutionIcon className="size-4.5" /> : null}
              </span>
              <div className="flex flex-col">
                <p className="font-semibold text-foreground">
                  {t(`appealResolution_${appeal.resolution}`)}
                  {appeal.revised_score !== null ? ` — ${t("appealRevisedScore", { score: appeal.revised_score })}` : ""}
                </p>
                <span className="text-xs font-medium text-muted-foreground">
                  {appeal.resolved_by_professor_name ?? t("unknownProfessor")}
                </span>
              </div>
            </div>
            {appeal.resolved_at ? (
              <span className="text-xs text-muted-foreground">{new Date(appeal.resolved_at).toLocaleString(locale)}</span>
            ) : null}
          </div>
          {appeal.review_comment ? (
            <div className="ml-11.5 flex items-start gap-2 rounded-lg border border-primary/25 bg-primary/10 p-2.5">
              <Info className="mt-0.5 size-4 shrink-0 text-primary" />
              <p className="text-sm font-semibold italic text-foreground">{appeal.review_comment}</p>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

// Les competency_code bruts (ex. "data_and_planning") viennent de l'enum
// backend en snake_case — jamais destinés à un affichage direct, donc
// convertis en texte lisible dès qu'il n'y a pas de criterion_label humain.
function formatCompetencyCode(code: string) {
  const spaced = code.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// Couleur + icône par ligne de compétence — basé sur le vrai success_rate
// renvoyé par le backend (EvaluationCriteria.subquestion_detail, Phase 4/4
// C2PCT), jamais une couleur fixe : 0% = danger (icône croix), 100% =
// success (icône coche), tout le reste = warning, sans icône (pas un
// verdict binaire).
const competencyToneClasses: Record<"danger" | "warning" | "success" | "neutral", string> = {
  danger: "text-danger",
  warning: "text-warning",
  success: "text-success",
  neutral: "text-foreground",
};

function getCompetencyTone(successRate: number | null) {
  if (successRate === null) return { tone: "neutral" as const, Icon: null };
  if (successRate <= 0) return { tone: "danger" as const, Icon: XCircle };
  if (successRate >= 1) return { tone: "success" as const, Icon: CheckCircle2 };
  return { tone: "warning" as const, Icon: null };
}

// Verdict global de la question — mêmes seuils que la logique de tone
// ci-dessus, appliqués au ratio score/max de la question entière, pour un
// signal lisible avant même de lire le détail par compétence.
function getQuestionVerdict(ratio: number | null) {
  if (ratio === null) return null;
  if (ratio < 0.5) return { tone: "danger" as const, Icon: AlertTriangle, labelKey: "verdictToRevisit" as const };
  if (ratio < 0.8) return { tone: "warning" as const, Icon: Minus, labelKey: "verdictSatisfactory" as const };
  return { tone: "success" as const, Icon: CheckCircle2, labelKey: "verdictExcellent" as const };
}

// Met en évidence les numéros de sous-questions (ex. "1.1", "2.2", "4")
// cités dans le feedback — uniquement à l'intérieur des groupes entre
// parenthèses "(sous-questions 1.1, 1.2 ...)", pour ne jamais accrocher un
// nombre qui n'a rien à voir (score, date...) présent hors parenthèses.
function renderFeedbackParagraph(paragraph: string) {
  return paragraph.split(/(\([^)]*\))/g).map((segment, segIndex) => {
    if (!(segment.startsWith("(") && segment.endsWith(")"))) return segment;
    return (
      <span key={segIndex}>
        {segment.split(/(\d+(?:\.\d+)?)/g).map((part, partIndex) =>
          /^\d+(?:\.\d+)?$/.test(part) ? (
            <strong key={partIndex} className="font-bold text-primary not-italic">
              {part}
            </strong>
          ) : (
            part
          ),
        )}
      </span>
    );
  });
}

function QuestionResultRow({
  evaluation,
  questionResult,
}: {
  evaluation: EvaluationRead;
  questionResult: QuestionResultRead | undefined;
}) {
  const t = useTranslations("SubmissionResultsPage");
  const ratio = questionResult && Number(questionResult.max_score) > 0 ? Number(evaluation.score) / Number(questionResult.max_score) : null;
  const verdict = getQuestionVerdict(ratio);

  return (
    // Bordure primary bien visible (même traitement que les blocs d'extraction,
    // cf. écran de vérification) — chaque question notée doit se démarquer.
    <div className="flex flex-col gap-2 rounded-xl border-2 border-primary/60 bg-card p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-foreground">
            {t("questionLabel", { order: evaluation.question_order })}
          </span>
          {verdict ? (
            <StatusBadge
              tone={verdict.tone}
              className="text-xs"
              status={
                <>
                  <verdict.Icon className="mr-1 size-3.5" />
                  {t(verdict.labelKey)}
                </>
              }
            />
          ) : null}
        </div>
        <span className="font-mono text-sm font-bold text-danger">
          {questionResult
            ? t("questionScoreLabel", { score: evaluation.score, max: questionResult.max_score })
            : `${evaluation.score} pts`}
        </span>
      </div>
      {evaluation.criteria.length > 0 ? (
        <ul className="mt-1 flex flex-col gap-1.5 border-t pt-2">
          {evaluation.criteria.map((criterion) => {
            const successRate = criterion.subquestion_detail ? Number(criterion.subquestion_detail.success_rate) : null;
            const { tone, Icon: ToneIcon } = getCompetencyTone(successRate);
            return (
              <li key={criterion.id} className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
                <span className="flex min-w-0 items-center gap-1.5">
                  {ToneIcon ? <ToneIcon className={`size-4 shrink-0 ${competencyToneClasses[tone]}`} /> : null}
                  <span className="truncate italic text-black dark:text-white">
                    {criterion.criterion_label ?? (criterion.competency_code ? formatCompetencyCode(criterion.competency_code) : t("competencyLine"))}
                  </span>
                </span>
                <span className={`[font-family:var(--font-handwriting)] shrink-0 text-xl leading-none font-bold ${competencyToneClasses[tone]}`}>
                  +{criterion.points_awarded}
                </span>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}

// Bug corrigé (2026-09-02, cas réel zainabsebhi) : une question sans
// Evaluation disparaissait purement et simplement de l'écran (la liste
// itérait sur les évaluations, jamais sur le barème complet) — l'étudiant
// n'avait alors AUCUN moyen de savoir qu'une partie de sa copie n'avait
// pas encore été corrigée. Carte visuellement distincte (pointillés, pas de
// score) plutôt qu'une absence silencieuse.
// Raison affichée (2026-09-06, cas réel salma, copie hors-sujet) : le badge
// générique ne disait jamais POURQUOI une question restait sans note — un
// étudiant/professeur ne pouvait pas distinguer "je n'ai rien répondu à
// cette question" (no_student_answer) d'un vrai retard de correction
// (pending_review, contenu déposé mais pas encore jugé).
function ungradedReasonLabel(
  reason: QuestionResultRead["not_graded_reason"],
  t: (key: string) => string,
): string {
  if (reason === "no_student_answer") return t("questionNotGradedNoAnswer");
  if (reason === "pending_review") return t("questionNotGradedPending");
  return t("questionNotGraded");
}

function UngradedQuestionRow({ questionResult }: { questionResult: QuestionResultRead }) {
  const t = useTranslations("SubmissionResultsPage");
  return (
    <div className="flex flex-col gap-2 rounded-xl border-2 border-dashed border-muted-foreground/30 bg-muted/20 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Clock className="size-4 text-muted-foreground" />
          <span className="text-sm font-semibold text-foreground">
            {t("questionLabel", { order: questionResult.question_order })}
          </span>
          <StatusBadge
            tone="warning"
            className="text-xs"
            status={ungradedReasonLabel(questionResult.not_graded_reason, t)}
          />
        </div>
        <span className="font-mono text-sm font-semibold text-muted-foreground">
          {t("questionMaxScoreLabel", { max: questionResult.max_score })}
        </span>
      </div>
      {/* Justification RÉELLE de l'agent (2026-09-06) — affichée telle
          quelle quand disponible, jamais remplacée par un texte générique :
          c'est précisément ce que le badge seul ne pouvait pas exprimer. */}
      {questionResult.blocking_justification ? (
        <p className="pl-6 text-sm italic leading-relaxed text-muted-foreground">
          {t("questionBlockingJustificationPrefix")} {questionResult.blocking_justification}
        </p>
      ) : null}
    </div>
  );
}

export function SubmissionResultsContent({
  submission,
  onScoreLoaded,
}: {
  submission: SubmissionRead;
  onScoreLoaded?: (score: { total_score: number; max_score: number; is_fully_graded: boolean } | null) => void;
}) {
  const t = useTranslations("SubmissionResultsPage");
  const [results, setResults] = useState<{ total_score: number; max_score: number } | null>(null);
  const [evaluations, setEvaluations] = useState<EvaluationRead[]>([]);
  const [questionResults, setQuestionResults] = useState<QuestionResultRead[]>([]);
  const [feedback, setFeedback] = useState<FeedbackReportRead | null>(null);
  const [appeals, setAppeals] = useState<GradeAppealRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isAppealDialogOpen, setIsAppealDialogOpen] = useState(false);

  const fetchAll = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const [resultsData, evaluationsData] = await Promise.all([
        getMySubmissionResults(session.accessToken, submission.id),
        listSubmissionEvaluations(session.accessToken, submission.id),
      ]);
      setResults(resultsData);
      onScoreLoaded?.(resultsData);
      setQuestionResults(resultsData.questions);
      setEvaluations(evaluationsData);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }

    // Best-effort, jamais bloquant (même principe que l'ancienne modale) :
    // un 404 (pas encore généré / aucun recours déposé) est l'état normal.
    try {
      setFeedback(await getSubmissionFeedback(session.accessToken, submission.student_id, submission.id));
    } catch {
      setFeedback(null);
    }
    try {
      setAppeals(await listSubmissionAppeals(session.accessToken, submission.id));
    } catch {
      setAppeals([]);
    }
  }, [submission.id, submission.student_id, t]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  function handleAppealFiled(appeal: GradeAppealRead) {
    setAppeals((prev) => [appeal, ...prev]);
  }

  const questionResultById = new Map(questionResults.map((q) => [q.question_id, q]));
  const evaluationByQuestionId = new Map(evaluations.map((e) => [e.question_id, e]));

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-16">
        <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm font-medium text-muted-foreground">{t("loading")}</p>
      </div>
    );
  }

  if (error) {
    return <div className="rounded-lg border border-danger/20 bg-danger/10 p-4 text-sm font-medium text-danger">{error}</div>;
  }

  return (
    <div className="flex flex-col gap-6">
      {questionResults.length === 0 ? (
        <div className="rounded-xl border bg-muted/30 py-12 text-center">
          <p className="text-sm font-medium text-muted-foreground">{t("noEvaluations")}</p>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {[...questionResults]
            .sort((a, b) => a.question_order - b.question_order)
            .map((questionResult) => {
              const evaluation = evaluationByQuestionId.get(questionResult.question_id);
              return evaluation ? (
                <QuestionResultRow key={questionResult.question_id} evaluation={evaluation} questionResult={questionResult} />
              ) : (
                <UngradedQuestionRow key={questionResult.question_id} questionResult={questionResult} />
              );
            })}
        </div>
      )}

      {feedback ? (
        <Card className="overflow-hidden rounded-2xl border-0 bg-[#F8FBFE] shadow-2xl ring-1 ring-black/10 dark:bg-zinc-900 dark:ring-white/10">
          <div className="flex shrink-0 items-center gap-1.5 border-b border-black/5 px-4 py-3 dark:border-white/10">
            <span className="size-3 rounded-full bg-[#ff605c]" />
            <span className="size-3 rounded-full bg-[#ffbd44]" />
            <span className="size-3 rounded-full bg-[#00ca4e]" />
          </div>
          <CardHeader className="flex flex-row items-center gap-2.5 border-b border-black/5 px-5 py-4 dark:border-white/10">
            <div className="flex size-9 items-center justify-center rounded-xl border border-info/20 bg-info/10 text-info">
              <Sparkles className="size-4.5" />
            </div>
            <CardTitle className="text-sm font-semibold text-foreground">{t("feedbackTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3.5 px-5 pb-5 pt-4">
            {feedback.feedback_text
              .split(/\n\s*\n/)
              .map((paragraph) => paragraph.trim())
              .filter(Boolean)
              .map((paragraph, index) => (
                <p key={index} className="text-base italic leading-relaxed text-black dark:text-white">
                  {renderFeedbackParagraph(paragraph)}
                </p>
              ))}
          </CardContent>
        </Card>
      ) : null}

      {evaluations.length > 0 ? (
        <Card className="overflow-hidden rounded-2xl border-0 bg-[#F8FBFE] shadow-2xl ring-1 ring-black/10 dark:bg-zinc-900 dark:ring-white/10">
          <div className="flex shrink-0 items-center gap-1.5 border-b border-black/5 px-4 py-3 dark:border-white/10">
            <span className="size-3 rounded-full bg-[#ff605c]" />
            <span className="size-3 rounded-full bg-[#ffbd44]" />
            <span className="size-3 rounded-full bg-[#00ca4e]" />
          </div>
          <CardHeader className="flex flex-row items-center justify-between gap-2.5 border-b border-black/5 px-5 py-4 dark:border-white/10">
            <div className="flex items-center gap-2.5">
              <div className="flex size-9 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
                <Gavel className="size-4.5" />
              </div>
              <CardTitle className="text-sm font-semibold text-foreground">{t("appealsTitle")}</CardTitle>
            </div>
            <Button size="sm" variant="skew" className="h-8 px-3.5 text-sm font-semibold tracking-wide" onClick={() => setIsAppealDialogOpen(true)}>
              <Gavel className="size-3.5" /> {t("fileAppealAction")}
            </Button>
          </CardHeader>
          <CardContent className="px-5 pb-5 pt-4">
            {appeals.length > 0 ? (
              <div className="flex flex-col gap-2">
                {appeals.map((appeal) => (
                  <AppealRow key={appeal.id} appeal={appeal} />
                ))}
              </div>
            ) : (
              <p className="text-sm font-medium text-black dark:text-white">{t("noAppeals")}</p>
            )}
          </CardContent>
        </Card>
      ) : null}

      <FileAppealDialog
        submission={submission}
        evaluations={evaluations}
        open={isAppealDialogOpen}
        onOpenChange={setIsAppealDialogOpen}
        onFiled={handleAppealFiled}
      />
    </div>
  );
}
