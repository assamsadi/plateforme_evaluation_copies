import { getTranslations, setRequestLocale } from "next-intl/server";

import { SequentialTypewriter } from "@/components/landing/ui/sequential-typewriter";
import { BackgroundGradientAnimation } from "@/components/ui/background-gradient-animation";
import Reassurance from "@/components/landing/sections/reassurance";
import HowItWorks from "@/components/landing/sections/how-it-works";
import CompetencyWheel from "@/components/landing/sections/competency-wheel";
import FinalCta from "@/components/landing/sections/final-cta";

export default async function Home({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations("Hero");

  // Sous-titre coupé en 3 courts segments empilés (contrainte nowrap de
  // TypewriterEffectSmooth, cf. mémoire de session) — montés un par un via
  // SequentialTypewriter, jamais les 3 présents d'avance. Dernier mot de
  // chaque segment en vert émeraude, même logique que le titre.
  const subheadlineSegments = [t("subheadlineLine1"), t("subheadlineLine2"), t("subheadlineLine3")].map((segment) => {
    const segmentParts = segment.split(" ");
    return segmentParts.map((word, index) => ({
      text: word,
      className:
        index === segmentParts.length - 1 ||
        word === "plateforme" ||
        word === "transforme" ||
        word === "évaluation"
          ? "font-satisfy text-emerald-600 dark:text-emerald-600"
          : "text-slate-700 dark:text-slate-700",
    }));
  });
  return (
    <div className="relative flex min-h-screen w-full flex-col items-center text-slate-950">
      {/* Background Gradient Animation Aceternity fixé en arrière-plan (palette claire, éléments 100% visibles) */}
      <BackgroundGradientAnimation
        containerClassName="fixed inset-0 -z-10 h-full w-full pointer-events-none"
        interactive={true}
      />

      <div id="hero" className="relative z-10 mx-auto flex min-h-screen w-full max-w-4xl flex-col items-center justify-center px-4 pb-32 text-center scroll-mt-24">
        <SequentialTypewriter
          segments={subheadlineSegments}
          className="font-cinzel text-2xl font-bold leading-tight sm:text-3xl md:text-4xl"
          cursorClassName="bg-slate-400 h-4 sm:h-6"
        />
      </div>

      <Reassurance id="reassurance" />
      <HowItWorks id="how-it-works" />
      <CompetencyWheel id="competencies" />
      <FinalCta id="get-started" />
    </div>
  );
}
