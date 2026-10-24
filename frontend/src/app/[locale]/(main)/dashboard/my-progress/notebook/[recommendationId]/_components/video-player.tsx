"use client";

import { AspectRatio } from "@/components/ui/aspect-ratio";

// Cadre Aspect Ratio propre (16:9) — contrôles natifs du <video> (pas de
// nouvelle dépendance Vidstack/Plyr, même choix que AudioPlayer), juste un
// cadre soigné autour plutôt qu'un <video> nu.
export function VideoPlayer({ src }: { src: string }) {
  return (
    <AspectRatio ratio={16 / 9} className="overflow-hidden rounded-xl border border-border/60 bg-black">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- vidéo générée (NotebookLM), aucune piste de sous-titres disponible */}
      <video src={src} controls className="size-full" />
    </AspectRatio>
  );
}
