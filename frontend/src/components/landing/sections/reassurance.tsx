import { getTranslations } from "next-intl/server";
import { GlowCards } from "./glow-cards";

const ITEM_KEYS = ["analysis", "validation", "traceability"] as const;

export default async function Reassurance({ id = "reassurance" }: { id?: string }) {
  const t = await getTranslations("Reassurance");

  const items = ITEM_KEYS.map((key) => ({
    key,
    title: t(`items.${key}.title`),
    description: t(`items.${key}.description`),
  }));

  return (
    <section id={id} className="relative z-10 w-full font-montserrat scroll-mt-32 py-16 sm:py-20">
      <div className="mx-auto max-w-[1600px] px-4 pb-28 pt-4 sm:px-8 lg:px-12">

        {/* En-tête de section */}
        <div
          data-aos="fade-up"
          className="mx-auto max-w-4xl text-center"
        >
          <span className="inline-block rounded-full border border-emerald-200 bg-emerald-50 px-5 py-2 text-sm font-bold uppercase tracking-widest text-emerald-700 sm:text-base">
            Notre approche
          </span>
          <h2 className="font-nacelle mt-5 text-4xl font-bold text-slate-900 sm:text-5xl md:text-6xl">
            {t("headline")}
          </h2>
          <p
            data-aos="fade-up"
            data-aos-delay={100}
            className="mt-5 text-xl sm:text-2xl leading-relaxed text-slate-600"
          >
            {t("subheadline")}
          </p>
        </div>

        {/* Grille de cartes avec effet lumineux */}
        <div data-aos="fade-up" data-aos-delay={200}>
          <GlowCards items={items} />
        </div>
      </div>
    </section>
  );
}
