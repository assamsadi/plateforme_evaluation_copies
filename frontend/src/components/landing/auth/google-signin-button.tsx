"use client";

import { useEffect, useRef } from "react";
import type { ReactNode } from "react";

import Script from "next/script";

// Typage minimal du script externe Google Identity Services — jamais
// installé comme dépendance npm (chargé en <script> global, cf. Script
// ci-dessous), donc pas de vrais types disponibles. Seuls les 2 usages
// réels de ce fichier sont typés (initialize/renderButton).
interface GoogleIdentityServices {
  accounts: {
    id: {
      initialize: (config: {
        client_id: string;
        callback: (response: { credential: string }) => void;
      }) => void;
      renderButton: (
        parent: HTMLElement,
        options: { theme?: string; size?: string; shape?: string; width?: number; locale?: string },
      ) => void;
    };
  };
}

declare global {
  interface Window {
    google?: GoogleIdentityServices;
  }
}

// "Se connecter avec Google" (cf. mémoire de session) — nécessite un vrai
// Client ID OAuth 2.0 créé dans Google Cloud Console (APIs & Services >
// Credentials > OAuth client ID > Web application), fourni via
// NEXT_PUBLIC_GOOGLE_CLIENT_ID. Sans cette variable, le bouton ne
// s'affiche simplement pas — jamais une tentative avec un client_id vide
// (Google Identity Services échouerait silencieusement ou de façon peu
// claire pour l'utilisateur).
//
// `children` (optionnel) : Google Identity Services ne permet AUCUN style
// Tailwind personnalisé sur le bouton qu'il dessine lui-même (renderButton
// n'accepte que ses propres options theme/size/shape) — technique standard
// pour un visuel 100% personnalisé (cf. mémoire de session, inspiration
// MerakiUI) : le vrai bouton Google reste rendu mais invisible (opacity-0),
// posé EN SUPERPOSITION exacte au-dessus du visuel `children`, qui lui
// n'intercepte aucun clic (pointer-events-none) — l'utilisateur clique
// visuellement sur `children`, mais capte réellement le vrai bouton Google
// dessous. Jamais un faux bouton qui ne ferait qu'imiter Google visuellement
// sans vraie authentification derrière.
export function GoogleSignInButton({
  onCredential,
  children,
}: {
  onCredential: (credential: string) => void;
  children?: ReactNode;
}) {
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
  const containerRef = useRef<HTMLDivElement>(null);

  function renderButton() {
    if (!clientId || !containerRef.current || !window.google) return;
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: (response) => onCredential(response.credential),
    });
    containerRef.current.innerHTML = "";
    window.google.accounts.id.renderButton(containerRef.current, {
      theme: "outline",
      size: "large",
      shape: children ? "rectangular" : "pill",
      width: 350,
    });
  }

  useEffect(() => {
    // Le script a pu finir de charger avant le montage de ce composant
    // (navigation client-side ultérieure) — dans ce cas onLoad (ci-dessous)
    // ne se déclenche jamais une seconde fois, il faut retenter ici.
    if (window.google) renderButton();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!clientId) return null;

  if (children) {
    return (
      <div className="relative h-12 w-full overflow-hidden rounded-lg">
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">{children}</div>
        <div
          ref={containerRef}
          className="absolute inset-0 flex items-center justify-center opacity-0 [&>div]:!w-full"
        />
        <Script src="https://accounts.google.com/gsi/client" strategy="afterInteractive" onLoad={renderButton} />
      </div>
    );
  }

  return (
    <>
      <Script src="https://accounts.google.com/gsi/client" strategy="afterInteractive" onLoad={renderButton} />
      <div ref={containerRef} className="flex justify-center" />
    </>
  );
}
