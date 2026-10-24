import { redirect } from "@/i18n/navigation";
import { routing } from "@/i18n/routing";

// Ancienne page autonome, jamais reliée au sidebar (gap documenté dans
// arbitration/_components/appeals-tab.tsx) — les recours de note vivent
// maintenant sous Arbitrage (cf. sidebar-items.ts), on redirige les liens
// existants plutôt que de dupliquer l'écran.
export default async function Page({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const typedLocale = routing.locales.includes(locale as (typeof routing.locales)[number])
    ? (locale as (typeof routing.locales)[number])
    : routing.defaultLocale;

  redirect({ href: "/dashboard/arbitration/appeals", locale: typedLocale });
}
