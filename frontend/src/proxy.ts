import createMiddleware from "next-intl/middleware";

import { routing } from "@/i18n/routing";

// Next.js 16 a renommé le fichier "middleware.ts" en "proxy.ts" (export
// nommé `proxy` au lieu d'un export par défaut) — cf. src/proxy.disabled.ts,
// laissé par le template comme exemple inerte. next-intl/middleware retourne
// toujours une fonction de la forme attendue par cette convention, qu'elle
// s'appelle middleware ou proxy.
export const proxy = createMiddleware(routing);

export const config = {
  // Ne s'applique jamais aux assets statiques/API — uniquement aux routes de pages.
  matcher: ["/((?!api|_next|_vercel|.*\\..*).*)"],
};
