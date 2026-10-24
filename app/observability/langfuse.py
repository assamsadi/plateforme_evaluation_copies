"""
Instrumentations et traçabilité Langfuse centralisées pour tous les agents.

v2 (2026-08-17) — corrige un bug plateforme (pas spécifique à un agent) :
tous les agents d'un même pipeline (ex. Document_Structuring_Agent ->
Extraction_Verification_Agent -> Solution_Variant_Generation_Agent, exécutés
dans le même run) apparaissaient comme des traces Langfuse SÉPARÉES et
DÉCONNECTÉES, alors qu'ils partageaient le même trace_id applicatif —
seul le dashboard laissait deviner le problème (un seul agent visible par
run). Cause trouvée en lisant directement la source du SDK Langfuse installé
(4.14.2, jamais devinée) : `start_observation()`/`start_as_current_
observation()` définissent INCONDITIONNELLEMENT `AS_ROOT=True` dès qu'un
`trace_context={"trace_id": ...}` est fourni SANS `parent_span_id` — chaque
appel devenait donc sa propre racine Langfuse, même avec un trace_id
identique. Aggravé par l'usage de `start_observation()` (pas `start_as_
current_observation()`), qui par conception ne s'inscrit jamais dans le
contexte OTEL ambiant (cf. docstring SDK : "does not set it as the current
span in the context") — la propagation automatique parent/enfant n'a donc
jamais pu fonctionner, même par accident.

Fix : `start_as_current_observation()` (context manager natif OTEL, imbrique
automatiquement sous le span ambiant courant) + `trace_context` fourni
UNIQUEMENT quand aucun span n'est déjà actif dans le contexte (premier agent
d'un run, ex. Document_Structuring_Agent) — les agents suivants du MÊME
pipeline (même call stack Python, ex. Extraction_Verification_Agent appelé
juste après dans le même service) s'imbriquent alors automatiquement comme
enfants du span déjà actif, sans jamais forcer AS_ROOT. Un agent appelé
isolément plus tard (ex. Solution_Variant_Generation_Agent en mode
on_demand, déclenché par un clic professeur bien après la fin du pipeline
proactif) reste correctement sa propre trace — c'est le comportement
sémantiquement correct dans ce cas, pas un bug.
"""
import logging
import time
import uuid
from typing import Any

from opentelemetry import trace as otel_trace_api

from app.core import langfuse_client

logger = logging.getLogger(__name__)


def _has_active_span_in_context() -> bool:
    """
    True si un span OTEL est déjà actif dans le contexte ambiant courant —
    déterminant pour savoir si CE span doit s'imbriquer automatiquement en
    tant qu'enfant (ambient context propagation) ou s'il doit ancrer
    lui-même un nouveau trace_id (premier agent d'un run, rien au-dessus).
    Jamais une exception : un échec de lecture de contexte est traité comme
    "pas de parent" (comportement historique inchangé, jamais plus cassant
    que l'ancien code).
    """
    try:
        return otel_trace_api.get_current_span().get_span_context().is_valid
    except Exception:
        return False


def _to_otel_trace_id(trace_id: str) -> str | None:
    """
    Langfuse (SDK OTEL) exige un trace_id hex 32 caractères minuscules, pas
    un UUID à tirets — nos trace_id applicatifs sont systématiquement
    str(uuid.uuid4()) (36 caractères). Convertit via UUID.hex (32 hex,
    forme canonique sans tirets) ; retourne None si trace_id n'est pas un
    UUID valide plutôt que de laisser Langfuse lever une ValueError.
    """
    try:
        return uuid.UUID(trace_id).hex
    except (ValueError, AttributeError, TypeError):
        return None


class AgentTraceSpan:
    """Gestionnaire de span d'observation Langfuse pour un agent."""

    def __init__(self, agent_name: str, trace_id: str, metadata: dict | None = None) -> None:
        self.agent_name = agent_name
        self.trace_id = trace_id
        self.metadata = metadata or {}
        self.start_time = time.perf_counter()
        self.metrics: dict[str, Any] = {}
        self._trace = None  # legacy .trace() (v2/v3) ou observation renvoyée par start_observation()
        self._cm = None  # context manager de start_as_current_observation() (v4/OTEL), pour __exit__

    def __enter__(self):
        self.start_time = time.perf_counter()
        # Lu à travers le module (pas un import par valeur) : reflète un
        # éventuel rebuild_langfuse_client() fait au démarrage, cf.
        # docstring app/core/langfuse_client.py.
        langfuse = langfuse_client.langfuse
        try:
            if langfuse:
                if hasattr(langfuse, "trace"):
                    self._trace = langfuse.trace(
                        id=self.trace_id,
                        name=self.agent_name,
                        metadata=self.metadata,
                    )
                elif hasattr(langfuse, "start_as_current_observation"):
                    # Ancrer explicitement trace_id (donc forcer AS_ROOT côté
                    # SDK, cf. docstring module) UNIQUEMENT si aucun span
                    # n'est déjà actif dans le contexte ambiant — sinon ce
                    # nouveau span doit s'imbriquer comme enfant du span
                    # déjà actif (autre agent du même pipeline), jamais
                    # redevenir sa propre racine déconnectée. start_as_
                    # current_observation() (pas start_observation()) inscrit
                    # en plus ce span comme "courant" pour la durée du bloc
                    # `with`, ce qui permet à un agent appelé PLUS LOIN dans
                    # la même pile d'appels de s'imbriquer à son tour sous
                    # celui-ci automatiquement.
                    trace_context = None
                    if not _has_active_span_in_context():
                        otel_trace_id = _to_otel_trace_id(self.trace_id)
                        if otel_trace_id:
                            trace_context = {"trace_id": otel_trace_id}
                    self._cm = langfuse.start_as_current_observation(
                        name=self.agent_name,
                        trace_context=trace_context,
                        metadata=self.metadata,
                    )
                    self._trace = self._cm.__enter__()
                elif hasattr(langfuse, "start_observation"):
                    # Repli pour un SDK plus ancien ne supportant que
                    # start_observation() (sans context manager) — même
                    # limitation qu'avant ce fix (AS_ROOT toujours forcé),
                    # jamais atteint avec le SDK actuellement installé
                    # (4.14.2, a start_as_current_observation).
                    otel_trace_id = _to_otel_trace_id(self.trace_id)
                    trace_context = {"trace_id": otel_trace_id} if otel_trace_id else None
                    self._trace = langfuse.start_observation(
                        name=self.agent_name,
                        trace_context=trace_context,
                        metadata=self.metadata,
                    )
        except Exception as e:
            logger.warning(f"Erreur initialisation trace Langfuse : {e}")
        return self

    def record_metrics(self, **kwargs: Any) -> None:
        """Enregistre des métriques personnalisées pour cette exécution d'agent."""
        self.metrics.update(kwargs)

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = round((time.perf_counter() - self.start_time) * 1000, 2)
        self.metrics["total_duration_ms"] = duration_ms

        if exc_val is not None:
            self.metrics["status"] = "ERROR"
            self.metrics["error_message"] = str(exc_val)
        else:
            self.metrics["status"] = "SUCCESS"

        try:
            if self._trace and hasattr(self._trace, "update"):
                self._trace.update(
                    output=self.metrics,
                    metadata={**self.metadata, **self.metrics},
                )
            if self._cm is not None:
                # Délègue la fermeture au context manager natif de Langfuse
                # (start_as_current_observation) : clôture le span ET le
                # retire du contexte ambiant (pop) — un appel manuel à
                # .end() seul laisserait ce span "actif" dans le contexte,
                # ce qui imbriquerait à tort un span FRÈRE ultérieur comme
                # son enfant plutôt que comme un vrai frère.
                self._cm.__exit__(exc_type, exc_val, exc_tb)
            elif self._trace and hasattr(self._trace, "end"):
                # SDK v4 (OTEL), repli start_observation() : ne clôture
                # jamais le span tout seul — sans .end() explicite, aucun
                # end_time n'est jamais fixé et le span n'est pas exporté
                # correctement (invisible/incomplet sur le dashboard
                # Langfuse), même après flush(). hasattr() car l'ancienne
                # API .trace() (v2/v3) n'a pas cette méthode — jamais
                # appelée dans ce cas, sans effet sur ce chemin-là.
                self._trace.end()
            langfuse = langfuse_client.langfuse
            if langfuse and hasattr(langfuse, "flush"):
                langfuse.flush()
        except Exception as e:
            logger.warning(f"Erreur lors de la mise à jour de la trace Langfuse : {e}")
