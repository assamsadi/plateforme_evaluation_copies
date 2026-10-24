/**
 * Shared form styling utilities for professor dashboard dialogs.
 * Keeps all form chrome consistent: labels, inputs, selects, error state,
 * footer buttons — without touching any logic.
 */

// 2026-09-11 — remonté d'un cran (démarche "toute l'application, admin
// compris") : partagé entre dialogs enseignant ET admin (AddExerciseDialog,
// EditBaremeDialog... ET AddUserDialog, EditProgramDialog, AddCredentialDialog...),
// corrigé UNE SEULE FOIS ici plutôt qu'en double dans chaque dialog.

/** Label style: standard, semibold, dark slate */
export const formLabelCn = "text-base font-semibold text-slate-800 dark:text-zinc-200";

/** Standard input height and border */
export const formInputCn =
  "h-11 rounded-xl border-slate-200 bg-white text-base text-slate-900 placeholder:text-slate-400 focus-visible:ring-primary/30 focus-visible:border-primary dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100";

/** Select trigger matching inputs */
export const formSelectTriggerCn =
  "h-11 w-full rounded-xl border-slate-200 bg-white text-base text-slate-900 focus:ring-primary/30 focus:border-primary dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100";

/** Textarea: similar to input */
export const formTextareaCn =
  "rounded-xl border-slate-200 bg-white text-base text-slate-900 placeholder:text-slate-400 focus-visible:ring-primary/30 focus-visible:border-primary dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100";

/** Context block (shows existing data) */
export const formContextBlockCn =
  "rounded-xl border border-slate-200/80 bg-slate-50/80 p-4 text-base leading-relaxed text-slate-800 dark:border-zinc-800 dark:bg-zinc-800/40 dark:text-zinc-200";

/** Primary submit button */
export const formSubmitBtnCn =
  "h-11 bg-primary px-4 text-base font-semibold text-primary-foreground shadow-2xs hover:bg-primary/90 disabled:opacity-50";

/** Cancel button */
export const formCancelBtnCn =
  "h-11 border-slate-200 px-4 text-base font-semibold text-slate-700 hover:border-slate-300 hover:bg-slate-50 dark:border-zinc-700 dark:text-zinc-300";

/** Danger action button (reject / incoherent) */
export const formDangerBtnCn =
  "h-11 border-rose-200 px-4 text-base font-semibold text-rose-700 hover:border-rose-300 hover:bg-rose-50 dark:border-rose-900/40 dark:text-rose-400";

/** Success action button (accept / coherent) */
export const formSuccessBtnCn =
  "h-11 bg-emerald-600 px-4 text-base font-semibold text-white shadow-2xs hover:bg-emerald-700";

/** Inline error paragraph */
export const formErrorCn =
  "rounded-lg border border-rose-200 bg-rose-50 px-3.5 py-2.5 text-sm font-semibold text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300";
