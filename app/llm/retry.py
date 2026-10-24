"""
Politique de retry d'infrastructure (Tenacity) pour les erreurs temporaires réseau/5xx.
Ne s'applique JAMAIS aux erreurs métier (ex. mauvaise extraction, confiance faible, qualité).
"""
import logging

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Liste des exceptions réseau/infrastructures éligibles aux retries automatiques
INFRASTRUCTURE_ERRORS = (
    TimeoutError,
    ConnectionError,
    OSError,
)

try:
    import httpx
    INFRASTRUCTURE_ERRORS += (
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.HTTPStatusError,
    )
except ImportError:
    pass


def infrastructure_retry(max_attempts: int = 3):
    """Décorateur de retry pour les appels LLM sur erreurs réseau/timeout/5xx."""
    return retry(
        reraise=True,
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(INFRASTRUCTURE_ERRORS),
        before_sleep=lambda retry_state: logger.warning(
            f"Retry d'infrastructure #{retry_state.attempt_number} suite à {retry_state.outcome.exception()}"
        ),
    )
