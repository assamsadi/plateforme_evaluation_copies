import Image from "next/image";
import { Link } from "@/i18n/navigation";
import { getTranslations } from "next-intl/server";

import SignUpForm from "@/components/landing/auth/signup-form";

export async function generateMetadata() {
  const t = await getTranslations("Auth.signUp");
  return { title: t("title") };
}

export default async function SignUp() {
  const t = await getTranslations("Auth.signUp");

  return (
    <section className="flex min-h-[calc(100vh-5rem)] w-full items-center justify-center px-4 py-8 sm:px-8 sm:py-12">
      {/* Cadre grand format avec fond verre dépoli et ombre */}
      <div className="flex w-full max-w-3xl overflow-hidden rounded-3xl border border-slate-200/80 bg-white/95 shadow-2xl backdrop-blur-md lg:max-w-7xl xl:max-w-screen-xl">
        {/* Même image que la page signin */}
        <div className="relative hidden lg:block lg:w-1/2 self-stretch">
          <Image
            src="/images/surface-DMVU0XqiT90-unsplash.jpg"
            alt="Étudiante travaillant sur sa copie"
            fill
            priority
            sizes="(max-width: 1024px) 0vw, 50vw"
            className="object-cover object-center"
          />
        </div>

        {/* Côté formulaire — plus large pour des inputs spacieux */}
        <div className="flex w-full flex-col justify-center px-8 py-10 sm:px-10 sm:py-12 lg:px-12 lg:py-14 lg:w-1/2">
          <div className="w-full">
            <div className="mb-6 flex justify-center">
              <Image
                src="/images/logo-c2pct.png"
                alt="C2PCT Assess"
                width={300}
                height={110}
                className="h-24 w-auto object-contain"
                priority
              />
            </div>
            <h1 className="font-nacelle text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 text-center">
              {t("title")}
            </h1>

            <SignUpForm />
          </div>
        </div>
      </div>
    </section>
  );
}
