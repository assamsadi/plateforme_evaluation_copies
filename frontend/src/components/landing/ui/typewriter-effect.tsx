"use client";

import { cn } from "@/lib/utils";
import { motion, stagger, useAnimate, useInView } from "motion/react";
import { useEffect } from "react";

export const TypewriterEffect = ({
  words,
  className,
  cursorClassName,
  showCursor = true,
  onComplete,
}: {
  words: {
    text: string;
    className?: string;
  }[];
  className?: string;
  cursorClassName?: string;
  // Masque le curseur clignotant (ligne déjà terminée dans un enchaînement
  // séquentiel de plusieurs lignes — cf. showCursor sur TypewriterEffectSmooth,
  // même principe).
  showCursor?: boolean;
  // Appelé une fois TOUS les caractères réellement révélés (la promesse
  // retournée par animate() de Framer Motion se résout à la toute fin de
  // l'animation, jamais un délai deviné à l'avance) — permet à un appelant
  // de monter la ligne suivante seulement quand celle-ci a fini de s'écrire,
  // quel que soit le nombre réel de caractères de cette ligne précise.
  onComplete?: () => void;
}) => {
  // split text inside of words into array of characters
  const wordsArray = words.map((word) => {
    return {
      ...word,
      text: word.text.split(""),
    };
  });

  const [scope, animate] = useAnimate();
  const isInView = useInView(scope);
  useEffect(() => {
    if (isInView) {
      animate(
        "span",
        {
          display: "inline-block",
          opacity: 1,
          width: "fit-content",
        },
        {
          duration: 0.3,
          delay: stagger(0.1),
          ease: "easeInOut",
        }
      ).then(() => {
        onComplete?.();
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isInView]);

  const renderWords = () => {
    return (
      <motion.div ref={scope} className="inline">
        {wordsArray.map((word, idx) => {
          const hasCustomColor =
            word.className?.includes("text-") ||
            word.className?.includes("bg-clip-text");

          return (
            <div key={`word-${idx}`} className="inline-block">
              {word.text.map((char, index) => (
                <motion.span
                  initial={{}}
                  key={`char-${index}`}
                  className={cn(
                    "opacity-0 hidden",
                    !hasCustomColor && "dark:text-white text-black",
                    word.className
                  )}
                >
                  {char}
                </motion.span>
              ))}
              &nbsp;
            </div>
          );
        })}
      </motion.div>
    );
  };
  return (
    <div
      className={cn(
        "text-base sm:text-xl md:text-3xl lg:text-5xl font-bold text-center",
        className
      )}
    >
      {renderWords()}
      {showCursor && (
        <motion.span
          initial={{
            opacity: 0,
          }}
          animate={{
            opacity: 1,
          }}
          transition={{
            duration: 0.8,
            repeat: Infinity,
            repeatType: "reverse",
          }}
          className={cn(
            "inline-block rounded-sm w-[4px] h-4 md:h-6 lg:h-10 bg-blue-500",
            cursorClassName
          )}
        ></motion.span>
      )}
    </div>
  );
};

export const TypewriterEffectSmooth = ({
  words,
  className,
  cursorClassName,
  delay = 1,
  showCursor = true,
}: {
  words: {
    text: string;
    className?: string;
  }[];
  className?: string;
  cursorClassName?: string;
  // Permet d'enchaîner plusieurs instances l'une après l'autre (ex. un
  // sous-titre coupé en plusieurs lignes courtes, chacune sa propre
  // instance) — 1 par défaut, comportement inchangé pour tout appel
  // existant qui ne passe pas cette prop.
  delay?: number;
  // Masque le curseur clignotant — utile quand plusieurs instances
  // s'enchaînent : seule celle en train de s'écrire doit garder un
  // curseur, les lignes déjà terminées non (sinon plusieurs curseurs
  // clignotent en même temps, incohérent avec "une seule ligne à la fois").
  showCursor?: boolean;
}) => {
  // split text inside of words into array of characters
  const wordsArray = words.map((word) => {
    return {
      ...word,
      text: word.text.split(""),
    };
  });
  const renderWords = () => {
    return (
      <div>
        {wordsArray.map((word, idx) => {
          return (
            <div key={`word-${idx}`} className="inline-block">
              {word.text.map((char, index) => (
                <span
                  key={`char-${index}`}
                  className={cn(`dark:text-white text-black `, word.className)}
                >
                  {char}
                </span>
              ))}
              &nbsp;
            </div>
          );
        })}
      </div>
    );
  };

  return (
    <div className="flex space-x-1 my-6">
      <motion.div
        className="overflow-hidden pb-2"
        initial={{
          width: "0%",
        }}
        whileInView={{
          width: "fit-content",
        }}
        transition={{
          duration: 2,
          ease: "linear",
          delay,
        }}
      >
        <div
          className={cn("text-xs sm:text-base md:text-xl lg:text-3xl xl:text-5xl font-bold", className)}
          style={{
            whiteSpace: "nowrap",
          }}
        >
          {renderWords()}{" "}
        </div>{" "}
      </motion.div>
      {showCursor && (
        <motion.span
          initial={{
            opacity: 0,
          }}
          animate={{
            opacity: 1,
          }}
          transition={{
            duration: 0.8,

            repeat: Infinity,
            repeatType: "reverse",
          }}
          className={cn(
            "block rounded-sm w-[4px]  h-4 sm:h-6 xl:h-12 bg-blue-500",
            cursorClassName
          )}
        ></motion.span>
      )}
    </div>
  );
};
