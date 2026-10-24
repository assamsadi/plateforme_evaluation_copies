import { redirect } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

// /dashboard n'est pas une page en soi — la redirection de next.config.mjs
// ("/dashboard" -> "/dashboard/default") ne matche que le chemin sans
// préfixe de locale et ne s'applique donc jamais en pratique (next-intl
// préfixe toujours la locale, ex. /fr/dashboard). Sans cette page, /fr/dashboard
// rendait un contenu vide au lieu de rediriger.
export default async function Page({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const typedLocale = routing.locales.includes(locale as (typeof routing.locales)[number])
    ? (locale as (typeof routing.locales)[number])
    : routing.defaultLocale;

  redirect({ href: "/dashboard/default", locale: typedLocale });
}
