"""
ModelRegistry = registre centralisé des modèles AI et chaînes de fallback par TaskType.

Les agents ne manipulent jamais de noms de modèles ou de fournisseurs en dur ;
ils demandent simplement `registry.get_llm_chain(TaskType.OCR_VISION)`.

Chantier "Configuration des modèles IA" (admin) — surcharge base de
données de l'entrée PRIMAIRE par TaskType (table ModelConfiguration),
avec cache TTL court en mémoire (get_specs_for_task/get_llm_chain restent
SYNCHRONES, aucun call site existant cassé — ils ne lisent QUE le cache).

Compromis assumé (cache TTL, pas d'invalidation événementielle) : ce
registre est un SINGLETON PAR PROCESSUS (web + workers Celery, plusieurs
processus séparés, jamais d'état partagé entre eux) — une invalidation
"immédiate" dans le processus qui reçoit un PUT admin n'a de toute façon
aucun effet sur les autres processus. Un TTL court (par défaut 30s,
_DEFAULT_CACHE_TTL_SECONDS) borne la propagation vers TOUS les processus
sans mécanisme distribué neuf (pub/sub Redis/Kafka) — surface de panne
disproportionnée pour ce gain face à un TTL déjà court et prévisible.
invalidate_cache() force un rafraîchissement immédiat, mais UNIQUEMENT
dans le processus qui l'appelle (effet best-effort, jamais garanti
cross-process) — le TTL reste la seule garantie réelle de convergence.
"""
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx
from langchain_core.language_models import BaseChatModel

from app.model_registry.models import ModelProvider, ModelSpec, TaskType
from app.model_registry.providers import create_llm_from_spec

if TYPE_CHECKING:
    from app.domain.models.system_infrastructure.model_configuration import ModelConfiguration

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_TTL_SECONDS = 30


# Configuration par défaut des chaînes de modèles par TaskType
# Timeouts par défaut (audit "garanties transverses", Plan C) : les tâches
# vision (image pleine résolution, potentiellement multi-page) reçoivent un
# budget plus large que les tâches texte seul, cohérent avec leur latence
# réelle observée — jamais la même valeur uniforme partout.
#
# _TEXT_TIMEOUT_SECONDS relevé de 45 à 90 (Phase test réelle, 2026-08-27) :
# depuis que Gemini est en priorité sur les tâches texte aussi (cf.
# TaskType.DOCUMENT_STRUCTURING et consorts ci-dessous — même raisonnement
# que pour OCR_VISION, Groq/OpenAI cassés sur ce compte), un appel de
# structuration démarrant juste après l'OCR retombe souvent sur le MÊME
# quota Gemini déjà largement consommé (15 req/min, palier gratuit) — son
# propre retry-avec-backoff interne (cf. google-genai SDK) peut annoncer un
# délai de 40 à 59s avant de réessayer. Un timeout de 45s coupait cet appel
# AVANT que ce retry interne ait fini, le faisait échouer, puis basculait
# vers Groq/OpenAI (tous deux inutilisables sur ce compte) -> échec total
# constaté en test réel ("Tous les fournisseurs LLM ont échoué pour la
# tâche document_structuring", des dizaines de blocs perdus/classés AUTRE).
# 90s (aligné sur _VISION_TIMEOUT_SECONDS, déjà éprouvé en pratique sur
# l'OCR malgré les mêmes 429) laisse ce retry interne le temps d'aboutir.
_VISION_TIMEOUT_SECONDS = 90
_TEXT_TIMEOUT_SECONDS = 90

# 2026-08-29 — 3e maillon (secours ultime, après les 2 comptes Gemini du
# TaskType) sur les TaskTypes texte-seul à fort enjeu de disponibilité :
# "openai/gpt-oss-120b" via Groq, PAS "llama-3.3-70b-versatile" (retiré
# officiellement par Groq le 17 juin 2026, cf. console.groq.com/docs/
# deprecations — remplacement recommandé par Groq lui-même). Choix
# vérifié en conditions réelles ce jour (2 appels de test, dont un avec
# with_structured_output — le mécanisme réellement utilisé par
# invoke_llm_with_fallback, pas juste un texte libre) : répond
# correctement, sortie structurée valide. Reste soumis au même plafond
# 8000 TPM déjà constaté sur ce compte Groq (cf. historique de session) —
# un vrai filet de sécurité seulement si les 2 comptes Gemini du TaskType
# sont épuisés le même jour, jamais un remplacement de la chaîne Gemini.
_GROQ_TEXT_FALLBACK = ModelSpec(
    provider=ModelProvider.GROQ,
    model_name="openai/gpt-oss-120b",
    temperature=0.1,
    timeout_seconds=_TEXT_TIMEOUT_SECONDS,
)

# Gemini reste le seul FOURNISSEUR sur les 6 tâches (2026-08-27, décision
# explicite : Groq structurellement plafonné à 8000 TPM sur ce compte,
# OpenAI sans crédit, OpenRouter à crédit quasi nul et modèle "stealth"
# retiré — cf. mémoire de session pour l'historique complet de chaque
# échec) — mais chaque chaîne porte maintenant 2 ENTRÉES Gemini, sur 2
# COMPTES Google distincts (GOOGLE_API_KEY puis GOOGLE_API_KEY_2, cf.
# ModelProvider.GEMINI_2 et providers.py). Motif (constaté en test réel,
# document C2PCT 36 pages) : le palier gratuit Gemini a DEUX plafonds
# indépendants (15 req/min ET 500 req/jour) — avec un seul compte, dès que
# l'un des deux est atteint, TOUTE la tâche échoue ("Tous les fournisseurs
# LLM ont échoué"), sans aucun repli possible. Le 2e compte n'est PAS un
# fournisseur différent : mêmes modèles, mêmes prompts, seul le jeu de
# crédentials change — invoke_llm_with_fallback (déjà existant, aucune
# modification requise) bascule dessus automatiquement dès que le 1er
# échoue, ce qui rend chaque compte individuellement moins susceptible de
# bloquer tout un run. Si les DEUX comptes sont épuisés le même jour,
# get_llm_chain() lève toujours RuntimeError plutôt que de silencieusement
# essayer un fournisseur cassé (Groq/OpenAI/OpenRouter) — cf. historique
# git pour réintroduire un repli non-Gemini si besoin.
_DEFAULT_REGISTRY_CONFIG: dict[TaskType, list[ModelSpec]] = {
    TaskType.OCR_VISION: [
        ModelSpec(
            provider=ModelProvider.GEMINI,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            supports_vision=True,
            timeout_seconds=_VISION_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_2,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            supports_vision=True,
            timeout_seconds=_VISION_TIMEOUT_SECONDS,
        ),
    ],
    # 2026-08-29 (backlog_bugs_c2pct.md, couche 4) — OCR du document de
    # RÉFÉRENCE du professeur uniquement (cf. TaskType.OCR_VISION_REFERENCE,
    # models.py) : TaskType séparé conservé (isolation du chemin à risque
    # maximal, cf. justification complète dans models.py), mais REVENU sur
    # "gemini-flash-lite-latest" — la tentative de palier supérieur
    # ("gemini-flash-latest", résolu par Google vers "gemini-3.7-flash") a
    # été testée le jour même et a immédiatement échoué en conditions
    # réelles : 429 RESOURCE_EXHAUSTED sur les 2 comptes, "limit: 20"
    # requêtes/JOUR en palier gratuit pour ce modèle — structurellement
    # incompatible avec l'OCR d'un document multi-pages (36 pages = 36+
    # appels), jamais un pic passager (contrairement à un 503 de surcharge,
    # confirmé par le message d'erreur lui-même). "gemini-flash-lite-latest"
    # n'a jamais présenté cette limite sur le même compte durant toute la
    # session. Repasser au palier supérieur nécessiterait un compte payant
    # (hors périmètre ici) — ne jamais retenter "gemini-flash-latest" sur le
    # palier gratuit pour ce TaskType précis sans lever cette limite d'abord.
    TaskType.OCR_VISION_REFERENCE: [
        ModelSpec(
            provider=ModelProvider.GEMINI,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            supports_vision=True,
            timeout_seconds=_VISION_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_2,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            supports_vision=True,
            timeout_seconds=_VISION_TIMEOUT_SECONDS,
        ),
    ],
    # GEMINI_3/_4 (pas GEMINI/GEMINI_2) — cf. leur docstring (models.py) :
    # comptes dédiés, jamais partagés avec OCR_VISION, pour qu'un épuisement
    # de quota côté OCR ne prive jamais l'appel de regroupement en questions
    # (le plus critique de cet agent) de toute chance de réussir.
    TaskType.DOCUMENT_STRUCTURING: [
        ModelSpec(
            provider=ModelProvider.GEMINI_3,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_4,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        # GEMINI_5/_6/_7 (2026-09-11) — GEMINI_3 ET GEMINI_4 épuisés le même
        # jour en conditions réelles (429 RESOURCE_EXHAUSTED sur les deux),
        # cf. docstring ModelProvider.GEMINI_5 (models.py). 3 comptes
        # supplémentaires plutôt qu'un seul : le palier gratuit Gemini a un
        # plafond PAR MINUTE (15 req/min) en plus du plafond journalier —
        # un seul compte de plus se serait aussi fait épuiser en quelques
        # appels sur un document multi-pages.
        ModelSpec(
            provider=ModelProvider.GEMINI_5,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_6,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_7,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        _GROQ_TEXT_FALLBACK,
    ],
    # Vision requise : Cas A/C relisent une image en pleine résolution
    # (OCR2). Cas B/D sont purement textuels mais partagent la même
    # chaîne — un modèle vision traite aussi bien du texte pur, l'inverse
    # n'est pas vrai. Même chaîne que OCR_VISION (cohérence de qualité).
    TaskType.CONTESTATION_VERIFICATION: [
        ModelSpec(
            provider=ModelProvider.GEMINI,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            supports_vision=True,
            timeout_seconds=_VISION_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_2,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            supports_vision=True,
            timeout_seconds=_VISION_TIMEOUT_SECONDS,
        ),
    ],
    # Pas de vision requise : Extraction_Verification_Agent travaille sur
    # raw_text déjà extrait (TeacherCorrectionBlock), jamais sur une image.
    # Même chaîne texte-seule que DOCUMENT_STRUCTURING.
    TaskType.EXTRACTION_VERIFICATION: [
        ModelSpec(
            provider=ModelProvider.GEMINI,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_2,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        _GROQ_TEXT_FALLBACK,
    ],
    TaskType.REASONING_GRAPH: [
        ModelSpec(
            provider=ModelProvider.GEMINI,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_2,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        _GROQ_TEXT_FALLBACK,
    ],
    # Pas de vision requise : Feedback_Agent travaille uniquement sur le
    # StudentCompetencyReport déjà calculé (texte/nombres), jamais une
    # image. Même chaîne texte-seule que DOCUMENT_STRUCTURING/REASONING_
    # GRAPH. Température volontairement standard (0.1) malgré la nature
    # rédactionnelle de la sortie — la contrainte socratique/factuelle
    # (ancrage sur des extraits réels fournis) prime sur la créativité,
    # cohérent avec le garde-fou déterministe posé après coup (présence
    # d'une question) plutôt qu'une température plus élevée qui rendrait
    # ce garde-fou plus souvent nécessaire.
    TaskType.FEEDBACK_GENERATION: [
        ModelSpec(
            provider=ModelProvider.GEMINI,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_2,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        _GROQ_TEXT_FALLBACK,
    ],
    # 2026-08-29 — TaskType absent jusqu'ici de ce registre (trouvé en
    # analysant systématiquement chaque agent/TaskType du projet) :
    # Comparative_Evaluation_Agent retombait sur le repli générique Groq/
    # OpenAI de get_default_specs_for_task ci-dessous — CASSÉ (Groq :
    # ancien model_name retiré côté fournisseur ; OpenAI : crédit épuisé)
    # pour l'agent qui attribue littéralement les points (le plus critique
    # de tout le pipeline de notation). Pas de vision requise (compare le
    # texte déjà extrait/vérifié contre les variantes de référence). Même
    # chaîne texte-seule que les autres TaskTypes ci-dessus.
    TaskType.COMPARATIVE_EVALUATION: [
        ModelSpec(
            provider=ModelProvider.GEMINI,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_2,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        _GROQ_TEXT_FALLBACK,
    ],
    # Absent jusqu'ici de ce registre — retombait sur le repli générique
    # Groq/OpenAI de get_default_specs_for_task ci-dessous, TOUS DEUX cassés
    # sur ce compte (Groq : llama-3.3-70b-versatile supprimé côté fournisseur,
    # 404 model_not_found ; OpenAI : crédit épuisé, 429 insufficient_quota) —
    # échec systématique de "Générer avec l'IA" (variantes de solution),
    # constaté en test réel. Pas de vision requise (travaille sur le texte
    # de l'énoncé/référence déjà extrait) : même chaîne texte-seule que
    # DOCUMENT_STRUCTURING/REASONING_GRAPH/FEEDBACK_GENERATION.
    TaskType.SOLUTION_VARIANT_GENERATION: [
        ModelSpec(
            provider=ModelProvider.GEMINI,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
        ModelSpec(
            provider=ModelProvider.GEMINI_2,
            model_name="gemini-flash-lite-latest",
            temperature=0.1,
            timeout_seconds=_TEXT_TIMEOUT_SECONDS,
        ),
    ],
}


class ModelRegistry:
    """Registre singleton de résolution des modèles LLM et de leurs fallbacks."""

    def __init__(
        self,
        config: dict[TaskType, list[ModelSpec]] | None = None,
        cache_ttl_seconds: int = _DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._config = config or _DEFAULT_REGISTRY_CONFIG
        self._cache_ttl_seconds = cache_ttl_seconds
        # Surcharges DB par TaskType (task_type -> ModelConfiguration),
        # vide tant qu'aucun rafraîchissement n'a eu lieu — get_specs_for_
        # task se comporte alors EXACTEMENT comme avant ce chantier
        # (jamais de comportement cassé si la table est vide ou jamais
        # interrogée, cf. contrainte du ticket).
        self._overrides: dict[TaskType, "ModelConfiguration"] = {}
        self._cache_loaded_at: datetime | None = None

    def _is_cache_stale(self) -> bool:
        if self._cache_loaded_at is None:
            return True
        age_seconds = (datetime.now(timezone.utc) - self._cache_loaded_at).total_seconds()
        return age_seconds >= self._cache_ttl_seconds

    async def refresh_cache_if_stale(self) -> None:
        """
        Rafraîchit le cache de surcharges depuis la base SI le TTL est
        dépassé (no-op sinon — pas de session DB ouverte à chaque appel).
        Best-effort explicite : une erreur DB (table absente, connexion
        indisponible) ne doit JAMAIS interrompre un appel LLM — c'est une
        fonctionnalité d'admin, pas un prérequis du pipeline. Le cache
        existant (ou vide, donc repli intégral sur _DEFAULT_REGISTRY_CONFIG)
        est conservé tel quel en cas d'échec.
        """
        if not self._is_cache_stale():
            return

        from app.core.database import get_db_context
        from app.domain.repositories.model_configuration_repository import (
            SQLAlchemyModelConfigurationRepository,
        )

        try:
            async with get_db_context() as db:
                rows = await SQLAlchemyModelConfigurationRepository(db).get_all()
            self._overrides = {row.task_type: row for row in rows}
            self._cache_loaded_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning(
                f"Impossible de rafraîchir le cache de configuration LLM "
                f"(repli sur le cache existant / les valeurs par défaut) : {e}"
            )

    def invalidate_cache(self) -> None:
        """Force un rafraîchissement au prochain appel — effet immédiat SEULEMENT dans ce processus (cf. docstring module)."""
        self._cache_loaded_at = None

    def _apply_override(self, task_type: TaskType, specs: list[ModelSpec]) -> list[ModelSpec]:
        """
        Surcharge UNIQUEMENT l'entrée primaire (index 0) — temperature/
        max_tokens/supports_vision hérités de la ModelSpec d'origine
        (jamais devinés), le(s) fournisseur(s) de repli restent
        INCHANGÉS (jamais retirés par une ligne de config admin).
        """
        override = self._overrides.get(task_type)
        if override is None:
            return specs
        primary = specs[0]
        overridden_primary = ModelSpec(
            provider=override.provider,
            model_name=override.model_name,
            temperature=primary.temperature,
            max_tokens=primary.max_tokens,
            supports_vision=primary.supports_vision,
            timeout_seconds=override.timeout_seconds,
        )
        return [overridden_primary, *specs[1:]]

    def get_default_specs_for_task(self, task_type: TaskType) -> list[ModelSpec]:
        """
        Chaîne par défaut SANS surcharge admin appliquée — utilisé par
        get_specs_for_task ci-dessous (qui applique la surcharge en cache)
        ET par ModelConfigAdminService (vue GET /admin/config/models,
        toujours fraîche, jamais couplée au cache du chemin d'appel LLM).
        """
        specs = self._config.get(task_type)
        if not specs:
            # Fallback générique si le TaskType spécifique n'est pas encore enregistré
            specs = [
                ModelSpec(
                    provider=ModelProvider.GROQ, model_name="openai/gpt-oss-120b",
                    temperature=0.1, timeout_seconds=_TEXT_TIMEOUT_SECONDS,
                ),
                ModelSpec(
                    provider=ModelProvider.OPENAI, model_name="gpt-4o-mini",
                    temperature=0.1, timeout_seconds=_TEXT_TIMEOUT_SECONDS,
                ),
            ]
        return specs

    def get_specs_for_task(self, task_type: TaskType) -> list[ModelSpec]:
        """Retourne la liste ordonnée des ModelSpec (primaire + fallbacks) pour une tâche, surcharge admin (cache) appliquée."""
        specs = self.get_default_specs_for_task(task_type)
        return self._apply_override(task_type, specs)

    def get_primary_llm(self, task_type: TaskType) -> tuple[BaseChatModel, ModelSpec, httpx.AsyncClient]:
        """Obtient le LLM principal pour le TaskType. L'appelant doit fermer le httpx.AsyncClient retourné."""
        specs = self.get_specs_for_task(task_type)
        primary_spec = specs[0]
        llm, http_client = create_llm_from_spec(primary_spec)
        return llm, primary_spec, http_client

    def get_llm_chain(self, task_type: TaskType) -> list[tuple[BaseChatModel, ModelSpec, httpx.AsyncClient]]:
        """
        Retourne la chaîne complète (LLM, Spec, httpx.AsyncClient) pour
        exécution avec fallback. L'appelant doit fermer chaque
        httpx.AsyncClient après usage (cf. create_llm_from_spec).
        """
        specs = self.get_specs_for_task(task_type)
        chain = []
        for spec in specs:
            try:
                llm, http_client = create_llm_from_spec(spec)
                chain.append((llm, spec, http_client))
            except Exception as e:
                logger.warning(
                    f"Impossible d'instancier le provider {spec.provider} pour {task_type} : {e}"
                )
        if not chain:
            raise RuntimeError(f"Aucun fournisseur LLM disponible pour la tâche {task_type}")
        return chain


# Singleton global
registry = ModelRegistry()
