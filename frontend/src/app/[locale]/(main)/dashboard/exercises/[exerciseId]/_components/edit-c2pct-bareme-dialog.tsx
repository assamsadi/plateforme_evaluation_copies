"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Calculator } from "lucide-react";
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
import { setQuestionSubquestionPoints, type ExerciseRead, type QuestionRead } from "@/lib/professor-api";
import {
  formCancelBtnCn,
  formContextBlockCn,
  formErrorCn,
  formLabelCn,
  formSubmitBtnCn,
} from "../../../_components/form-styles";

// Les 15 sous-questions officielles C2PCT (CHAABI) — même référentiel figé
// que app/domain/models/competency/c2pct_scaffold.py côté backend, groupé
// par compétence pour l'affichage. Jamais un champ "total" séparé : la
// somme des valeurs saisies EST le total, rien à valider en double (cf.
// docstring SubquestionPointsCreate, exercise_schemas.py).
const C2PCT_GROUPS: { competency: string; subquestions: { id: string; label: string }[] }[] = [
  {
    competency: "Données et planification",
    subquestions: [
      { id: "1.1", label: "Lister et catégoriser les données" },
      { id: "1.2", label: "Identifier ce qui est demandé" },
      { id: "1.3", label: "Déterminer les données nécessaires" },
      { id: "1.4", label: "Représentation du problème" },
      { id: "1.5", label: "Identifier les données manquantes" },
    ],
  },
  {
    competency: "Décomposition et organisation",
    subquestions: [
      { id: "2.1", label: "Identifier le complément nécessaire" },
      { id: "2.2", label: "Diviser le problème en mini-problèmes" },
    ],
  },
  {
    competency: "Structuration algorithmique",
    subquestions: [
      { id: "3.1", label: "Décrire les étapes de résolution en mots" },
      { id: "3.2", label: "Représentation visuelle des étapes" },
    ],
  },
  {
    competency: "Généralisation et transfert",
    subquestions: [{ id: "4", label: "Identifier un autre problème/contexte" }],
  },
  {
    competency: "Communication de la solution",
    subquestions: [{ id: "5", label: "Rédiger la réponse finale" }],
  },
  {
    competency: "Auto-évaluation et créativité",
    subquestions: [
      { id: "6.1", label: "Le résultat a-t-il un sens" },
      { id: "6.2", label: "Est-ce la meilleure solution possible" },
    ],
  },
  {
    competency: "Réflexion et métacognition",
    subquestions: [
      { id: "7.1", label: "Difficultés rencontrées" },
      { id: "7.2", label: "Utilité de la structure suivie" },
    ],
  },
];

export function EditC2PCTBaremeDialog({
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
  const t = useTranslations("EditC2PCTBaremeDialog");
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (question) {
      const existing = question.subquestion_points ?? {};
      const initial: Record<string, string> = {};
      for (const group of C2PCT_GROUPS) {
        for (const sq of group.subquestions) {
          initial[sq.id] = existing[sq.id] != null ? String(existing[sq.id]) : "";
        }
      }
      setValues(initial);
      setError(null);
    }
  }, [question]);

  // Arrondi à 2 décimales pour l'affichage uniquement — bug réel constaté :
  // additionner des décimaux en JavaScript (ex. 0.3 + 0.3 + 0.5 + 0.35 + ...)
  // accumule une erreur d'arrondi binaire (0.3 n'est pas représentable
  // exactement en binaire) et affichait "6.999999999999998" au lieu de "7"
  // pour un total mathématiquement exact. N'affecte JAMAIS les données
  // réellement envoyées (chaque valeur repart telle quelle, en texte exact,
  // cf. SubquestionPointsCreate côté backend) — uniquement ce total
  // d'aperçu, jamais utilisé pour un calcul réel.
  const rawTotal = Object.values(values).reduce((sum, v) => sum + (Number(v) || 0), 0);
  const total = Math.round(rawTotal * 100) / 100;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!question) return;
    setError(null);

    const points: Record<string, number> = {};
    for (const [id, raw] of Object.entries(values)) {
      const trimmed = raw.trim();
      if (!trimmed) continue;
      points[id] = Number(trimmed);
    }
    if (Object.keys(points).length === 0) {
      setError(t("emptyError"));
      return;
    }

    const session = getStoredSession();
    if (!session) return;

    setIsSubmitting(true);
    try {
      const updated = await setQuestionSubquestionPoints(session.accessToken, exercise.id, question.id, { points });
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
      <DialogContent className="max-h-[85vh] overflow-y-auto p-0 sm:max-w-xl">
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
                <div className={formContextBlockCn}>{t("hint")}</div>

                <div className="flex flex-col gap-4">
                  {C2PCT_GROUPS.map((group) => (
                    <div key={group.competency} className="flex flex-col gap-2">
                      <p className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                        {group.competency}
                      </p>
                      <div className="flex flex-col gap-1.5">
                        {group.subquestions.map((sq) => (
                          <div
                            key={sq.id}
                            className="flex items-center gap-2 rounded-xl border border-slate-200/90 bg-slate-50/50 p-2.5 dark:border-zinc-800 dark:bg-zinc-800/30"
                          >
                            <span className="inline-flex shrink-0 items-center rounded-md bg-primary/10 px-2 py-0.5 text-xs font-bold text-primary ring-1 ring-primary/20">
                              {sq.id}
                            </span>
                            <span className="flex-1 text-sm font-medium text-slate-700 dark:text-zinc-300">
                              {sq.label}
                            </span>
                            <Input
                              className="h-9 w-24 rounded-lg border-slate-200 bg-white font-mono text-sm font-bold text-slate-900 placeholder:text-slate-400 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100"
                              type="number"
                              // step="any" (jamais un pas fixe type "0.1") — bug réel
                              // constaté en usage : un pas fixe déclenche la validation
                              // native du navigateur ("les valeurs valides les plus
                              // proches sont X et Y"), qui rejette à tort des valeurs
                              // décimales pourtant exactes (0.1 n'est pas représentable
                              // exactement en binaire) ET ne correspond de toute façon
                              // pas à la précision réelle des barèmes (0.30, 0.35...).
                              step="any"
                              min="0"
                              placeholder="—"
                              value={values[sq.id] ?? ""}
                              onChange={(event) =>
                                setValues((prev) => ({ ...prev, [sq.id]: event.target.value }))
                              }
                            />
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                <Field className="gap-2">
                  <FieldLabel className={formLabelCn}>{t("totalLabel")}</FieldLabel>
                  <p className="font-mono text-lg font-bold text-slate-900 dark:text-zinc-100">{total}</p>
                </Field>

                {error ? <div className={formErrorCn}>{error}</div> : null}
              </FieldGroup>

              <DialogFooter className="mt-2 -mx-6 -mb-6 rounded-b-xl border-t bg-muted/50 p-4 sm:justify-end gap-2">
                <DialogClose asChild>
                  <Button type="button" variant="outline" className={formCancelBtnCn}>
                    {t("cancel")}
                  </Button>
                </DialogClose>
                <Button type="submit" disabled={isSubmitting} className={formSubmitBtnCn}>
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
