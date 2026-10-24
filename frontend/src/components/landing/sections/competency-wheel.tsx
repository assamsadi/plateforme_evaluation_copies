import { getTranslations } from "next-intl/server";
import { CompetencyFaq, CompetencyData } from "./competency-faq";

const COMPETENCY_KEYS = [
  "dataAndPlanning",
  "decompositionAndOrganization",
  "algorithmicStructuring",
  "generalizationAndTransfer",
  "solutionCommunication",
  "selfEvaluationAndCreativity",
  "reflectionAndMetacognition",
] as const;

export default async function CompetencyWheel({ id = "competencies" }: { id?: string }) {
  const t = await getTranslations("CompetencyWheel");

  const competencies: CompetencyData[] = COMPETENCY_KEYS.map((key) => {
    // next-intl getTranslations returns arrays when key points to array in JSON
    const rawSubquestions = t.raw(`competencies.${key}.subquestions`);
    const subquestions = Array.isArray(rawSubquestions) ? rawSubquestions : [];

    return {
      key,
      title: t(`competencies.${key}.title`),
      subquestions,
    };
  });

  return (
    <section id={id} className="relative z-10 w-full font-montserrat py-16 sm:py-24 scroll-mt-32">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        {/* Section Header */}
        <div data-aos="fade-up" className="mx-auto max-w-3xl text-center">
          <span className="inline-block rounded-full border border-emerald-200 bg-emerald-50 px-5 py-2 text-sm font-bold uppercase tracking-widest text-emerald-700 sm:text-base">
            {t("badge")}
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

        {/* Accordéon des 7 compétences C2PCT */}
        <CompetencyFaq competencies={competencies} />
      </div>
    </section>
  );
}
