"use client";

import { type ReactNode, useEffect } from "react";

import { useRouter } from "@/i18n/navigation";
import { useAuth } from "@/lib/auth-context";

export function AuthGuard({
  children,
  requiredRole,
}: {
  children: ReactNode;
  /** Rôle backend exact requis pour cette page (ex. "admin") — redirige vers /unauthorized si non respecté. */
  requiredRole?: string;
}) {
  const { user, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  const roleMismatch = Boolean(requiredRole && user && user.role !== requiredRole);

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      // Un seul point de connexion pour toute la plateforme : la page
      // signin de landing. Landing et dashboard vivent maintenant dans la
      // même application (une seule origine) — navigation interne.
      router.replace("/signin");
      return;
    }
    if (roleMismatch) {
      router.replace("/unauthorized");
    }
  }, [isLoading, isAuthenticated, roleMismatch, router]);

  // Rien tant qu'on n'a pas confirmé la session/le rôle (évite un flash du
  // contenu protégé avant la redirection) ou pendant la redirection elle-même.
  if (isLoading || !isAuthenticated || roleMismatch) return null;

  return <>{children}</>;
}
