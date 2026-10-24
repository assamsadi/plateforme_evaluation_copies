"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useParams } from "next/navigation";

import { IconArrowLeft } from "@tabler/icons-react";
import { User, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { Link, useRouter } from "@/i18n/navigation";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import { listCourseStudents, listMyCourses, type CourseRead, type StudentPublic } from "@/lib/professor-api";

const PAGE_SIZE = 200;

function StudentsPageContent() {
  const t = useTranslations("StudentsSheet");
  const { courseId } = useParams<{ courseId: string }>();
  const router = useRouter();
  const [course, setCourse] = useState<CourseRead | null>(null);
  const [students, setStudents] = useState<StudentPublic[]>([]);
  const [search, setSearch] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const [coursesPage, studentsResult] = await Promise.all([
        listMyCourses(session.accessToken, { limit: PAGE_SIZE }),
        listCourseStudents(session.accessToken, courseId),
      ]);
      setCourse(coursesPage.items.find((c) => c.id === courseId) ?? null);
      setStudents(studentsResult);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [courseId, t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const filteredStudents = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return students;
    return students.filter((student) => {
      const haystack = `${student.first_name} ${student.last_name} ${student.student_number}`.toLowerCase();
      return haystack.includes(query);
    });
  }, [students, search]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center gap-2">
        <Link
          href="/dashboard/my-courses"
          className="inline-flex items-center gap-1.5 rounded-lg border bg-background px-3 py-1.5 text-sm text-muted-foreground shadow-2xs transition-colors hover:bg-muted hover:text-foreground"
        >
          <IconArrowLeft className="size-4" stroke={1.75} />
          {t("backToCourses")}
        </Link>
      </div>

      {error ? (
        <Alert variant="destructive" className="rounded-2xl">
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : (
        <Card className="overflow-hidden">
          <div className="h-1 w-full bg-primary" />
          <CardHeader className="border-b border-slate-100/80 pb-4 pt-4 dark:border-zinc-800/80 has-data-[slot=card-action]:grid-cols-1 md:has-data-[slot=card-action]:grid-cols-[1fr_auto]">
            <div className="flex items-center gap-2.5">
              <div className="flex size-8 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
                <Users className="size-4" />
              </div>
              <div>
                <CardTitle className="text-base font-semibold leading-none text-slate-900 dark:text-zinc-100">
                  {t("title", { module: course?.module_name ?? "" })}
                  <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                    {students.length}
                  </span>
                </CardTitle>
                <CardDescription className="mt-0.5 text-xs">{course?.group_label}</CardDescription>
              </div>
            </div>
            <CardAction className="col-start-1 row-start-auto flex w-full flex-wrap justify-start gap-2 justify-self-stretch md:col-start-2 md:row-span-2 md:row-start-1 md:w-auto md:flex-nowrap md:justify-end md:justify-self-end md:self-center">
              <SearchInput
                className="w-full md:w-64"
                placeholder={t("searchPlaceholder")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </CardAction>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 pt-4">
            {isLoading ? (
              <div className="flex items-center gap-2 py-8 justify-center">
                <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
                <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</p>
              </div>
            ) : filteredStudents.length === 0 ? (
              <div className="rounded-xl border border-slate-100 bg-slate-50/60 py-8 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
                <p className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("empty")}</p>
              </div>
            ) : (
              filteredStudents.map((student) => (
                <div
                  key={student.id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-slate-200/80 bg-slate-50/60 p-3.5 transition-colors hover:border-primary/40 hover:bg-emerald-50/20 dark:border-zinc-800 dark:bg-zinc-900/60"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="flex size-9 shrink-0 items-center justify-center rounded-full bg-slate-200 text-sm font-bold text-slate-800 dark:bg-zinc-800 dark:text-zinc-200">
                      {student.first_name?.[0]?.toUpperCase() || <User className="size-4" />}
                    </div>
                    <div className="min-w-0 truncate">
                      <div className="truncate text-sm font-bold text-slate-900 dark:text-zinc-100">
                        {student.first_name} {student.last_name}
                      </div>
                      <div className="font-mono text-xs font-semibold text-slate-500 dark:text-zinc-400">{student.student_number}</div>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="skew"
                    className="h-8 shrink-0 px-3 text-sm font-semibold tracking-wide"
                    onClick={() => router.push(`/dashboard/my-courses/${courseId}/students/${student.id}/profile`)}
                  >
                    {t("viewProfileAction")}
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="professor">
      <StudentsPageContent />
    </AuthGuard>
  );
}
