"""
ProviderCredential = surcharge admin (base de données) d'un secret
fournisseur IA (clé API LLM, config Langfuse) — clé/valeur générique,
SANS allowlist fermée côté backend (contrairement à SystemConfigOverride,
fichier voisin) : décision actée avec l'utilisateur, l'admin doit pouvoir
nommer lui-même n'importe quelle clé (ex. un futur fournisseur pas encore
câblé dans app/model_registry/providers.py), jamais bloqué par une liste
fermée.

`value` stocké en clair (même choix que SystemConfigOverride, aucune
infra de chiffrement ailleurs dans ce projet — décision actée). La
protection réelle est côté API : `value` n'est JAMAIS renvoyé par
ProviderCredentialRead (cf. app/domain/schemas/system_schemas.py) — un
admin peut remplacer ou effacer une clé à l'aveugle, jamais revoir
l'ancienne valeur (même sémantique que les secrets GitHub Actions/Vercel).

Seules GROQ_API_KEY et OPENAI_API_KEY ont un effet réellement vivant
aujourd'hui (cf. app/core/provider_credentials.py::get_effective_credential,
consommé par app/model_registry/providers.py) — toute autre clé est
stockée mais inerte tant qu'aucun code ne la consomme, signalé
honnêtement côté UI (ProviderCredentialRead.is_wired), jamais un blocage
à l'écriture. Langfuse (LANGFUSE_SECRET_KEY/LANGFUSE_PUBLIC_KEY/
LANGFUSE_BASE_URL) est un cas particulier : lu au démarrage du processus
uniquement (cf. app/core/langfuse_client.py) — effet au prochain
redémarrage, jamais à chaud, décision actée.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin


class ProviderCredential(Base, TimestampMixin):
    __tablename__ = "provider_credentials"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(1000), nullable=False)
