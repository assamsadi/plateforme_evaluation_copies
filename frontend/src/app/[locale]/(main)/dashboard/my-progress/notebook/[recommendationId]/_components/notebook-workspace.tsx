"use client";

import { IconArrowLeft, IconSparkles } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Link } from "@/i18n/navigation";
import type { RecommendedExerciseRead } from "@/lib/student-api";

import { ChatPanel } from "./chat-panel";
import { SourcesPanel } from "./sources-panel";
import { StudioPanel } from "./studio-panel";

// Plein écran (data-content-padding=false annule le p-4/p-6 par défaut du
// layout dashboard, cf. app/[locale]/(main)/dashboard/layout.tsx) — les 3
// colonnes ont besoin de tout l'espace disponible, pas d'une page paddée
// comme le reste de l'espace étudiant.
export function NotebookWorkspace({
  recommendation,
  onRecommendationChange,
}: {
  recommendation: RecommendedExerciseRead;
  onRecommendationChange: (patch: Partial<RecommendedExerciseRead>) => void;
}) {
  const t = useTranslations("NotebookSheet");
  const tProgress = useTranslations("MyProgress");

  return (
    <div data-content-padding={false} className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-border/60 px-4 py-3 md:px-6">
        <Link
          href="/dashboard/my-progress"
          className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <IconArrowLeft className="size-4.5" stroke={1.75} />
        </Link>
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-primary/20 bg-primary/10 text-primary">
          <IconSparkles className="size-4" stroke={1.75} />
        </div>
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-sm font-semibold text-foreground">{t("title")}</span>
          <span className="truncate text-xs text-muted-foreground">
            {tProgress(`competency_${recommendation.competency_code}`)} · {recommendation.exercise_title}
          </span>
        </div>
      </div>

      {/* defaultSize/minSize/maxSize numériques sont interprétés en PIXELS par
          cette version de react-resizable-panels (pas en %, cf. ses types) —
          chaînes en "%" explicites obligatoires ici, sans quoi les panneaux
          s'effondrent à quelques pixels (bug constaté). */}
      <ResizablePanelGroup orientation="horizontal" className="flex-1">
        <ResizablePanel defaultSize="22%" minSize="18%" maxSize="32%">
          <SourcesPanel recommendation={recommendation} />
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize="48%" minSize="30%">
          <ChatPanel recommendation={recommendation} />
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize="30%" minSize="20%" maxSize="40%">
          <StudioPanel recommendation={recommendation} onRecommendationChange={onRecommendationChange} />
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
