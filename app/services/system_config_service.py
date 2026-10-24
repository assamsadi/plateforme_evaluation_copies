"""
Service admin — surcharge des seuils Settings (chantier "Configuration
des modèles IA", Étape 2, décision actée avec l'utilisateur : stockage/
lecture SEULEMENT, PAS câblé dans les agents/services qui lisent
settings.X aujourd'hui — cf. docstring SystemConfigOverride). Seul
model_registry (ModelConfigAdminService, fichier voisin) a un effet
réellement vivant sur le prochain appel LLM.

_ALLOWED_SETTINGS est la SEULE source de vérité des clés acceptées —
jamais éditable via l'API, jamais une clé arbitraire acceptée
silencieusement (contrainte du ticket). Sélection : seuils métier/tuning
qui ont un sens à changer sans redéploiement (garde-fous transverses,
seuils de classification agents) — jamais un secret/identifiant (clé
API, connection string), jamais une valeur d'infrastructure (DB_POOL_SIZE,
KAFKA_BOOTSTRAP_SERVERS).
"""
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from app.core.config import settings
from app.domain.repositories.system_config_override_repository import (
    SystemConfigOverrideRepositoryProtocol,
)
from app.domain.schemas.system_schemas import SettingOverrideRead

# name -> type Python attendu (cast + validation à l'écriture ET à la lecture).
_ALLOWED_SETTINGS: dict[str, type] = {
    "MAX_LLM_CALLS_PER_THREAD": int,
    "LLM_RATE_LIMIT_MAX_RETRIES": int,
    "LLM_RATE_LIMIT_WAIT_SECONDS": int,
    "OCR_MIN_LAPLACIAN_VARIANCE": float,
    "OCR_CONFIDENCE_THRESHOLD": float,
    "OCR_MAX_CONCURRENCY": int,
    "OCR_MAX_RE_READ_ATTEMPTS": int,
    "DOCUMENT_STRUCTURING_MAX_CONCURRENCY": int,
    "QUESTION_ATTACHMENT_COSINE_THRESHOLD": float,
    "QUESTION_ATTACHMENT_LABEL_FUZZY_THRESHOLD": int,
    "QUESTION_ATTACHMENT_ORPHAN_SIMILARITY_THRESHOLD": float,
    "QUESTION_ATTACHMENT_MAX_TIMEOUT_SECONDS": int,
    "COMPETENCY_DECAY_FACTOR": Decimal,
    "COMPETENCY_TREND_THRESHOLD_PERCENT": Decimal,
    "COMPETENCY_PERSISTENT_WEAKNESS_THRESHOLD": Decimal,
    "COMPETENCY_PERSISTENT_WEAKNESS_WINDOW": int,
    "COMPETENCY_STRENGTH_RATIO_THRESHOLD": Decimal,
    "COMPETENCY_WEAKNESS_RATIO_THRESHOLD": Decimal,
    "RECOMMENDATION_WEAK_MASTERY_THRESHOLD": Decimal,
    "RECOMMENDATION_LOW_CONFIDENCE_THRESHOLD": Decimal,
    "RECOMMENDATION_MAX_PER_COMPETENCY": int,
    "RECOMMENDATION_MAX_TOTAL": int,
}


def _cast(value_type: type, raw: str) -> Any:
    """
    Lève ValueError sur échec de cast OU valeur négative (tous les
    seuils de l'allowlist sont sémantiquement >= 0 dans ce projet —
    compteurs, secondes, ratios, pourcentages, jamais une quantité
    signée) — validation stricte générique, pas de borne haute par
    seuil (hors périmètre de ce chantier, cf. plan validé).
    """
    try:
        casted = value_type(raw)
    except (ValueError, InvalidOperation) as e:
        raise ValueError(f"Valeur invalide pour le type {value_type.__name__} : {raw!r}") from e
    if casted < 0:
        raise ValueError(f"Valeur négative refusée : {raw!r}")
    return casted


class SystemConfigServiceProtocol(Protocol):
    async def get_all_settings(self) -> list[SettingOverrideRead]: ...
    async def update_setting(self, key: str, value: str) -> SettingOverrideRead: ...


class SystemConfigService:
    def __init__(self, system_config_repo: SystemConfigOverrideRepositoryProtocol) -> None:
        self._repo = system_config_repo

    async def get_all_settings(self) -> list[SettingOverrideRead]:
        overrides = {o.key: o for o in await self._repo.get_all()}
        result: list[SettingOverrideRead] = []
        for key, value_type in _ALLOWED_SETTINGS.items():
            default_value = str(getattr(settings, key))
            override = overrides.get(key)
            effective_value = override.value if override is not None else default_value
            result.append(SettingOverrideRead(
                key=key, value_type=value_type.__name__, default_value=default_value,
                override_value=override.value if override is not None else None,
                effective_value=effective_value,
                updated_at=override.updated_at if override is not None else None,
            ))
        return result

    async def update_setting(self, key: str, value: str) -> SettingOverrideRead:
        if key not in _ALLOWED_SETTINGS:
            raise ValueError(f"Seuil non configurable : {key!r} (absent de l'allowlist)")

        value_type = _ALLOWED_SETTINGS[key]
        _cast(value_type, value)  # lève ValueError si invalide — jamais persisté silencieusement

        row = await self._repo.upsert(key=key, value=value)
        return SettingOverrideRead(
            key=key, value_type=value_type.__name__, default_value=str(getattr(settings, key)),
            override_value=row.value, effective_value=row.value, updated_at=row.updated_at,
        )
