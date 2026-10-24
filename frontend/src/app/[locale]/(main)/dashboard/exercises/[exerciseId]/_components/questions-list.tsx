"use client";

import { ListChecks, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { LatexText } from "@/components/ui/latex-text";
import { Link } from "@/i18n/navigation";
import type { QuestionRead, SubquestionRead } from "@/lib/professor-api";

export function SubquestionCard({ subquestion }: { subquestion: SubquestionRead }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-200/90 bg-white p-3.5 shadow-2xs dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center gap-2">
        <span className="inline-flex shrink-0 items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-bold text-primary ring-1 ring-primary/20">
          {subquestion.id}
        </span>
        <span className="text-xs font-bold text-slate-700 dark:text-zinc-300">{subquestion.official_title}</span>
      </div>
      <LatexText
        text={subquestion.content}
        className="text-sm font-medium leading-relaxed text-slate-800 dark:text-zinc-200"
      />
    </div>
  );
}

export function QuestionsList({
  questions,
  canEditStructure,
  onAddVariant,
  onEditBareme,
  onEditC2PCTBareme,
  onAddQuestion,
  onEditQuestion,
  onDeleteQuestion,
}: {
  questions: QuestionRead[];
  canEditStructure: boolean;
  onAddVariant: (question: QuestionRead) => void;
  onEditBareme: (question: QuestionRead) => void;
  onEditC2PCTBareme: (question: QuestionRead) => void;
  onAddQuestion: () => void;
  onEditQuestion: (question: QuestionRead) => void;
  onDeleteQuestion: (question: QuestionRead) => void;
}) {
  const t = useTranslations("ExerciseDetail");

  return (
    <Card className="overflow-hidden border-slate-200/90 shadow-2xs dark:border-zinc-800">
      <CardHeader className="border-b border-slate-100 pb-4 pt-4 dark:border-zinc-800">
        <div>
          <CardTitle className="font-serif text-base font-bold text-slate-900 dark:text-zinc-100">
            {t("questionsTitle")}
            <span className="ml-2 inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-bold text-slate-700 dark:bg-zinc-800 dark:text-zinc-300">
              {questions.length}
            </span>
          </CardTitle>
          <p className="mt-1 text-sm font-medium text-slate-500 dark:text-zinc-400">{t("questionsDescription")}</p>
        </div>
        {canEditStructure ? (
          <CardAction>
            <Button
              size="sm"
              variant="skew"
              className="h-10 px-4 text-base font-semibold tracking-wide"
              onClick={onAddQuestion}
            >
              <Plus className="mr-1.5 size-4" /> {t("addQuestionAction")}
            </Button>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-4 pt-4">
        {questions.length === 0 ? (
          <EmptyState icon={ListChecks} title={t("emptyQuestionsTitle")} description={t("emptyQuestionsDescription")} />
        ) : null}
        {[...questions]
          .sort((a, b) => a.order - b.order)
          .map((question) => (
            <div
              key={question.id}
              className="flex flex-col gap-3.5 rounded-xl border border-slate-200/80 bg-slate-50/70 p-4.5 transition-colors hover:border-primary/40 hover:bg-emerald-50/20 dark:border-zinc-800 dark:bg-zinc-900/60"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-2.5">
                  <span className="mt-0.5 inline-flex shrink-0 items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-bold text-primary ring-1 ring-primary/20">
                    Q{question.order}
                  </span>
                  {!question.subquestions || question.subquestions.length === 0 ? (
                    <LatexText
                      text={question.statement}
                      className="text-sm font-semibold leading-relaxed text-slate-900 dark:text-zinc-100"
                    />
                  ) : null}
                </div>
                <div className="flex shrink-0 flex-wrap justify-end gap-2">
                  {canEditStructure ? (
                    <>
                      <Button
                        size="sm"
                        variant="skew"
                        className="h-8 px-3 text-sm font-semibold tracking-wide"
                        onClick={() => onEditQuestion(question)}
                      >
                        {t("editQuestionAction")}
                      </Button>
                      {questions.length > 1 ? (
                        <Button
                          size="sm"
                          variant="skew-destructive"
                          className="h-8 px-3 text-sm font-semibold tracking-wide"
                          onClick={() => onDeleteQuestion(question)}
                        >
                          {t("deleteQuestionAction")}
                        </Button>
                      ) : null}
                    </>
                  ) : null}
                  {/* Barème classique et barème C2PCT natif sont mutuellement exclusifs
                      (cf. Question.bareme / Question.subquestion_points) — jamais les
                      deux boutons "Ajouter" en même temps une fois l'un des deux choisi,
                      pour ne jamais laisser le professeur créer accidentellement les deux
                      mécanismes sur la même question. */}
                  {!question.subquestion_points ? (
                    <Button
                      size="sm"
                      variant="skew"
                      className="h-8 px-3 text-sm font-semibold tracking-wide"
                      onClick={() => onEditBareme(question)}
                    >
                      {question.bareme ? t("editBaremeAction") : t("addBaremeAction")}
                    </Button>
                  ) : null}
                  {!question.bareme ? (
                    <Button
                      size="sm"
                      variant="skew"
                      className="h-8 px-3 text-sm font-semibold tracking-wide"
                      onClick={() => onEditC2PCTBareme(question)}
                    >
                      {question.subquestion_points ? t("editC2PCTBaremeAction") : t("addC2PCTBaremeAction")}
                    </Button>
                  ) : null}
                  <Button size="sm" variant="skew" className="h-8 px-3 text-sm font-semibold tracking-wide" asChild>
                    <Link href={`/dashboard/exercises/${question.exercise_id}/questions/${question.id}/variants`}>
                      {t("viewVariantsAction")}
                    </Link>
                  </Button>
                  <Button
                    size="sm"
                    variant="skew"
                    className="h-8 px-3 text-sm font-semibold tracking-wide"
                    onClick={() => onAddVariant(question)}
                  >
                    {t("addVariantAction")}
                  </Button>
                </div>
              </div>

              {question.subquestions && question.subquestions.length > 0 ? (
                <div className="flex flex-col gap-2.5">
                  {question.subquestions.map((sq) => (
                    <SubquestionCard key={sq.id} subquestion={sq} />
                  ))}
                </div>
              ) : null}

              {question.bareme ? (
                <div className="flex flex-col gap-2 border-t border-emerald-200/60 pt-3 dark:border-emerald-900/40">
                  <p className="text-xs font-bold uppercase tracking-wider text-emerald-800 dark:text-emerald-400">
                    {t("baremeLabel")} — {question.bareme.points} {t("points")}
                  </p>
                  {question.bareme.criteria.length > 0 ? (
                    <div className="flex flex-wrap gap-2">
                      {question.bareme.criteria.map((criterion) => (
                        <span
                          key={criterion.id}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-100/90 px-2.5 py-1 text-xs font-semibold text-emerald-900 ring-1 ring-emerald-300/80 dark:bg-emerald-950/60 dark:text-emerald-300 dark:ring-emerald-800"
                        >
                          {criterion.label}
                          <span className="font-bold">{criterion.points} pts</span>
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : question.subquestion_points ? (
                // Bug réel corrigé (2026-09-03, test réel examen C2PCT à 3
                // exercices) : le barème C2PCT natif (Cas 0) était calculé et
                // persisté correctement mais jamais affiché — le professeur
                // voyait l'avertissement "Pas de barème" ci-dessous alors
                // qu'un vrai barème complet existait, juste sous un mécanisme
                // distinct (`subquestion_points`, jamais `bareme`).
                <div className="flex flex-col gap-2 border-t border-emerald-200/60 pt-3 dark:border-emerald-900/40">
                  <p className="text-xs font-bold uppercase tracking-wider text-emerald-800 dark:text-emerald-400">
                    {t("baremeLabel")} (C2PCT) —{" "}
                    {Object.values(question.subquestion_points).reduce((sum, points) => sum + points, 0)} {t("points")}
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(question.subquestion_points)
                      .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
                      .map(([subquestionId, points]) => (
                        <span
                          key={subquestionId}
                          className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-100/90 px-2.5 py-1 text-xs font-semibold text-emerald-900 ring-1 ring-emerald-300/80 dark:bg-emerald-950/60 dark:text-emerald-300 dark:ring-emerald-800"
                        >
                          {subquestionId}
                          <span className="font-bold">{points} pts</span>
                        </span>
                      ))}
                  </div>
                </div>
              ) : (
                <p className="border-t border-amber-200/60 pt-3 text-xs font-semibold text-amber-800 dark:border-amber-900/40 dark:text-amber-300">
                  ⚠ {t("noBareme")}
                </p>
              )}
            </div>
          ))}
      </CardContent>
    </Card>
  );
}
