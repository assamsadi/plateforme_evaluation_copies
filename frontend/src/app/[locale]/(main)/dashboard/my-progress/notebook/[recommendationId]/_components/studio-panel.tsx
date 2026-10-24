"use client";

import { useEffect, useRef, useState } from "react";

import {
  IconAlertTriangle,
  IconCards,
  IconMusic,
  IconLayoutGrid,
  IconMovie,
  IconRefresh,
  IconVideo,
  IconWaveSine,
  type Icon as TablerIcon,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AuthApiError, getStoredSession } from "@/lib/auth-api";
import {
  regenerateAudioOverview,
  regenerateFlashcards,
  requestVideoOverview,
  type GenerationStatus,
  type RecommendedExerciseRead,
  type VideoOverviewStatus,
} from "@/lib/student-api";

import { AudioPlayer } from "./audio-player";
import { FlashcardsCarousel } from "./flashcards-carousel";
import { VideoPlayer } from "./video-player";

const POLL_INTERVAL_MS = 5000;

// Bandeau générer/régénérer/pending/failed commun aux 3 formats — jamais
// un panneau vide sans explication (échec graceful, cf. demande) : pending
// -> Skeleton, failed -> message + bouton régénérer, sinon le player réel.
function FormatActionRow({
  status,
  isBusy,
  onRegenerate,
  generateLabel,
  regenerateLabel,
}: {
  status: GenerationStatus | VideoOverviewStatus;
  isBusy: boolean;
  onRegenerate: () => void;
  generateLabel: string;
  regenerateLabel: string;
}) {
  return (
    <Button
      type="button"
      size="sm"
      variant="skew"
      className="h-8 w-fit px-3 text-sm font-semibold tracking-wide"
      onClick={onRegenerate}
      disabled={isBusy || status === "pending"}
    >
      <IconRefresh className="size-3.5" stroke={1.75} />
      {status === "not_requested" ? generateLabel : regenerateLabel}
    </Button>
  );
}

function FormatFailedNotice({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2 text-sm font-medium text-destructive">
      <IconAlertTriangle className="size-4 shrink-0" stroke={1.75} />
      {message}
    </div>
  );
}

// État vide illustré (icône + texte) par format — jamais un simple texte
// gris plat, cohérent avec les icon-box teintées utilisées partout
// ailleurs dans l'app.
function FormatEmptyState({
  icon: Icon,
  label,
  toneClassName,
}: {
  icon: TablerIcon;
  label: string;
  toneClassName: string;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-border/60 bg-background/50 py-10 text-center">
      <div className={`flex size-12 items-center justify-center rounded-full border ${toneClassName}`}>
        <Icon className="size-5" stroke={1.5} />
      </div>
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  );
}

export function StudioPanel({
  recommendation,
  onRecommendationChange,
}: {
  recommendation: RecommendedExerciseRead;
  onRecommendationChange: (patch: Partial<RecommendedExerciseRead>) => void;
}) {
  const t = useTranslations("NotebookSheet");
  const [isRequestingVideo, setIsRequestingVideo] = useState(false);
  const [isRequestingAudio, setIsRequestingAudio] = useState(false);
  const [isRequestingFlashcards, setIsRequestingFlashcards] = useState(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [flashcardsError, setFlashcardsError] = useState<string | null>(null);

  async function handleRequestVideo() {
    const session = getStoredSession();
    if (!session) return;
    setIsRequestingVideo(true);
    setVideoError(null);
    try {
      const result = await requestVideoOverview(session.accessToken, recommendation.student_id, recommendation.id);
      onRecommendationChange({ video_overview_status: result.video_overview_status, video_overview_url: result.video_overview_url });
    } catch (requestError) {
      setVideoError(requestError instanceof AuthApiError ? requestError.message : t("videoError"));
    } finally {
      setIsRequestingVideo(false);
    }
  }

  async function handleRegenerateAudio() {
    const session = getStoredSession();
    if (!session) return;
    setIsRequestingAudio(true);
    setAudioError(null);
    try {
      const result = await regenerateAudioOverview(session.accessToken, recommendation.student_id, recommendation.id);
      onRecommendationChange({ audio_overview_status: result.audio_overview_status, audio_overview_url: result.audio_overview_url });
    } catch (requestError) {
      setAudioError(requestError instanceof AuthApiError ? requestError.message : t("audioError"));
    } finally {
      setIsRequestingAudio(false);
    }
  }

  async function handleRegenerateFlashcards() {
    const session = getStoredSession();
    if (!session) return;
    setIsRequestingFlashcards(true);
    setFlashcardsError(null);
    try {
      const result = await regenerateFlashcards(session.accessToken, recommendation.student_id, recommendation.id);
      onRecommendationChange({ flashcards_status: result.flashcards_status, flashcards_url: result.flashcards_url });
    } catch (requestError) {
      setFlashcardsError(requestError instanceof AuthApiError ? requestError.message : t("flashcardsError"));
    } finally {
      setIsRequestingFlashcards(false);
    }
  }

  // Polling — pendant qu'un format est PENDING, rappelle silencieusement le
  // même endpoint toutes les 5s (idempotent tant que PENDING, cf. docstring
  // RecommendationService.regenerate_*), même comportement que l'ancien
  // NotebookSheet.
  const recommendationRef = useRef(recommendation);
  recommendationRef.current = recommendation;

  useEffect(() => {
    const anyPending =
      recommendation.video_overview_status === "pending" ||
      recommendation.audio_overview_status === "pending" ||
      recommendation.flashcards_status === "pending";
    if (!anyPending) return;

    const interval = setInterval(async () => {
      const session = getStoredSession();
      const current = recommendationRef.current;
      if (!session) return;

      if (current.video_overview_status === "pending") {
        requestVideoOverview(session.accessToken, current.student_id, current.id)
          .then((result) => onRecommendationChange({ video_overview_status: result.video_overview_status, video_overview_url: result.video_overview_url }))
          .catch(() => undefined);
      }
      if (current.audio_overview_status === "pending") {
        regenerateAudioOverview(session.accessToken, current.student_id, current.id)
          .then((result) => onRecommendationChange({ audio_overview_status: result.audio_overview_status, audio_overview_url: result.audio_overview_url }))
          .catch(() => undefined);
      }
      if (current.flashcards_status === "pending") {
        regenerateFlashcards(session.accessToken, current.student_id, current.id)
          .then((result) => onRecommendationChange({ flashcards_status: result.flashcards_status, flashcards_url: result.flashcards_url }))
          .catch(() => undefined);
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recommendationRef porte la valeur fraîche
  }, [recommendation.video_overview_status, recommendation.audio_overview_status, recommendation.flashcards_status]);

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col border-l border-border/60 bg-slate-50/60 p-4 dark:bg-zinc-900/40 md:p-6">
      <span className="mb-3 shrink-0 text-xs font-bold tracking-wider text-muted-foreground uppercase">
        {t("studioTitle")}
      </span>

      <Tabs defaultValue="audio" className="min-h-0 flex-1">
        <TabsList className="w-full">
          <TabsTrigger value="audio" className="min-w-0">
            <IconMusic className="size-4 shrink-0 text-primary" stroke={1.75} />
            <span className="truncate">{t("audioTabLabel")}</span>
          </TabsTrigger>
          <TabsTrigger value="video" className="min-w-0">
            <IconVideo className="size-4 shrink-0 text-info" stroke={1.75} />
            <span className="truncate">{t("videoTabLabel")}</span>
          </TabsTrigger>
          <TabsTrigger value="flashcards" className="min-w-0">
            <IconLayoutGrid className="size-4 shrink-0 text-warning" stroke={1.75} />
            <span className="truncate">{t("flashcardsTabLabel")}</span>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="audio" className="flex flex-col gap-3 pt-4">
          {recommendation.audio_overview_status === "pending" ? (
            <Skeleton className="h-16 w-full rounded-xl" />
          ) : recommendation.audio_overview_url ? (
            <AudioPlayer src={recommendation.audio_overview_url} />
          ) : (
            <FormatEmptyState icon={IconWaveSine} label={t("audioEmpty")} toneClassName="border-primary/20 bg-primary/10 text-primary" />
          )}
          {recommendation.audio_overview_status === "failed" ? <FormatFailedNotice message={t("audioFailed")} /> : null}
          {audioError ? <FormatFailedNotice message={audioError} /> : null}
          <FormatActionRow
            status={recommendation.audio_overview_status}
            isBusy={isRequestingAudio}
            onRegenerate={handleRegenerateAudio}
            generateLabel={t("audioGenerateAction")}
            regenerateLabel={t("audioRegenerateAction")}
          />
        </TabsContent>

        <TabsContent value="video" className="flex flex-col gap-3 pt-4">
          {recommendation.video_overview_status === "pending" ? (
            <Skeleton className="aspect-video w-full rounded-xl" />
          ) : recommendation.video_overview_url ? (
            <VideoPlayer src={recommendation.video_overview_url} />
          ) : (
            <FormatEmptyState icon={IconMovie} label={t("videoEmpty")} toneClassName="border-info/20 bg-info/10 text-info" />
          )}
          {recommendation.video_overview_status === "failed" ? <FormatFailedNotice message={t("videoFailed")} /> : null}
          {videoError ? <FormatFailedNotice message={videoError} /> : null}
          <FormatActionRow
            status={recommendation.video_overview_status}
            isBusy={isRequestingVideo}
            onRegenerate={handleRequestVideo}
            generateLabel={t("videoRequestAction")}
            regenerateLabel={t("videoRegenerateAction")}
          />
        </TabsContent>

        <TabsContent value="flashcards" className="flex flex-col gap-3 pt-4">
          {recommendation.flashcards_status === "pending" ? (
            <Skeleton className="h-48 w-full rounded-xl" />
          ) : recommendation.flashcards_url ? (
            <FlashcardsCarousel url={recommendation.flashcards_url} />
          ) : (
            <FormatEmptyState icon={IconCards} label={t("flashcardsEmpty")} toneClassName="border-warning/20 bg-warning/10 text-warning" />
          )}
          {recommendation.flashcards_status === "failed" ? <FormatFailedNotice message={t("flashcardsFailed")} /> : null}
          {flashcardsError ? <FormatFailedNotice message={flashcardsError} /> : null}
          <FormatActionRow
            status={recommendation.flashcards_status}
            isBusy={isRequestingFlashcards}
            onRegenerate={handleRegenerateFlashcards}
            generateLabel={t("flashcardsGenerateAction")}
            regenerateLabel={t("flashcardsRegenerateAction")}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
