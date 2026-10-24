import type { ReactNode } from "react";

import "@/styles/landing/style.css";
import "@fontsource/pacifico";
import "@fontsource-variable/noto-sans";
import "@fontsource-variable/playfair-display/wght.css";
import "@fontsource-variable/montserrat";
import "@fontsource-variable/cinzel";
import "@fontsource/satisfy";

import { Inter } from "next/font/google";
import localFont from "next/font/local";
import { getTranslations } from "next-intl/server";

import Header from "@/components/landing/ui/header";
import { routing } from "@/i18n/routing";
import { SITE_URL } from "@/lib/site";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

// Sous-titre du Hero uniquement (cf. son usage dans page.tsx) — jamais le
// corps de texte du reste du site. Chargée via @fontsource (@font-face
// globale nommée "Pacifico", cf. --font-pacifico dans style.css) plutôt que
// next/font/google, à la demande explicite.
const nacelle = localFont({
  src: [
    {
      path: "../../../../public/fonts/nacelle-regular.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../../../public/fonts/nacelle-italic.woff2",
      weight: "400",
      style: "italic",
    },
    {
      path: "../../../../public/fonts/nacelle-semibold.woff2",
      weight: "600",
      style: "normal",
    },
    {
      path: "../../../../public/fonts/nacelle-semibolditalic.woff2",
      weight: "600",
      style: "italic",
    },
  ],
  variable: "--font-nacelle",
  display: "swap",
});

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "Metadata" });
  return {
    metadataBase: new URL(SITE_URL),
    title: t("title"),
    description: t("description"),
    alternates: {
      languages: Object.fromEntries(routing.locales.map((loc) => [loc, `/${loc}`])),
    },
  };
}

export function generateStaticParams() {
  return routing.locales.map((locale) => ({ locale }));
}

// Pas de <html>/<body> ici : déjà fournis une seule fois par le layout
// racine ([locale]/layout.tsx), qui englobe aussi le dashboard. Ce layout
// écrase juste localement la police héritée du dashboard (fontVars) pour
// ce sous-arbre, via une div plutôt que le body. Pas d'AuthProvider non
// plus (déjà fourni par le parent) — ne pas doubler.
export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div
      className={`landing-root ${inter.variable} ${nacelle.variable} flex min-h-screen flex-col overflow-hidden bg-transparent font-inter text-base text-gray-800 antialiased supports-[overflow:clip]:overflow-clip`}
    >
      <Header />
      {children}
    </div>
  );
}
