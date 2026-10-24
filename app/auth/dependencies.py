from fastapi.security import OAuth2PasswordBearer

# Point d'entrée pour la documentation Swagger et l'extraction du token depuis le header Authorization
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    scheme_name="JWT",
    description="Authentification via JWT",
    auto_error=False  # Permet de gérer nous-mêmes l'erreur 401 avec un message clair
)
