"""
SystemConfigOverride = surcharge admin (base de données) d'un seuil
Settings — clé/valeur générique plutôt qu'une colonne par seuil : ~20
seuils candidats (cf. rapport de diagnostic), une table à colonne fixe
nécessiterait une migration à chaque nouveau seuil exposé. `key` est
validée à l'écriture contre une allowlist codée en dur (jamais éditable
via l'API, cf. app/services/system_config_service.py::_ALLOWED_SETTINGS)
— jamais de clé arbitraire acceptée silencieusement.

`value` stocké en texte brut (jamais typé en base) : le type réel (int,
float, Decimal) est réappliqué à la LECTURE selon l'allowlist, cohérent
avec Bareme.criteria/Question.subquestion_points (sérialisation texte,
désérialisation typée explicite ailleurs dans ce projet).

Stockage/lecture SEULEMENT à ce stade (chantier "Configuration des
modèles IA", décision actée avec l'utilisateur) — PAS encore câblé dans
les agents/services qui lisent settings.X aujourd'hui : limite
documentée explicitement, pas un oubli. Seul model_registry (table
ModelConfiguration, fichier voisin) a un effet réellement vivant sur le
prochain appel LLM.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import TimestampMixin


class SystemConfigOverride(Base, TimestampMixin):
    __tablename__ = "system_config_overrides"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
