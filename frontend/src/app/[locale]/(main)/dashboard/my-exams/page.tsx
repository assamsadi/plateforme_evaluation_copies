"use client";

import { useCallback, useEffect, useState } from "react";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  getMyStats,
  listAssignedExercises,
  listMySubmissions,
  type AssignedExerciseRead,
  type StudentStats,
  type SubmissionRead,
} from "@/lib/student-api";

import { MyExams, type ExamRow } from "./_components/my-exams";
import { MyStatsStrip } from "./_components/my-stats-strip";
import { SubmissionDetailDialog } from "./_components/submission-detail-dialog";
import { SubmitExamDialog } from "./_components/submit-exam-dialog";

const PAGE_SIZE = 200;

function MyExamsPageContent() {
  const t = useTranslations("MyExams");
  const [exercises, setExercises] = useState<AssignedExerciseRead[]>([]);
  const [submissions, setSubmissions] = useState<SubmissionRead[]>([]);
  const [stats, setStats] = useState<StudentStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitTarget, setSubmitTarget] = useState<AssignedExerciseRead | null>(null);
  const [detailTarget, setDetailTarget] = useState<SubmissionRead | null>(null);

  const fetchData = useCallback(async () => {
    const session = getStoredSession();
    if (!session) return;

    setIsLoading(true);
    setError(null);
    try {
      const [exercisesPage, submissionsPage] = await Promise.all([
        listAssignedExercises(session.accessToken, { limit: PAGE_SIZE }),
        listMySubmissions(session.accessToken, { limit: PAGE_SIZE }),
      ]);
      setExercises(exercisesPage.items);
      setSubmissions(submissionsPage.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }

    // Non-bloquant : un échec des statistiques ne doit jamais empêcher
    // l'affichage de la liste des examens, qui est le contenu principal
    // de cette page.
    try {
      const statsResult = await getMyStats(session.accessToken);
      setStats(statsResult);
    } catch {
      setStats(null);
    }
  }, [t]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  function handleSubmitted(submission: SubmissionRead) {
    setSubmissions((prev) => [submission, ...prev]);
    toast.success(t("submitSuccess"));
  }

  if (error) {
    return (
      <Alert variant="destructive">
        <AlertTitle>Erreur</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-16 w-full" />
        {Array.from({ length: 3 }, (_, index) => (
          <Skeleton key={index} className="h-28 w-full" />
        ))}
      </div>
    );
  }

  // Un étudiant ne dépose qu'une seule tentative pour un examen/devoir
  // (AlreadySubmittedError côté backend, cf. SubmissionService.
  // create_submission) — la dernière soumission de chaque exercice suffit
  // donc pour représenter son état, jamais un historique de plusieurs
  // tentatives ici (contrairement à ARCHIVED_IN_LIBRARY, hors périmètre de
  // cette page assignée).
  const rows: ExamRow[] = exercises.map((exercise) => ({
    exercise,
    submission: submissions.find((s) => s.exercise_id === exercise.id) ?? null,
  }));

  return (
    <>
      <div className="mb-4">
        <MyStatsStrip stats={stats} />
      </div>
      <MyExams
        rows={rows}
        onSubmit={setSubmitTarget}
        onViewSubmission={setDetailTarget}
      />
      <SubmitExamDialog
        exercise={submitTarget}
        open={Boolean(submitTarget)}
        onOpenChange={(open) => !open && setSubmitTarget(null)}
        onSubmitted={handleSubmitted}
      />
      <SubmissionDetailDialog
        submission={detailTarget}
        open={Boolean(detailTarget)}
        onOpenChange={(open) => !open && setDetailTarget(null)}
      />
    </>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="student">
      <MyExamsPageContent />
    </AuthGuard>
  );
}
