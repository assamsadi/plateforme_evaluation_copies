"use client";

import { useCallback, useEffect, useState } from "react";

import { AlertCircle, CheckCircle2, ChevronRight, CornerDownRight, Edit3, Flag, Link2, Send, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { LatexText } from "@/components/ui/latex-text";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { StatusBadge } from "@/components/ui/status-badge";
import { Textarea } from "@/components/ui/textarea";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  confirmSubmission,
  contestExtractionAttachment,
  contestExtractionContent,
  listSubmissionCorrections,
  type AssignedExerciseRead,
  type ExtractionCorrectionRead,
  type SubmissionRead,
} from "@/lib/student-api";

// Écran de vérification/contestation — anciennement une modale
// (verify-extraction-dialog.tsx), converti en page dédiée (même principe
// que l'écran des variantes, B10). Purement visuel : structure "Cahier
// structuré" (espacement généreux, une seule couleur sémantique), aucun
// changement de logique de rattachement/regroupement par question.
function CorrectionBlock({
  correction,
  questionOrder,
  availableQuestions,
  onContested,
}: {
  correction: ExtractionCorrectionRead;
  questionOrder: number | null;
  availableQuestions: { id: string; order: number }[];
  onContested: (updated: ExtractionCorrectionRead) => void;
}) {
  const t = useTranslations("VerifyExtractionDialog");
  const [isContesting, setIsContesting] = useState(false);
  const [claimedContent, setClaimedContent] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Rattachement (Cas B, distinct de la contestation de contenu ci-dessus,
  // cf. commentaire student-api.ts) — uniquement proposé sur un bloc non
  // rattaché (questionOrder === null, cf. rendu plus bas) : réclamer une
  // question sur un bloc déjà rattaché n'a pas de sens ici.
  const [isClaimingAttachment, setIsClaimingAttachment] = useState(false);
  const [claimedQuestionId, setClaimedQuestionId] = useState("");
  const [isSubmittingAttachment, setIsSubmittingAttachment] = useState(false);

  const alreadyContested = correction.contestation_status !== null && correction.contestation_status !== undefined;
  // contestation_status est la seule source de vérité pour le badge — jamais
  // une déduction depuis verified_content (un IMPLAUSIBLE ne pose jamais
  // verified_content, ce serait indissociable d'un signalement pas encore
  // traité).
  // Bug réel corrigé (2026-09-06, signalé) : contestation_status="resolved"
  // est posé À L'IDENTIQUE que le professeur ait accepté ou rejeté la
  // réclamation (arbitrage) — le badge affichait donc TOUJOURS "Signalement
  // tranché par l'enseignant", même sur un rejet, sans jamais distinguer.
  // Le vrai verdict vit dans arbitration_verdict (relayé depuis
  // CorrectionArbitration, jamais contestation_status seul).
  const contestationTone =
    correction.contestation_status === "plausible" ||
    (correction.contestation_status === "resolved" && correction.arbitration_verdict === "accepted")
      ? "success"
      : correction.contestation_status === "implausible" ||
          (correction.contestation_status === "resolved" && correction.arbitration_verdict === "rejected")
        ? "neutral"
        : "warning";
  const contestationLabel =
    correction.contestation_status === "plausible"
      ? t("contestationPlausible")
      : correction.contestation_status === "implausible"
        ? t("contestationImplausible")
        : correction.contestation_status === "resolved"
          ? correction.arbitration_verdict === "accepted"
            ? t("contestationResolvedAccepted")
            : correction.arbitration_verdict === "rejected"
              ? t("contestationResolvedRejected")
              : t("contestationResolved")
          : t("contestedBadge");
  // verified_content prime sur prediction_ocr dès qu'un verdict PLAUSIBLE
  // l'a posé — jamais l'inverse, prediction_ocr resterait le texte que
  // l'étudiant vient justement de contester avec succès.
  const displayedContent = correction.verified_content ?? correction.prediction_ocr;

  async function handleSubmitContest() {
    const session = getStoredSession();
    if (!session || !claimedContent.trim()) return;
    setIsSubmitting(true);
    try {
      const updated = await contestExtractionContent(
        session.accessToken, correction.submission_id, correction.id, claimedContent.trim(),
      );
      onContested(updated);
      setIsContesting(false);
      toast.success(t("contestSuccess"));
    } catch (contestError) {
      toast.error(contestError instanceof AuthApiError ? contestError.message : t("contestError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleSubmitAttachment() {
    const session = getStoredSession();
    if (!session || !claimedQuestionId) return;
    setIsSubmittingAttachment(true);
    try {
      const updated = await contestExtractionAttachment(
        session.accessToken, correction.submission_id, correction.id, claimedQuestionId,
      );
      onContested(updated);
      setIsClaimingAttachment(false);
      toast.success(t("contestSuccess"));
    } catch (attachmentError) {
      toast.error(attachmentError instanceof AuthApiError ? attachmentError.message : t("contestError"));
    } finally {
      setIsSubmittingAttachment(false);
    }
  }

  return (
    <div className="flex w-full flex-col gap-6 rounded-2xl border border-slate-200/80 bg-white p-6 shadow-sm transition-all hover:shadow-md dark:border-zinc-800/80 dark:bg-zinc-950">
      {/* En-tête (Header) */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4 dark:border-zinc-800/80">
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center justify-center rounded-md bg-slate-100 px-3 py-1.5 text-sm font-semibold text-slate-800 dark:bg-zinc-800 dark:text-zinc-200">
            {questionOrder !== null ? t("questionLabel", { order: questionOrder }) : t("unattachedLabel")}
          </span>
          {alreadyContested && (
            <StatusBadge tone={contestationTone} status={contestationLabel} className="px-2.5 py-1 text-xs font-semibold" />
          )}
        </div>
        {correction.is_low_ocr_confidence && (
          <div className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300">
            <AlertCircle className="size-4" />
            <span>{t("lowOcrConfidence")}</span>
          </div>
        )}
      </div>

      {/* Zone de Prévisualisation & OCR */}
      <div className="flex flex-col gap-6">
        {/* Media */}
        <div className="flex flex-col gap-3 rounded-xl bg-slate-50 p-5 dark:bg-zinc-900/50">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            Écriture manuscrite originale
          </p>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={correction.image_url}
            alt=""
            className="min-h-24 max-h-72 w-auto self-start rounded-lg border border-slate-200/50 bg-white object-contain shadow-xs dark:border-zinc-800"
            loading="lazy"
          />
        </div>

        {/* OCR Result */}
        <div className="flex flex-col gap-3 rounded-xl border border-slate-100 bg-slate-50/50 p-5 dark:border-zinc-800/50 dark:bg-zinc-900/30">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
            Texte reconnu (OCR)
          </p>
          <LatexText text={displayedContent} className="text-base font-medium leading-relaxed text-slate-800 dark:text-zinc-100" />
        </div>
      </div>

      {/* Pied de Carte (Actions Footer) */}
      {!alreadyContested && (
        <div className="flex flex-col gap-4 border-t border-slate-100 pt-5 dark:border-zinc-800/80">
          <div className="flex flex-wrap items-center gap-4">
            {questionOrder === null && availableQuestions.length > 0 && (
              <Button
                type="button"
                variant={isClaimingAttachment ? "secondary" : "outline"}
                className="h-10 rounded-xl px-4 text-sm font-semibold transition-all"
                onClick={() => {
                  setIsClaimingAttachment(!isClaimingAttachment);
                  setIsContesting(false);
                }}
              >
                <Link2 className="mr-2 size-4" />
                {t("claimAttachmentAction")}
              </Button>
            )}

            <Button
              type="button"
              variant={isContesting ? "secondary" : "outline"}
              className="h-10 rounded-xl px-4 text-sm font-semibold transition-all"
              onClick={() => {
                setIsContesting(!isContesting);
                setIsClaimingAttachment(false);
              }}
            >
              <Flag className="mr-2 size-4" />
              {t("reportErrorAction")}
            </Button>
          </div>

          {/* Tiroir repliable: Rattacher à une question */}
          {isClaimingAttachment && (
            <div className="w-full max-w-sm rounded-xl border border-indigo-100 bg-indigo-50/40 p-5 shadow-xs dark:border-indigo-900/30 dark:bg-indigo-950/20">
              <div className="mb-4 flex items-center justify-between">
                <span className="text-sm font-bold text-indigo-900 dark:text-indigo-300">Rattacher à une question</span>
                <Button size="icon-xs" variant="ghost" onClick={() => setIsClaimingAttachment(false)} disabled={isSubmittingAttachment} className="h-6 w-6 text-indigo-900 hover:bg-indigo-100 dark:text-indigo-300 dark:hover:bg-indigo-900/50">
                  <X className="size-4" />
                </Button>
              </div>
              <div className="flex flex-col gap-4">
                <Select value={claimedQuestionId} onValueChange={setClaimedQuestionId}>
                  <SelectTrigger className="h-11 w-full rounded-lg bg-white shadow-xs dark:bg-zinc-900">
                    <SelectValue placeholder={t("claimAttachmentPlaceholder")} />
                  </SelectTrigger>
                  <SelectContent>
                    {availableQuestions.map((q) => (
                      <SelectItem key={q.id} value={q.id}>
                        {t("questionLabel", { order: q.order })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  size="sm"
                  className="h-10 w-full rounded-lg bg-indigo-600 font-semibold text-white hover:bg-indigo-700"
                  onClick={handleSubmitAttachment}
                  disabled={isSubmittingAttachment || !claimedQuestionId}
                >
                  <CheckCircle2 className="mr-2 size-4" />
                  {t("submitAttachmentAction")}
                </Button>
              </div>
            </div>
          )}

          {/* Tiroir repliable: Signaler une erreur */}
          {isContesting && (
            <div className="w-full max-w-xl rounded-xl border border-emerald-100 bg-emerald-50/40 p-5 shadow-xs dark:border-emerald-900/30 dark:bg-emerald-950/20">
              <div className="mb-4 flex items-center justify-between">
                <span className="text-sm font-bold text-emerald-900 dark:text-emerald-300">Corriger le texte OCR</span>
                <Button size="icon-xs" variant="ghost" onClick={() => setIsContesting(false)} disabled={isSubmitting} className="h-6 w-6 text-emerald-900 hover:bg-emerald-100 dark:text-emerald-300 dark:hover:bg-emerald-900/50">
                  <X className="size-4" />
                </Button>
              </div>
              <div className="flex flex-col gap-4">
                <p className="text-xs text-emerald-800/80 dark:text-emerald-200/70">
                  L'intelligence artificielle a mal déchiffré votre écriture ? Modifiez le texte ci-dessous :
                </p>
                <Textarea
                  value={claimedContent}
                  onChange={(e) => setClaimedContent(e.target.value)}
                  placeholder={t("claimedContentPlaceholder")}
                  className="min-h-[120px] rounded-lg border-emerald-200/60 bg-white p-4 text-sm font-medium leading-relaxed focus-visible:ring-emerald-500/20 dark:border-zinc-700 dark:bg-zinc-900"
                />
                <div className="flex items-center justify-end gap-3 pt-1">
                  <Button size="sm" variant="ghost" onClick={() => setIsContesting(false)} disabled={isSubmitting} className="h-10 font-semibold text-emerald-900 hover:bg-emerald-100 dark:text-emerald-300 dark:hover:bg-emerald-900/50">
                    {t("cancelAction")}
                  </Button>
                  <Button
                    size="sm"
                    className="h-10 rounded-lg bg-emerald-600 px-6 font-semibold text-white shadow-sm hover:bg-emerald-700"
                    onClick={handleSubmitContest}
                    disabled={isSubmitting || !claimedContent.trim()}
                  >
                    <Send className="mr-2 size-4" />
                    {t("submitContestAction")}
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function VerifyExtractionContent({
  submission,
  exercise,
  onConfirmed,
}: {
  submission: SubmissionRead;
  exercise: AssignedExerciseRead | null;
  onConfirmed: () => void;
}) {
  const t = useTranslations("VerifyExtractionDialog");
  const [corrections, setCorrections] = useState<ExtractionCorrectionRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isConfirming, setIsConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchCorrections = useCallback(async (isSilent = false) => {
    const session = getStoredSession();
    if (!session) return;
    if (!isSilent) {
      setIsLoading(true);
    }
    setError(null);
    try {
      const result = await listSubmissionCorrections(session.accessToken, submission.id);
      setCorrections(result);
    } catch (fetchError) {
      if (!isSilent) {
        setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
      }
    } finally {
      if (!isSilent) {
        setIsLoading(false);
      }
    }
  }, [submission.id, t]);

  useEffect(() => {
    fetchCorrections(false);
  }, [fetchCorrections]);

  // Le verdict de Contestation_Verification_Agent arrive de façon
  // asynchrone (tâche Celery), jamais dans la même requête que le dépôt du
  // signalement — ce polling silencieux en arrière-plan évite que le badge reste figé sur "en cours de
  // traitement" SANS jamais détruire l'arbre DOM ni provoquer de sauts de défilement (layout shift).
  const hasPendingContestationForPolling = corrections.some(
    (c) => c.contestation_status === "pending_verification",
  );
  useEffect(() => {
    if (!hasPendingContestationForPolling) return;
    const interval = setInterval(() => {
      fetchCorrections(true);
    }, 10_000);
    return () => clearInterval(interval);
  }, [hasPendingContestationForPolling, fetchCorrections]);

  function handleContested(updated: ExtractionCorrectionRead) {
    setCorrections((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  }

  async function handleConfirm() {
    const session = getStoredSession();
    if (!session) return;
    setIsConfirming(true);
    try {
      await confirmSubmission(session.accessToken, submission.id);
      toast.success(t("confirmSuccess"));
      onConfirmed();
    } catch (confirmError) {
      toast.error(confirmError instanceof AuthApiError ? confirmError.message : t("confirmError"));
    } finally {
      setIsConfirming(false);
    }
  }

  const questionOrderByQuestionId = new Map(
    (exercise?.questions ?? []).map((question) => [question.id, question.order]),
  );
  const hasPendingContestation = corrections.some(
    (c) => c.contestation_status === "pending_verification" || c.contestation_status === "ambigu",
  );

  // Regroupement par question globale conservé tel quel (pas de
  // sous-découpage) — un simple en-tête par groupe, dans l'ordre
  // d'apparition, blocs non rattachés relégués en dernier.
  const questionIds = Array.from(
    new Set(corrections.map((c) => c.question_id).filter((id): id is string => id !== null)),
  ).sort((a, b) => (questionOrderByQuestionId.get(a) ?? 0) - (questionOrderByQuestionId.get(b) ?? 0));
  const unattached = corrections.filter((c) => c.question_id === null);
  const availableQuestions = (exercise?.questions ?? [])
    .map((question) => ({ id: question.id, order: question.order }))
    .sort((a, b) => a.order - b.order);

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

  if (corrections.length === 0) {
    return (
      <div className="rounded-xl border bg-muted/30 py-12 text-center">
        <p className="text-sm font-medium text-muted-foreground">{t("noCorrections")}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      {questionIds.map((questionId) => (
        <div key={questionId} className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-foreground">
            {t("questionLabel", { order: questionOrderByQuestionId.get(questionId) ?? "" })}
          </h2>
          <div className="flex flex-col gap-3">
            {corrections
              .filter((c) => c.question_id === questionId)
              .map((correction) => (
                <CorrectionBlock
                  key={correction.id}
                  correction={correction}
                  questionOrder={questionOrderByQuestionId.get(questionId) ?? null}
                  availableQuestions={availableQuestions}
                  onContested={handleContested}
                />
              ))}
          </div>
        </div>
      ))}

      {unattached.length > 0 ? (
        <div className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold text-foreground">{t("unattachedLabel")}</h2>
          <div className="flex flex-col gap-3">
            {unattached.map((correction) => (
              <CorrectionBlock
                key={correction.id}
                correction={correction}
                questionOrder={null}
                availableQuestions={availableQuestions}
                onContested={handleContested}
              />
            ))}
          </div>
        </div>
      ) : null}

      <Separator />

      <Button onClick={handleConfirm} disabled={isConfirming || hasPendingContestation} size="lg" className="w-full sm:w-fit sm:self-end">
        <CheckCircle2 className="size-4" />
        {hasPendingContestation ? t("confirmDisabledPending") : t("confirmAction")}
      </Button>
    </div>
  );
}
