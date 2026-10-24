import { defineRouting } from "next-intl/routing";

// Préfixe "always" : landing (/, /signin, /signup...) et le dashboard
// (/dashboard/...) partagent la même app et le même routing i18n.
export const routing = defineRouting({
  locales: ["fr", "en", "es"],
  defaultLocale: "fr",
  localePrefix: "always",
});

export type Locale = (typeof routing.locales)[number];
