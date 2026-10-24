import { redirect } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

// Les trois sections (AI Models / API Keys & Langfuse / Settings) sont
// maintenant des routes distinctes, exposées en sous-menu du sidebar
// plutôt qu'en onglets internes à la page — /dashboard/system-config seul
// ne rend donc plus rien, on redirige vers la première section.
export default async function Page({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const typedLocale = routing.locales.includes(locale as (typeof routing.locales)[number])
    ? (locale as (typeof routing.locales)[number])
    : routing.defaultLocale;

  redirect({ href: "/dashboard/system-config/models", locale: typedLocale });
}
