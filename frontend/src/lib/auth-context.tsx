"use client";

import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import {
  clearSession,
  getStoredSession,
  getTokenExpiryMs,
  logout as logoutRequest,
  refreshAccessToken,
  storeSession,
  type UserPublic,
} from "@/lib/auth-api";

interface AuthContextValue {
  user: UserPublic | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  setSession: (accessToken: string, refreshToken: string, user: UserPublic) => void;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// Marge avant expiration à laquelle on déclenche le rafraîchissement — assez
// tôt pour tolérer la latence réseau, jamais négatif même si le token est
// déjà expiré (le fetch échouera alors immédiatement et forcera la
// déconnexion, comportement correct).
const REFRESH_MARGIN_MS = 60_000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  // true tant qu'on n'a pas lu le localStorage — évite un flash "non connecté"
  // au premier rendu avant hydratation.
  const [isLoading, setIsLoading] = useState(true);
  // Incrémenté à chaque connexion/rafraîchissement pour redéclencher la
  // planification ci-dessous sans dupliquer `user` dans les dépendances.
  const [sessionVersion, setSessionVersion] = useState(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const session = getStoredSession();
    setUser(session?.user ?? null);
    setIsLoading(false);
  }, []);

  useEffect(() => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);

    const session = getStoredSession();
    if (!session) return;

    const expiryMs = getTokenExpiryMs(session.accessToken);
    if (expiryMs === null) return;

    const delay = Math.max(expiryMs - Date.now() - REFRESH_MARGIN_MS, 0);

    timeoutRef.current = setTimeout(async () => {
      try {
        const result = await refreshAccessToken(session.refreshToken);
        storeSession(result.accessToken, result.refreshToken, result.user);
        setUser(result.user);
        setSessionVersion((v) => v + 1);
      } catch {
        // Refresh token expiré/invalide — jamais de session à moitié
        // valide, on force une reconnexion propre.
        clearSession();
        setUser(null);
      }
    }, delay);

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, [user, sessionVersion]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isLoading,
      setSession: (accessToken, refreshToken, nextUser) => {
        storeSession(accessToken, refreshToken, nextUser);
        setUser(nextUser);
      },
      logout: async () => {
        const session = getStoredSession();
        if (session) {
          await logoutRequest(session.accessToken, session.refreshToken).catch(() => {
            // Déconnexion locale malgré tout — voir commentaire dans auth-api.ts.
          });
        }
        clearSession();
        setUser(null);
      },
    }),
    [user, isLoading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth doit être utilisé à l'intérieur de <AuthProvider>");
  }
  return context;
}
