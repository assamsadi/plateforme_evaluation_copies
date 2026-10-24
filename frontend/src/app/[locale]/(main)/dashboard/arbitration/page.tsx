import { redirect } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

// Corrections/Incidents/Appeals sont maintenant des routes distinctes,
// exposées en sous-menu du sidebar (cf. sidebar-items.ts) plutôt qu'en
// onglets internes — /dashboard/arbitration seul ne rend donc plus rien,
// on redirige vers la première section.
export default async function Page({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const typedLocale = routing.locales.includes(locale as (typeof routing.locales)[number])
    ? (locale as (typeof routing.locales)[number])
    : routing.defaultLocale;

  redirect({ href: "/dashboard/arbitration/corrections", locale: typedLocale });
}
