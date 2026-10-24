import Image from "next/image";
import { getTranslations } from "next-intl/server";

import SignInForm from "@/components/landing/auth/signin-form";

export async function generateMetadata() {
  const t = await getTranslations("Auth.signIn");
  return { title: t("title") };
}

export default function SignIn() {
  return (
    <section className="flex min-h-[calc(100vh-5rem)] items-center justify-center px-4 py-8 sm:py-12">
      <div className="flex w-full max-w-2xl overflow-hidden rounded-3xl border border-slate-200/80 bg-white/95 shadow-2xl backdrop-blur-md lg:max-w-7xl xl:max-w-screen-xl">
        <div className="relative hidden lg:block lg:w-1/2 min-h-[720px] self-stretch">
          <Image
            src="/images/surface-DMVU0XqiT90-unsplash.jpg"
            alt="Étudiante travaillant sur sa copie"
            fill
            priority
            sizes="(max-width: 1024px) 0vw, 50vw"
            className="object-cover object-center"
          />
        </div>

        <div className="flex w-full flex-col justify-center px-8 py-12 sm:px-12 sm:py-16 md:px-16 lg:w-1/2">
          <SignInForm />
        </div>
      </div>
    </section>
  );
}
