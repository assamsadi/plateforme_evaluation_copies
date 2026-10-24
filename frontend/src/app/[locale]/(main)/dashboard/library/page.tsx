"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useSearchParams } from "next/navigation";

import { BookOpen, Send } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AuthGuard } from "@/app/[locale]/(main)/dashboard/_components/auth-guard";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { SearchInput } from "@/components/ui/search-input";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  listModuleLibrary,
  getReferenceDocumentUrl,
  type AssignedExerciseRead,
  type SubmissionRead,
} from "@/lib/student-api";
import { cn } from "@/lib/utils";

import { SubmitExamDialog } from "../my-exams/_components/submit-exam-dialog";

const PAGE_SIZE = 200;

function ExerciseLibraryCard({
  exercise,
  isHighlighted,
  onSubmit,
}: {
  exercise: AssignedExerciseRead;
  isHighlighted: boolean;
  onSubmit: () => void;
}) {
  const t = useTranslations("LibraryPage");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [isFetchingUrl, setIsFetchingUrl] = useState(false);
  const [pdfFetchAttempted, setPdfFetchAttempted] = useState(false);

  // Chargement LAZY — uniquement déclenché sur action utilisateur,
  // jamais au montage (sinon N appels Azure simultanés pour N cartes).
  const fetchPdfUrl = async (): Promise<string | null> => {
    if (pdfUrl || pdfFetchAttempted) return pdfUrl; // déjà en cache local ou déjà tenté
    const session = getStoredSession();
    if (!session) return null;
    setIsFetchingUrl(true);
    try {
      const url = await getReferenceDocumentUrl(session.accessToken, exercise.id);
      setPdfUrl(url);
      setPdfFetchAttempted(true);
      return url;
    } catch (err) {
      console.error("Error fetching pdf url", err);
      setPdfFetchAttempted(true);
      return null;
    } finally {
      setIsFetchingUrl(false);
    }
  };

  const handleDownload = async () => {
    const url = await fetchPdfUrl();
    if (url) window.open(url, "_blank");
  };

  return (
    <Card
      className={cn(
        "overflow-hidden transition-all",
        isHighlighted
          ? "border-2 border-primary bg-emerald-50/30 shadow-md dark:bg-emerald-950/20"
          : "border-slate-200/90 shadow-2xs dark:border-zinc-800",
      )}
    >
      <div className="h-1 w-full bg-primary" />
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-bold text-slate-900 dark:text-zinc-100">{exercise.title}</h3>
            {exercise.difficulty_level && (
              <Badge variant="outline" className="text-xs font-medium">
                {exercise.difficulty_level}
              </Badge>
            )}
          </div>
          {exercise.description && (
            <p className="text-sm font-medium leading-relaxed text-slate-600 dark:text-zinc-300">
              {exercise.description}
            </p>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button
            size="sm"
            className="h-9 gap-2 rounded-xl bg-primary px-4 text-sm font-semibold text-white shadow-xs hover:bg-primary/90"
            onClick={onSubmit}
          >
            <Send className="size-3.5" />
            {t("submitAction")}
          </Button>

          {/* Bouton PDF — chargement lazy au premier clic et ouverture dans un nouvel onglet */}
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={isFetchingUrl}
            className="h-9 gap-2 rounded-xl font-semibold text-slate-700 dark:text-zinc-200"
            onClick={handleDownload}
          >
            {isFetchingUrl ? (
              <div className="size-3.5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            ) : (
              <BookOpen className="size-3.5 text-primary" />
            )}
            {t("viewPdfAction")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function LibraryPageContent() {
  const t = useTranslations("LibraryPage");
  const searchParams = useSearchParams();
  const moduleId = searchParams.get("module_id");
  const highlightExerciseId = searchParams.get("exercise_id");

  const [exercises, setExercises] = useState<AssignedExerciseRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitTarget, setSubmitTarget] = useState<AssignedExerciseRead | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchExercises = useCallback(async () => {
    if (!moduleId) return;
    const session = getStoredSession();
    if (!session) return;
    setIsLoading(true);
    setError(null);
    try {
      const page = await listModuleLibrary(session.accessToken, moduleId, { limit: PAGE_SIZE });
      setExercises(page.items);
    } catch (fetchError) {
      setError(fetchError instanceof AuthApiError ? fetchError.message : t("fetchError"));
    } finally {
      setIsLoading(false);
    }
  }, [moduleId, t]);

  useEffect(() => {
    fetchExercises();
  }, [fetchExercises]);

  function handleSubmitted() {
    toast.success(t("submitSuccess"));
  }

  const filteredExercises = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return exercises;
    return exercises.filter(
      (exercise) =>
        exercise.title.toLowerCase().includes(query) ||
        (exercise.description ?? "").toLowerCase().includes(query),
    );
  }, [exercises, searchQuery]);

  if (!moduleId) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 py-16 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
        <p className="text-base font-semibold text-slate-600 dark:text-zinc-400">{t("noModuleSelected")}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
            <BookOpen className="size-5" />
          </div>
          <h1 className="text-xl font-bold text-slate-900 dark:text-zinc-100">
            {t("title")}
            <span className="ml-2 inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-semibold text-muted-foreground align-middle">
              {exercises.length}
            </span>
          </h1>
        </div>
        <SearchInput
          className="w-full sm:w-64"
          placeholder={t("searchPlaceholder")}
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
      </div>

      {error ? (
        <Alert variant="destructive" className="rounded-2xl">
          <AlertTitle>Erreur</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : isLoading ? (
        <div className="flex items-center gap-2 py-8">
          <div className="size-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <span className="text-sm font-medium text-slate-500 dark:text-zinc-400">{t("loading")}</span>
        </div>
      ) : exercises.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 py-16 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
          <p className="text-base font-semibold text-slate-500 dark:text-zinc-400">{t("empty")}</p>
        </div>
      ) : filteredExercises.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-200 bg-slate-50/60 py-16 text-center dark:border-zinc-800 dark:bg-zinc-800/30">
          <p className="text-base font-semibold text-slate-500 dark:text-zinc-400">{t("noResults")}</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {filteredExercises.map((exercise) => (
            <ExerciseLibraryCard
              key={exercise.id}
              exercise={exercise}
              isHighlighted={exercise.id === highlightExerciseId}
              onSubmit={() => setSubmitTarget(exercise)}
            />
          ))}
        </div>
      )}

      <SubmitExamDialog
        exercise={submitTarget}
        open={Boolean(submitTarget)}
        onOpenChange={(open) => !open && setSubmitTarget(null)}
        onSubmitted={handleSubmitted}
      />
    </div>
  );
}

export default function Page() {
  return (
    <AuthGuard requiredRole="student">
      <LibraryPageContent />
    </AuthGuard>
  );
}
