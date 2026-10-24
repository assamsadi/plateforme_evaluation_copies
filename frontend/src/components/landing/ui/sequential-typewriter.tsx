"use client";

import { useState } from "react";

import { TypewriterEffect } from "./typewriter-effect";

// Écrit une ligne caractère par caractère (effet clavier, via TypewriterEffect
// — jamais TypewriterEffectSmooth, qui révèle la ligne d'un bloc en faisant
// grandir une largeur, pas mot par mot), ATTEND la fin RÉELLE de cette
// écriture (callback onComplete de TypewriterEffect, jamais un délai deviné
// à l'avance — chaque ligne a un nombre de caractères différent), PUIS
// monte la suivante. Jamais deux lignes qui s'écrivent en même temps.
export function SequentialTypewriter({
  segments,
  className,
  cursorClassName,
}: {
  segments: { text: string; className?: string }[][];
  className?: string;
  cursorClassName?: string;
}) {
  const [visibleCount, setVisibleCount] = useState(1);

  return (
    <div className="flex flex-col items-center gap-1">
      {segments.slice(0, visibleCount).map((segmentWords, index) => (
        <TypewriterEffect
          key={index}
          words={segmentWords}
          showCursor={index === visibleCount - 1}
          onComplete={
            index === visibleCount - 1 && visibleCount < segments.length
              ? () => setVisibleCount((prev) => prev + 1)
              : undefined
          }
          className={className}
          cursorClassName={cursorClassName}
        />
      ))}
    </div>
  );
}
