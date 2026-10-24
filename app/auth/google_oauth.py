"""
Vérification serveur des jetons d'identité Google ("Se connecter avec
Google") — cf. mémoire de session. Volontairement un module DISTINCT de
app/auth/jwt_handler.py : ce dernier signe/vérifie NOS PROPRES jetons
(HS256, secret partagé) ; ici on vérifie un jeton signé par Google (RS256,
clés publiques Google, rotées automatiquement) — deux mécanismes de
signature différents, jamais mélangés.

Décision d'architecture (cf. mémoire de session) : Google Sign-In
authentifie seulement un compte DÉJÀ EXISTANT (retrouvé par email) — ne
crée jamais de nouveau compte. La vérification ci-dessous ne fait que
prouver "cet email est réellement celui de ce compte Google" ; c'est
UserService.authenticate_with_google (app/services/user_service.py) qui
décide ensuite si un compte existe pour cet email.
"""
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import settings


class GoogleAuthDisabledError(Exception):
    """GOOGLE_CLIENT_ID absent de la configuration — jamais un jeton
    accepté sans audience explicite à vérifier contre."""


class InvalidGoogleCredentialError(Exception):
    """Jeton invalide, expiré, mal signé, ou d'audience différente."""


# Un seul Request() réutilisé (cache HTTP interne des clés publiques
# Google, évite de les re-télécharger à chaque connexion) — création
# paresseuse pour ne jamais faire d'appel réseau à l'import du module.
_google_request: google_requests.Request | None = None


def _get_google_request() -> google_requests.Request:
    global _google_request
    if _google_request is None:
        _google_request = google_requests.Request()
    return _google_request


def verify_google_id_token(credential: str) -> str:
    """
    Vérifie la signature RS256 (clés publiques Google), l'expiration et
    l'audience (doit correspondre à GOOGLE_CLIENT_ID) du jeton. Retourne
    l'email vérifié — jamais un email non confirmé par Google
    (email_verified=False rejeté explicitement, cf. cas réel d'un compte
    Google créé avec un email non confirmé).

    Lève GoogleAuthDisabledError / InvalidGoogleCredentialError plutôt que
    de laisser remonter l'exception brute de la librairie Google — jamais
    un détail d'implémentation externe exposé tel quel à l'appelant.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise GoogleAuthDisabledError(
            "GOOGLE_CLIENT_ID absent de la configuration — authentification Google désactivée."
        )

    try:
        payload = google_id_token.verify_oauth2_token(
            credential, _get_google_request(), settings.GOOGLE_CLIENT_ID,
        )
    except ValueError as exc:
        raise InvalidGoogleCredentialError(f"Jeton Google invalide : {exc}") from exc

    if not payload.get("email_verified"):
        raise InvalidGoogleCredentialError("L'email de ce compte Google n'est pas vérifié.")

    email = payload.get("email")
    if not email:
        raise InvalidGoogleCredentialError("Le jeton Google ne contient aucun email.")

    return email
