import { fileURLToPath } from "node:url";

import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactCompiler: true,
  turbopack: {
    // Un second pnpm-lock.yaml traîne à la racine du dépôt (au-dessus de
    // frontend/) — Turbopack remonte l'arborescence pour deviner la racine
    // du projet, le trouve, l'ignore car "hors du dépôt Git" (avertissement
    // constaté au démarrage), et reste dans un état ambigu où des routes
    // pourtant réelles (fichiers page.tsx existants) retournent 404. Fixer
    // explicitement la racine sur frontend/ lève cette ambiguïté, cf. doc
    // node_modules/next/dist/docs/.../turbopack.md#root-directory.
    root: fileURLToPath(new URL(".", import.meta.url)),
  },
  compiler: {
    removeConsole: process.env.NODE_ENV === "production",
  },
  async redirects() {
    return [
      {
        source: "/dashboard",
        destination: "/dashboard/default",
        permanent: false,
      },
    ];
  },
};

export default withNextIntl(nextConfig);
