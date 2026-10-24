"""
ModelConfiguration = surcharge admin (base de données) du choix de modèle
LLM par TaskType — chantier "Configuration des modèles IA".

Une ligne PAR TaskType (task_type = clé primaire, jamais un id UUID
séparé : le concept EST "la config actuelle de cette tâche", pas un
historique de configs). Surcharge UNIQUEMENT l'entrée PRIMAIRE de la
chaîne de fallback (provider/model_name/timeout_seconds) — temperature/
max_tokens/supports_vision restent hérités de la ModelSpec d'origine
(_DEFAULT_REGISTRY_CONFIG), jamais devinés ici. Le fournisseur de repli
(OpenAI) n'est JAMAIS remplacé par une ligne de cette table — un admin ne
peut pas retirer le filet de sécurité, seulement changer le choix
primaire (cf. ModelRegistry.get_specs_for_task).

Absence de ligne pour un TaskType = comportement strictement identique à
_DEFAULT_REGISTRY_CONFIG (repli jamais cassé, cf. contrainte du ticket).
"""
from sqlalchemy import Enum as PgEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin
from app.model_registry.models import ModelProvider, TaskType


class ModelConfiguration(Base, TimestampMixin):
    __tablename__ = "model_configurations"

    task_type: Mapped[TaskType] = mapped_column(
        PgEnum(TaskType, name="model_configuration_task_type"),
        primary_key=True,
    )
    provider: Mapped[ModelProvider] = mapped_column(
        PgEnum(ModelProvider, name="model_configuration_provider"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
