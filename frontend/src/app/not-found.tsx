import Link from "next/link";

import { Button } from "@/components/ui/button";

import "./globals.css";

// Fallback GLOBAL (hors du segment [locale]) : ne déclenché que pour un
// chemin qui ne matche même pas une locale valide. Doit fournir ses propres
// <html>/<body> — aucun layout parent ne les fournit à ce niveau (le seul
// layout de l'app vit sous app/[locale]/layout.tsx). Pas de contexte de
// langue disponible ici, d'où le lien codé en dur vers la locale par défaut.
export default function NotFound() {
  return (
    <html lang="fr">
      <body className="min-h-screen antialiased">
        <div className="flex h-dvh flex-col items-center justify-center space-y-2 text-center">
          <h1 className="font-semibold text-2xl">Page introuvable.</h1>
          <p className="text-muted-foreground">La page que vous cherchez n'existe pas.</p>
          <Link prefetch={false} replace href="/fr/dashboard/default">
            <Button variant="outline">Retour à l'accueil</Button>
          </Link>
        </div>
      </body>
    </html>
  );
}
