"use client";

import { useEffect } from "react";
import { motion, stagger, useAnimate } from "motion/react";
import { cn } from "@/lib/utils";

export const TextGenerateEffect = ({
  words,
  className,
  filter = true,
  duration = 0.5,
}: {
  words: string;
  className?: string;
  filter?: boolean;
  duration?: number;
}) => {
  const [scope, animate] = useAnimate();
  const wordsArray = words.split(" ");

  useEffect(() => {
    animate(
      "span",
      {
        opacity: 1,
        filter: filter ? "blur(0px)" : "none",
      },
      {
        duration: duration ? duration : 1,
        delay: stagger(0.2),
      }
    );
  }, [scope.current]);

  // Le dégradé (bg-clip-text + text-transparent) ne se propage PAS
  // automatiquement sur les spans enfants — il faut l'appliquer inline
  // sur chaque span pour que le découpage CSS fonctionne correctement.
  const isGradient =
    className?.includes("text-transparent") ||
    className?.includes("bg-clip-text");

  const gradientStyle = isGradient
    ? {
        background: "linear-gradient(to right, #10b981, #34d399, #059669)",
        WebkitBackgroundClip: "text" as const,
        WebkitTextFillColor: "transparent" as const,
        backgroundClip: "text" as const,
      }
    : {};

  return (
    <div ref={scope} className={cn(className)}>
      {wordsArray.map((word, idx) => (
        <motion.span
          key={word + idx}
          className="opacity-0 inline-block"
          style={{
            filter: filter ? "blur(10px)" : "none",
            ...gradientStyle,
          }}
        >
          {word}&nbsp;
        </motion.span>
      ))}
    </div>
  );
};

