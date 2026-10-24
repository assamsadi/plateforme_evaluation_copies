import { getTranslations } from "next-intl/server";

import { ShimmerButton } from "@/components/landing/ui/shimmer-button";

export default async function FinalCta({ id = "get-started" }: { id?: string }) {
  const t = await getTranslations("FinalCta");

  return (
    <section id={id} className="relative z-10 w-full py-20 sm:py-28 scroll-mt-32">
      <div className="mx-auto flex max-w-4xl flex-col items-center px-4 text-center">
        <span
          data-aos="fade-up"
          className="inline-block rounded-full border border-emerald-200 bg-emerald-50 px-5 py-2 text-sm font-bold uppercase tracking-widest text-emerald-700 sm:text-base"
        >
          {t("badge")}
        </span>

        <h2
          data-aos="fade-up"
          data-aos-delay={100}
          className="mt-5 bg-gradient-to-r from-[#10b981] via-[#34d399] to-[#059669] bg-clip-text font-nacelle text-4xl font-bold text-transparent sm:text-5xl md:text-6xl"
        >
          {t("headline")}
        </h2>

        <p
          data-aos="fade-up"
          data-aos-delay={150}
          className="mt-5 max-w-2xl text-xl sm:text-2xl leading-relaxed text-slate-600"
        >
          {t("subheadline")}
        </p>

        <div data-aos="fade-up" data-aos-delay={250} className="mt-10">
          <ShimmerButton
            background="linear-gradient(135deg, #059669 0%, #10b981 50%, #34d399 100%)"
            shimmerColor="#a7f3d0"
            className="rounded-full text-lg sm:text-xl font-bold text-white px-8 py-3.5 shadow-lg"
          >
            {t("cta")}
          </ShimmerButton>
        </div>
      </div>
    </section>
  );
}
