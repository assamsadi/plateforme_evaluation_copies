import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      // Espace admin — jamais public, quel que soit la locale. Absent de
      // l'app landing d'origine (dont robots.ts a été porté ici tel quel) :
      // ajouté maintenant que landing et dashboard partagent la même app.
      disallow: ["/*/dashboard", "/*/dashboard/*", "/*/unauthorized"],
    },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
