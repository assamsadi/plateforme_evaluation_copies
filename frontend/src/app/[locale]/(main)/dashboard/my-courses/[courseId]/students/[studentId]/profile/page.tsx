"use client";

import { useCallback, useEffect, useState } from "react";

import { useParams } from "next/navigation";

import { IconArrowLeft, IconUser } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Link } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  getStudentCompetencyModules,
  listCourseStudents,
  listMyCourses,
  type StudentModuleOptionRead,
  type StudentPublic,
} from "@/lib/professor-api";

import { StudentProfileContent } from "./_components/student-profile-content";

const PAGE_SIZE = 200;

function StudentProfilePageInner() {
  const t = useTranslations("StudentProfilePage");
  const { courseId, studentId } = useParams<{ courseId: string; studentId: string }>();
  const [student, setStudent] = useState<StudentPublic | null>(null);
  const [modules, setModules] = useState<StudentModuleOptionRead[]>([]);
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const [studentsPage, coursesPage] = await Promise.all([
        listCourseStudents(session.accessToken, courseId),
        listMyCourses(session.accessToken, { limit: PAGE_SIZE }),
      ]);
      const foundStudent = studentsPage.find((s) => s.id === studentId) ?? null;
      if (!foundStudent) {
        setError(t("studentNotFound"));
        setIsLoading(false);
        return;
      }
      setStudent(foundStudent);

      const modulesResult = await getStudentCompetencyModules(session.accessToken, studentId);
      setModules(modulesResult);

      const course = coursesPage.items.find((c) => c.id === courseId);
      const preferredModuleId = course && modulesResult.some((m) => m.module_id === course.module_id)
        ? course.module_id
        : (modulesResult[0]?.module_id ?? null);
      setSelectedModuleId(preferredModuleId);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [courseId, studentId, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-2">
        <Link
          href={`/dashboard/my-courses`}
          className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-sm text-muted-foreground shadow-2xs transition-colors hover:bg-muted hover:text-foreground"
        >
          <IconArrowLeft className="size-4" stroke={1.75} />
          {t("backToCourses")}
        </Link>
      </div>

      {error ? (
        <Alert variant="destructive" className="rounded-xl">
          <AlertTitle>{t("errorTitle")}</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : isLoading || !student ? (
        <div className="flex items-center gap-2 py-8">
          <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm text-muted-foreground">{t("loading")}</span>
        </div>
      ) : modules.length === 0 || !selectedModuleId ? (
        <>
          <StudentHeader student={student} />
          <div className="rounded-xl border-[0.5px] border-border bg-muted/30 py-16 text-center">
            <p className="text-sm text-muted-foreground">{t("noModules")}</p>
          </div>
        </>
      ) : (
        <>
          <StudentHeader student={student} />
          <StudentProfileContent
            student={student}
            modules={modules}
            selectedModuleId={selectedModuleId}
            onModuleChange={setSelectedModuleId}
          />
        </>
      )}
    </div>
  );
}

function StudentHeader({ student }: { student: StudentPublic }) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary/10 text-base font-medium text-primary">
        {student.first_name?.[0]?.toUpperCase() || <IconUser className="size-5" stroke={1.75} />}
      </div>
      <div>
        <h1 className="text-lg font-medium text-foreground">
          {student.first_name} {student.last_name}
        </h1>
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <StudentProfilePageInner />
    </AuthGuard>
  );
}
