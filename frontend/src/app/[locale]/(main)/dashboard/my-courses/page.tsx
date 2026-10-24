"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { DeleteConfirmDialog } from "@/app/[locale]/(main)/dashboard/_components/delete-confirm-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useRouter } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { deleteCourse, listMyCourses, type CourseRead } from "@/lib/professor-api";

import { EditCourseDialog } from "./_components/edit-course-dialog";
import { MyCourses } from "./_components/my-courses";

const PAGE_SIZE = 200;

function MyCoursesPageContent() {
  const t = useTranslations("MyCourses");
  const router = useRouter();
  const [courses, setCourses] = useState<CourseRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingCourseId, setPendingCourseId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CourseRead | null>(null);
  const [editTarget, setEditTarget] = useState<CourseRead | null>(null);

  const fetchCourses = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const page = await listMyCourses(session.accessToken, { limit: PAGE_SIZE });
      setCourses(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    fetchCourses();
  }, [fetchCourses]);

  async function handleConfirmDelete() {
    const session = getStoredSession();
    const target = deleteTarget;
    if (!session || !target) return;

    setPendingCourseId(target.id);
    try {
      await deleteCourse(session.accessToken, target.id);
      setCourses((prev) => prev.filter((c) => c.id !== target.id));
      toast.success(t("deleteSuccess", { name: target.module_name }));
      setDeleteTarget(null);
    } catch (actionError) {
      toast.error(actionError instanceof AuthApiError ? actionError.message : t("deleteError"));
    } finally {
      setPendingCourseId(null);
    }
  }

  function handleCreated(created: CourseRead) {
    setCourses((prev) => [created, ...prev]);
    toast.success(t("createSuccess", { name: created.module_name }));
  }

  function handleUpdated(updated: CourseRead) {
    setCourses((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
    toast.success(t("updateSuccess", { name: updated.module_name }));
  }

  if (error) {
    return (
      <Alert variant="destructive" className="rounded-2xl">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-12 justify-center">
        <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-xs font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</span>
      </div>
    );
  }

  return (
    <>
      <MyCourses
        courses={courses}
        onEdit={setEditTarget}
        onDelete={setDeleteTarget}
        onCreated={handleCreated}
        onViewStudents={(course) => router.push(`/dashboard/my-courses/${course.id}/students`)}
      />
      <EditCourseDialog
        course={editTarget}
        open={Boolean(editTarget)}
        onOpenChange={(open) => !open && setEditTarget(null)}
        onUpdated={handleUpdated}
      />
      <DeleteConfirmDialog
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title={t("deleteConfirmTitle")}
        description={
          deleteTarget
            ? t("deleteConfirmDescription", { module: deleteTarget.module_name, group: deleteTarget.group_label })
            : ""
        }
        cancelLabel={t("cancel")}
        confirmLabel={t("deleteAction")}
        isPending={Boolean(pendingCourseId)}
        onConfirm={handleConfirmDelete}
      />
    </>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <MyCoursesPageContent />
    </AuthGuard>
  );
}
