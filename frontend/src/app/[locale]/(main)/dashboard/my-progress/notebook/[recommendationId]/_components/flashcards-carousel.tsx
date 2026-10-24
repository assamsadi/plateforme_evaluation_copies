"use client";

import { useEffect, useState } from "react";

import { IconBulb, IconHelpCircle, IconRotate } from "@tabler/icons-react";
import { useTranslations } from "next-intl";

import { Skeleton } from "@/components/ui/skeleton";

interface FlashcardData {
  front: string;
  back: string;
}

// Format réel confirmé côté package notebooklm (_artifact/formatters.py,
// _format_interactive_content) : {"title": str, "cards": [{"front", "back"}]}
// — jamais un placeholder, mais on reste défensif (fetch cross-origin sur
// une URL signée, forme inattendue) : jamais un crash, un message clair
// avec un lien de repli à la place.
interface FlashcardsFile {
  title?: string;
  cards?: FlashcardData[];
}

function FlashcardTile({ card, index }: { card: FlashcardData; index: number }) {
  const t = useTranslations("NotebookSheet");
  const [isFlipped, setIsFlipped] = useState(false);

  return (
    <button
      type="button"
      onClick={() => setIsFlipped((prev) => !prev)}
      className="group h-60 w-full cursor-pointer [perspective:1200px] focus-visible:outline-none"
    >
      <div
        className={`relative size-full transition-transform duration-700 ease-out [transform-style:preserve-3d] group-hover:-translate-y-0.5 ${
          isFlipped ? "[transform:rotateY(180deg)]" : ""
        }`}
      >
        {/* Face avant : la question */}
        <div className="absolute inset-0 flex flex-col overflow-hidden rounded-2xl border border-primary/20 bg-gradient-to-br from-primary/10 via-background to-primary/5 p-5 text-center shadow-sm [backface-visibility:hidden] group-hover:shadow-lg group-hover:shadow-primary/10">
          <div className="pointer-events-none absolute -top-10 -right-10 size-32 rounded-full bg-primary/15 blur-2xl" />
          <div className="relative flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-bold tracking-wider text-primary uppercase">
              <IconHelpCircle className="size-4" stroke={2} />
              {t("flashcardFrontLabel")}
            </span>
            <span className="rounded-full bg-primary/15 px-2.5 py-0.5 font-mono text-xs font-bold text-primary tabular-nums">
              {String(index + 1).padStart(2, "0")}
            </span>
          </div>
          <p className="relative my-auto text-base leading-relaxed font-semibold text-foreground">{card.front}</p>
          <span className="relative flex items-center justify-center gap-1.5 text-xs font-medium text-muted-foreground">
            <IconRotate className="size-3.5 transition-transform duration-500 group-hover:rotate-180" stroke={1.75} />
            {t("flashcardFlipHint")}
          </span>
        </div>

        {/* Face arrière : la réponse */}
        <div className="absolute inset-0 flex flex-col overflow-hidden rounded-2xl bg-gradient-to-br from-primary to-primary/80 p-5 text-center text-primary-foreground shadow-lg shadow-primary/20 [backface-visibility:hidden] [transform:rotateY(180deg)]">
          <div className="pointer-events-none absolute -bottom-12 -left-12 size-40 rounded-full bg-white/10 blur-2xl" />
          <div className="relative flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-xs font-bold tracking-wider uppercase opacity-90">
              <IconBulb className="size-4" stroke={2} />
              {t("flashcardBackLabel")}
            </span>
            <span className="rounded-full bg-white/20 px-2.5 py-0.5 font-mono text-xs font-bold tabular-nums">
              {String(index + 1).padStart(2, "0")}
            </span>
          </div>
          <p className="relative my-auto text-sm leading-relaxed font-medium">{card.back}</p>
          <span className="relative flex items-center justify-center gap-1.5 text-xs font-medium opacity-80">
            <IconRotate className="size-3.5" stroke={1.75} />
            {t("flashcardFlipHint")}
          </span>
        </div>
      </div>
    </button>
  );
}

export function FlashcardsCarousel({ url }: { url: string }) {
  const t = useTranslations("NotebookSheet");
  const [cards, setCards] = useState<FlashcardData[] | null>(null);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setCards(null);
    setLoadError(false);

    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error("bad response");
        return response.json();
      })
      .then((data: FlashcardsFile) => {
        if (cancelled) return;
        if (!Array.isArray(data.cards)) throw new Error("unexpected shape");
        setCards(data.cards);
      })
      .catch(() => {
        if (!cancelled) setLoadError(true);
      });

    return () => {
      cancelled = true;
    };
  }, [url]);

  if (loadError) {
    return (
      <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border/60 p-6 text-center">
        <p className="text-sm text-muted-foreground">{t("flashcardsLoadError")}</p>
        <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm font-semibold text-primary hover:underline">
          {t("flashcardsAction")}
        </a>
      </div>
    );
  }

  if (!cards) {
    return <Skeleton className="h-60 w-full rounded-2xl" />;
  }

  if (cards.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border/60 p-6 text-center">
        <p className="text-sm text-muted-foreground">{t("flashcardsEmpty")}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {cards.map((card, index) => (
        <FlashcardTile key={index} card={card} index={index} />
      ))}
    </div>
  );
}
