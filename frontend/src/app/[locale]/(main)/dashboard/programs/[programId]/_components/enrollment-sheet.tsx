"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { StatusBadge } from "@/components/ui/status-badge";
import { deactivateEnrollment, type EnrollmentRead, listModuleEnrollments } from "@/lib/admin-api";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";

import { AddEnrollmentForm } from "./add-enrollment-form";

export function EnrollmentSheet({
  moduleId,
  moduleName,
  open,
  onOpenChange,
}: {
  moduleId: string | null;
  moduleName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("EnrollmentSheet");
  const [enrollments, setEnrollments] = useState<EnrollmentRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingEnrollmentId, setPendingEnrollmentId] = useState<string | null>(null);

  const fetchEnrollments = useCallback(async () => {
    if (!moduleId) return;
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listModuleEnrollments(session.accessToken, moduleId);
      setEnrollments(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [moduleId, t]);

  useEffect(() => {
    if (open && moduleId) {
      fetchEnrollments();
    }
  }, [open, moduleId, fetchEnrollments]);

  async function handleDeactivate(enrollment: EnrollmentRead) {
    const session = getStoredSession();
    if (!session) return;

    setPendingEnrollmentId(enrollment.id);
    try {
      const updated = await deactivateEnrollment(session.accessToken, enrollment.id);
      setEnrollments((prev) => prev.map((e) => (e.id === updated.id ? updated : e)));
      toast.success(t("deactivateSuccess", { name: enrollment.student_full_name }));
    } catch (actionError) {
      toast.error(actionError instanceof AuthApiError ? actionError.message : t("deactivateError"));
    } finally {
      setPendingEnrollmentId(null);
    }
  }

  function handleEnrolled(created: EnrollmentRead) {
    setEnrollments((prev) => [created, ...prev]);
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col gap-0 sm:max-w-md">
        <SheetHeader>
          <SheetTitle>{t("title", { moduleName })}</SheetTitle>
        </SheetHeader>

        <div className="flex flex-col gap-4 overflow-y-auto px-4 pb-4">
          <AddEnrollmentForm moduleId={moduleId ?? ""} onEnrolled={handleEnrolled} />

          <Separator />

          {error ? <p className="text-destructive text-base">{error}</p> : null}

          {isLoading ? (
            <p className="text-muted-foreground text-base">{t("loading")}</p>
          ) : enrollments.length === 0 ? (
            <p className="text-muted-foreground text-base">{t("empty")}</p>
          ) : (
            <div className="flex flex-col gap-2">
              {enrollments.map((enrollment) => {
                const isPending = pendingEnrollmentId === enrollment.id;
                return (
                  <div
                    key={enrollment.id}
                    className="flex items-center justify-between gap-3 rounded-lg border p-3 text-base"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">{enrollment.student_full_name}</div>
                      <StatusBadge
                        tone={enrollment.is_active ? "success" : "neutral"}
                        status={enrollment.is_active ? t("statusActive") : t("statusInactive")}
                        className="mt-1"
                      />
                    </div>
                    {enrollment.is_active ? (
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={isPending}
                        onClick={() => handleDeactivate(enrollment)}
                      >
                        {t("deactivateAction")}
                      </Button>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
