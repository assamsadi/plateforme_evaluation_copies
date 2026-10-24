const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export class AuthApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Le backend renvoie {"detail": "..."} sur les erreurs (cf. app/main.py,
// exception_handlers) — jamais un autre format, donc pas de fallback devinable.
async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // réponse non-JSON — laisse le message générique ci-dessous
  }
  return `Erreur ${response.status}`;
}

export interface UserPublic {
  id: string;
  email: string;
  role: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
}

export type LoginResult =
  | { mfaRequired: true; mfaToken: string }
  | {
      mfaRequired: false;
      accessToken: string;
      refreshToken: string;
      user: UserPublic;
    };

export async function login(email: string, password: string): Promise<LoginResult> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  const body = await response.json();

  if (body.mfa_required) {
    return { mfaRequired: true, mfaToken: body.mfa_token };
  }

  return {
    mfaRequired: false,
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
    user: body.user,
  };
}

// "Se connecter avec Google" (cf. mémoire de session) — même forme de
// réponse que login() ci-dessus (mfa_required ou jetons), réutilise donc
// EXACTEMENT le même type LoginResult et le même traitement côté appelant.
export async function loginWithGoogle(credential: string): Promise<LoginResult> {
  const response = await fetch(`${API_URL}/auth/login/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ credential }),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  const body = await response.json();

  if (body.mfa_required) {
    return { mfaRequired: true, mfaToken: body.mfa_token };
  }

  return {
    mfaRequired: false,
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
    user: body.user,
  };
}

export interface RegisterStudentPayload {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
  student_number: string;
  requested_group_label: string;
  enrollment_year: number;
  level: string;
}

export async function registerStudent(payload: RegisterStudentPayload): Promise<UserPublic> {
  const response = await fetch(`${API_URL}/auth/register/student`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  return response.json();
}

export interface RefreshResult {
  accessToken: string;
  refreshToken: string;
  user: UserPublic;
}

export async function refreshAccessToken(refreshToken: string): Promise<RefreshResult> {
  const response = await fetch(`${API_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    throw new AuthApiError(response.status, await parseErrorDetail(response));
  }

  const body = await response.json();
  return {
    accessToken: body.access_token,
    refreshToken: body.refresh_token,
    user: body.user,
  };
}

// Décodage local du payload JWT (pas de vérification de signature — on ne
// fait que lire `exp` pour planifier un rafraîchissement, jamais une
// décision de sécurité : le backend reste la seule source de vérité sur la
// validité réelle du token).
export function getTokenExpiryMs(accessToken: string): number | null {
  const payloadSegment = accessToken.split(".")[1];
  if (!payloadSegment) return null;

  try {
    const base64 = payloadSegment.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(base64));
    return typeof payload.exp === "number" ? payload.exp * 1000 : null;
  } catch {
    return null;
  }
}

export async function logout(accessToken: string, refreshToken: string): Promise<void> {
  await fetch(`${API_URL}/auth/logout`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  // Pas de throw sur échec : la déconnexion locale (effacement des tokens)
  // doit réussir même si l'appel serveur échoue (token déjà expiré, réseau).
}

const ACCESS_TOKEN_KEY = "auth.access_token";
const REFRESH_TOKEN_KEY = "auth.refresh_token";
const USER_KEY = "auth.user";

// Cookies, pas localStorage — simple mécanisme de stockage de session ici
// (landing et dashboard vivent dans la même app/origine, plus de partage
// cross-origin à gérer). En prod sur un vrai domaine avec un sous-domaine
// séparé, il faudrait un Domain=.votredomaine.com explicite ici.
const COOKIE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60; // 30 jours

function setCookie(name: string, value: string) {
  document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${COOKIE_MAX_AGE_SECONDS}; SameSite=Lax`;
}

function getCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

function deleteCookie(name: string) {
  document.cookie = `${name}=; Path=/; Max-Age=0`;
}

export interface StoredSession {
  accessToken: string;
  refreshToken: string;
  user: UserPublic;
}

export function storeSession(accessToken: string, refreshToken: string, user: UserPublic) {
  setCookie(ACCESS_TOKEN_KEY, accessToken);
  setCookie(REFRESH_TOKEN_KEY, refreshToken);
  setCookie(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  deleteCookie(ACCESS_TOKEN_KEY);
  deleteCookie(REFRESH_TOKEN_KEY);
  deleteCookie(USER_KEY);
}

export function getStoredSession(): StoredSession | null {
  const accessToken = getCookie(ACCESS_TOKEN_KEY);
  const refreshToken = getCookie(REFRESH_TOKEN_KEY);
  const rawUser = getCookie(USER_KEY);
  if (!accessToken || !refreshToken || !rawUser) return null;

  try {
    return { accessToken, refreshToken, user: JSON.parse(rawUser) as UserPublic };
  } catch {
    // Donnée corrompue (édition manuelle, ancien format) — jamais une
    // session à moitié reconstruite, on force une reconnexion propre.
    clearSession();
    return null;
  }
}
