"use client";

import { type FormEvent, useEffect, useState } from "react";

import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "@/components/ui/status-badge";
import { Textarea } from "@/components/ui/textarea";
import { TrafficLightDialog } from "@/components/ui/traffic-light-dialog";
import {
  completeErasurePrivacyRequest,
  type DataPrivacyRequestRead,
  type PrivacyResolutionDetail,
  RESOLUTION_DETAILS_BY_REQUEST_TYPE,
  rejectPrivacyRequest,
  startProcessingPrivacyRequest,
  verifyPrivacyRequestIdentity,
} from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { statusTone } from "./data";

type ActiveAction = "verify" | "complete" | "reject" | null;

export function RequestDetailDialog({
  request,
  open,
  onOpenChange,
  onUpdated,
}: {
  request: DataPrivacyRequestRead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUpdated: (request: DataPrivacyRequestRead) => void;
}) {
  const t = useTranslations("PrivacyRequestDetailDialog");
  const locale = useLocale();

  const [activeAction, setActiveAction] = useState<ActiveAction>(null);
  const [verificationMethod, setVerificationMethod] = useState("");
  const [resolutionDetail, setResolutionDetail] = useState<PrivacyResolutionDetail>("full_deletion");
  const [reason, setReason] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (request) {
      setActiveAction(null);
      setVerificationMethod("");
      setResolutionDetail(RESOLUTION_DETAILS_BY_REQUEST_TYPE[request.request_type][0] ?? "rejected");
      setReason("");
      setRejectReason("");
      setError(null);
    }
  }, [request]);

  const availableResolutionDetails = request ? RESOLUTION_DETAILS_BY_REQUEST_TYPE[request.request_type] : [];

  async function runAction(action: () => Promise<DataPrivacyRequestRead>) {
    setError(null);
    setIsSubmitting(true);
    try {
      const updated = await action();
      onUpdated(updated);
      setActiveAction(null);
    } catch (submitError) {
      setError(submitError instanceof AuthApiError ? submitError.message : t("genericError"));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleVerifySubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const session = getStoredSession();
    if (!session || !request) return;
    await runAction(() => verifyPrivacyRequestIdentity(session.accessToken, request.id, verificationMethod));
  }

  async function handleStartProcessing() {
    const session = getStoredSession();
    if (!session || !request) return;
    await runAction(() => startProcessingPrivacyRequest(session.accessToken, request.id));
  }

  async function handleCompleteSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const session = getStoredSession();
    if (!session || !request) return;
    await runAction(() =>
      completeErasurePrivacyRequest(session.accessToken, request.id, {
        resolution_detail: resolutionDetail,
        reason: reason || null,
      }),
    );
  }

  async function handleRejectSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const session = getStoredSession();
    if (!session || !request) return;
    await runAction(() => rejectPrivacyRequest(session.accessToken, request.id, rejectReason));
  }

  if (!request) {
    return (
      <TrafficLightDialog open={open} onOpenChange={onOpenChange} contentClassName="sm:max-w-md">
        <></>
      </TrafficLightDialog>
    );
  }

  const canVerifyIdentity = request.status === "pending" && !request.identity_verified;
  const canStartProcessing = request.status === "pending" && request.identity_verified;
  const canComplete = request.status === "in_progress" && request.request_type !== "access_export";
  const isUnsupportedExport = request.status === "in_progress" && request.request_type === "access_export";
  const canReject = request.status === "pending" || request.status === "in_progress";
  const isFinal = request.status === "completed" || request.status === "rejected";

  return (
    <TrafficLightDialog open={open} onOpenChange={onOpenChange} contentClassName="sm:max-w-lg">
      <>
        <DialogHeader>
          <DialogTitle className="text-base font-bold text-slate-900 dark:text-zinc-100">{t("title")}</DialogTitle>
        </DialogHeader>

        <div className="mt-4 flex flex-col gap-4">
          <div className="rounded-xl border border-slate-200/80 bg-slate-50/80 p-4 text-base dark:border-zinc-800 dark:bg-zinc-800/40">
            <div className="flex items-center justify-between gap-2">
              <p className="font-semibold text-foreground text-base">{request.user_full_name}</p>
              <StatusBadge tone={statusTone[request.status]} status={t(`status_${request.status}`)} />
            </div>
            <dl className="mt-3.5 grid grid-cols-2 gap-x-4 gap-y-2.5 text-muted-foreground text-base font-medium">
              <dt>{t("fieldType")}</dt>
              <dd className="text-right text-foreground">{t(`type_${request.request_type}`)}</dd>
              <dt>{t("fieldDeadline")}</dt>
              <dd className="text-right text-foreground">
                {new Date(request.legal_deadline).toLocaleDateString(locale)}
              </dd>
              <dt>{t("fieldIdentityVerified")}</dt>
              <dd className="text-right text-foreground">
                {request.identity_verified ? t("identityVerified") : t("identityNotVerified")}
              </dd>
              <dt>{t("fieldCreatedAt")}</dt>
              <dd className="text-right text-foreground">{new Date(request.created_at).toLocaleString(locale)}</dd>
              {request.processed_at ? (
                <>
                  <dt>{t("fieldProcessedAt")}</dt>
                  <dd className="text-right text-foreground">
                    {new Date(request.processed_at).toLocaleString(locale)}
                  </dd>
                </>
              ) : null}
              {request.resolution_detail ? (
                <>
                  <dt>{t("fieldResolutionDetail")}</dt>
                  <dd className="text-right text-foreground">{t(`resolution_${request.resolution_detail}`)}</dd>
                </>
              ) : null}
              {request.retention_or_rejection_reason ? (
                <>
                  <dt className="col-span-2">{t("fieldReason")}</dt>
                  <dd className="col-span-2 text-foreground">{request.retention_or_rejection_reason}</dd>
                </>
              ) : null}
            </dl>
          </div>

          {error ? <p className="text-destructive text-base">{error}</p> : null}

          {isFinal ? <p className="text-muted-foreground text-base">{t("finalStateNote")}</p> : null}

          {isUnsupportedExport ? <p className="text-muted-foreground text-base">{t("exportUnsupportedNote")}</p> : null}

          {activeAction === "verify" ? (
            <form onSubmit={handleVerifySubmit} className="flex flex-col gap-3 rounded-lg border p-3">
              <Field className="gap-1.5">
                <FieldLabel htmlFor="verify-method">{t("verificationMethod")}</FieldLabel>
                <Input
                  id="verify-method"
                  value={verificationMethod}
                  onChange={(event) => setVerificationMethod(event.target.value)}
                  placeholder={t("verificationMethodPlaceholder")}
                  required
                />
              </Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="outline" onClick={() => setActiveAction(null)}>
                  {t("cancel")}
                </Button>
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? t("submitting") : t("confirmVerify")}
                </Button>
              </div>
            </form>
          ) : null}

          {activeAction === "complete" ? (
            <form onSubmit={handleCompleteSubmit} className="flex flex-col gap-3 rounded-lg border p-3">
              <Field className="gap-1.5">
                <FieldLabel htmlFor="complete-resolution">{t("resolutionDetail")}</FieldLabel>
                <Select
                  value={resolutionDetail}
                  onValueChange={(value) => setResolutionDetail(value as PrivacyResolutionDetail)}
                >
                  <SelectTrigger id="complete-resolution" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {availableResolutionDetails.map((value) => (
                      <SelectItem key={value} value={value}>
                        {t(`resolution_${value}`)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field className="gap-1.5">
                <FieldLabel htmlFor="complete-reason">{t("reason")}</FieldLabel>
                <Textarea
                  id="complete-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  rows={2}
                />
              </Field>
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-slate-200 px-4 text-base font-semibold"
                  onClick={() => setActiveAction(null)}
                >
                  {t("cancel")}
                </Button>
                <Button
                  type="submit"
                  variant="skew"
                  className="h-9 px-4 text-base font-semibold tracking-wide"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? t("submitting") : t("confirmComplete")}
                </Button>
              </div>
            </form>
          ) : null}

          {activeAction === "reject" ? (
            <form
              onSubmit={handleRejectSubmit}
              className="flex flex-col gap-3 rounded-xl border border-slate-200/80 p-4 dark:border-zinc-800"
            >
              <Field className="gap-2">
                <FieldLabel
                  htmlFor="reject-reason"
                  className="text-base font-semibold text-slate-800 dark:text-zinc-200"
                >
                  {t("rejectReason")}
                </FieldLabel>
                <Textarea
                  id="reject-reason"
                  value={rejectReason}
                  onChange={(event) => setRejectReason(event.target.value)}
                  rows={2}
                  required
                  className="rounded-xl border-slate-200 text-base dark:border-zinc-700"
                />
              </Field>
              <div className="flex justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-slate-200 px-4 text-base font-semibold"
                  onClick={() => setActiveAction(null)}
                >
                  {t("cancel")}
                </Button>
                <Button
                  type="submit"
                  variant="skew-destructive"
                  className="h-9 px-4 text-base font-semibold tracking-wide"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? t("submitting") : t("confirmReject")}
                </Button>
              </div>
            </form>
          ) : null}

          {activeAction === null && !isFinal ? (
            <div className="flex flex-wrap justify-end gap-2">
              {canVerifyIdentity ? (
                <Button
                  size="sm"
                  variant="skew"
                  className="h-9 px-4 text-base font-semibold tracking-wide"
                  onClick={() => setActiveAction("verify")}
                >
                  {t("verifyIdentityAction")}
                </Button>
              ) : null}
              {canStartProcessing ? (
                <Button
                  size="sm"
                  variant="skew"
                  className="h-9 px-4 text-base font-semibold tracking-wide"
                  disabled={isSubmitting}
                  onClick={handleStartProcessing}
                >
                  {isSubmitting ? t("submitting") : t("startProcessingAction")}
                </Button>
              ) : null}
              {canComplete ? (
                <Button
                  size="sm"
                  variant="skew"
                  className="h-9 px-4 text-base font-semibold tracking-wide"
                  onClick={() => setActiveAction("complete")}
                >
                  {t("completeAction")}
                </Button>
              ) : null}
              {canReject ? (
                <Button
                  size="sm"
                  variant="skew-destructive"
                  className="h-9 px-4 text-base font-semibold tracking-wide"
                  onClick={() => setActiveAction("reject")}
                >
                  {t("rejectAction")}
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
      </>
    </TrafficLightDialog>
  );
}
