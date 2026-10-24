"""
Client Langfuse — singleton par processus, reconstruit UNE SEULE FOIS au
démarrage (cf. app/main.py::lifespan) avec la valeur effective de chaque
clé (surcharge admin en base si présente, sinon .env — cf.
app/core/provider_credentials.py). Contrairement aux clés API LLM
(app/model_registry/providers.py), une surcharge Langfuse faite APRÈS le
démarrage n'a effet qu'au PROCHAIN redémarrage — décision actée : le
client Langfuse n'est pas rebâti à chaud (chantier séparé, pas fait ici).

`langfuse` reste un simple nom de MODULE-LEVEL réassignable via
rebuild_langfuse_client() — les appelants (app/observability/langfuse.py)
DOIVENT lire cet attribut à travers le module (jamais `from
app.core.langfuse_client import langfuse` par valeur), sinon ils
garderaient une référence figée sur l'instance construite à l'import,
jamais mise à jour par un rebuild ultérieur.
"""
import logging
import os

from dotenv import load_dotenv
from langfuse import Langfuse

load_dotenv()

logger = logging.getLogger(__name__)


def _build_client(secret_key: str | None, public_key: str | None, base_url: str | None) -> Langfuse:
    return Langfuse(
        secret_key=secret_key,
        public_key=public_key,
        base_url=base_url,
        debug=True,
    )


langfuse = _build_client(
    os.getenv("LANGFUSE_SECRET_KEY"),
    os.getenv("LANGFUSE_PUBLIC_KEY"),
    os.getenv("LANGFUSE_BASE_URL"),
)


def rebuild_langfuse_client(secret_key: str | None, public_key: str | None, base_url: str | None) -> None:
    """Appelée UNE FOIS au démarrage (app/main.py::lifespan) avec les valeurs effectives (DB si présentes, sinon .env)."""
    global langfuse
    try:
        langfuse = _build_client(secret_key, public_key, base_url)
    except Exception as e:
        logger.warning(f"Échec de reconstruction du client Langfuse au démarrage (conservation du client .env existant) : {e}")

