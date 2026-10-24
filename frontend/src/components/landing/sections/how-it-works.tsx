"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

// Étiquettes courtes du template original ("Depth"/"Ambient"/"Portable"/
// "Yours") décrivaient le SLIDER lui-même (un composant à vendre) — aucun
// équivalent réel côté plateforme pour ce mot précis. Remplacées par un
// simple numéro d'étape, jamais par une redite du titre déjà affiché juste
// en dessous (aurait été redondant).
// Teintes -300 d'origine restaurées : la carte reste sombre (cf. plus bas,
// bg-gray-900/85) même si la SECTION est blanche — sans ça, bg-white/[0.06]
// (verre dépoli conçu pour un fond sombre) deviendrait invisible sur blanc.
// Accents adaptés pour fond clair (versions saturées lisibles sur blanc)
const ACCENTS = ["text-fuchsia-500", "text-cyan-500", "text-amber-500", "text-violet-500"];

export default function HowItWorks({ id = "how-it-works" }: { id?: string }) {
  const t = useTranslations("HowItWorks");
  const stageRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [active, setActive] = useState(0);
  const [stageWidth, setStageWidth] = useState(0);

  const steps = [1, 2, 3, 4].map((num) => ({
    id: num,
    tag: t(`steps.step${num}.tag`),
    title: t(`steps.step${num}.title`),
    description: t(`steps.step${num}.description`),
  }));

  useEffect(() => {
    function measure() {
      if (stageRef.current) setStageWidth(stageRef.current.offsetWidth);
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  function startAutoplay() {
    stopAutoplay();
    timerRef.current = setInterval(() => setActive((prev) => (prev + 1) % steps.length), 5000);
  }
  function stopAutoplay() {
    if (timerRef.current) clearInterval(timerRef.current);
  }

  useEffect(() => {
    startAutoplay();
    return stopAutoplay;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function goTo(i: number) {
    setActive((i + steps.length) % steps.length);
    startAutoplay();
  }

  const spacing = Math.max(340, stageWidth * 0.65);

  return (
    /* Section transparente pour laisser transparaître le background gradient de la landing page */
    <section
      id={id}
      className="relative z-10 w-full overflow-hidden py-24 font-sans scroll-mt-32"
    >
      <div className="relative z-10 mx-auto flex max-w-7xl flex-col items-center px-4 sm:px-6 lg:px-8">
        {/* En-tête de section */}
        <div data-aos="fade-up" className="mx-auto mb-16 max-w-4xl text-center">
          <span className="inline-block rounded-full border border-emerald-200 bg-emerald-50 px-5 py-2 text-sm font-bold uppercase tracking-widest text-emerald-700 sm:text-base">
            Fonctionnement
          </span>
          <h2 className="font-nacelle mt-5 text-4xl font-bold text-slate-900 sm:text-5xl md:text-6xl">
            {t("headline")}
          </h2>
          <p className="mt-5 text-xl sm:text-2xl leading-relaxed text-slate-600">
            {t("subheadline")}
          </p>
        </div>

        {/* Stage 3D aéré avec cartes grand format (+3cm de chaque côté) */}
        <div
          ref={stageRef}
          onMouseEnter={stopAutoplay}
          onMouseLeave={startAutoplay}
          className="relative h-[480px] w-full max-w-xl [perspective:2000px] sm:h-[540px] sm:max-w-3xl md:h-[580px] md:max-w-5xl lg:max-w-6xl"
        >
          <div className="absolute inset-0 [transform-style:preserve-3d]">
            {steps.map((step, i) => {
              let offset = i - active;
              if (offset > steps.length / 2) offset -= steps.length;
              if (offset < -steps.length / 2) offset += steps.length;
              const abs = Math.abs(offset);
              const tx = offset * spacing;
              const tz = -abs * 180;
              const ry = offset * -20;
              const scale = 1 - abs * 0.08;
              const opacity = abs > 2 ? 0 : 1 - abs * 0.16;

              return (
                <div
                  key={step.id}
                  /* Cartes élargies de ~3cm par côté (w-[380px] sm:w-[500px] md:w-[620px] lg:w-[680px]) avec espacement aéré */
                  className="absolute left-1/2 top-1/2 w-[340px] rounded-3xl border-2 border-white/80 bg-white/75 p-8 shadow-[0_20px_50px_rgba(100,116,139,0.15)] backdrop-blur-xl sm:w-[480px] sm:p-11 md:w-[600px] md:p-14 lg:w-[680px]"
                  style={{
                    transform: `translate(-50%,-50%) translate3d(${tx}px,0,${tz}px) rotateY(${ry}deg) scale(${scale})`,
                    opacity,
                    zIndex: 50 - abs,
                    pointerEvents: abs === 0 ? "auto" : "none",
                    transition: "transform 0.65s cubic-bezier(0.25, 1, 0.5, 1), opacity 0.65s ease",
                  }}
                >
                  <span className={`font-mono text-sm sm:text-base font-bold uppercase tracking-[0.2em] ${ACCENTS[i]}`}>
                    {String(step.id).padStart(2, "0")} / {step.tag}
                  </span>
                  <h2 className="mt-5 font-nacelle text-3xl font-bold leading-tight text-slate-900 sm:text-4xl md:text-5xl">
                    {step.title}
                  </h2>
                  <p className="mt-6 text-lg sm:text-xl leading-relaxed text-slate-600">
                    {step.description}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Flèches de navigation positionnées à l'extérieur des grandes cartes */}
          <button
            type="button"
            aria-label="Previous slide"
            onClick={() => goTo(active - 1)}
            className="absolute -left-3 sm:-left-6 md:-left-10 lg:-left-14 top-1/2 z-30 -translate-y-1/2 rounded-full border border-slate-200/80 bg-white/80 p-3.5 sm:p-4 text-slate-700 shadow-xl backdrop-blur-md transition hover:bg-white hover:text-emerald-700 hover:scale-110 active:scale-95"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <button
            type="button"
            aria-label="Next slide"
            onClick={() => goTo(active + 1)}
            className="absolute -right-3 sm:-right-6 md:-right-10 lg:-right-14 top-1/2 z-30 -translate-y-1/2 rounded-full border border-slate-200/80 bg-white/80 p-3.5 sm:p-4 text-slate-700 shadow-xl backdrop-blur-md transition hover:bg-white hover:text-emerald-700 hover:scale-110 active:scale-95"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
        </div>

        {/* Indicateurs de pagination (Dots) */}
        <div className="relative z-20 mt-12 flex items-center gap-3.5">
          {steps.map((step, i) => (
            <button
              key={step.id}
              type="button"
              aria-label={`Go to slide ${i + 1}`}
              onClick={() => goTo(i)}
              className={`h-3 rounded-full transition-all duration-300 ${i === active ? "w-9 bg-emerald-600 shadow-md" : "w-3 bg-slate-300 hover:bg-slate-400"}`}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
