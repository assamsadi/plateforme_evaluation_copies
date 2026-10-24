"""
AuditLog = journal d'audit des actions HUMAINES (distinct d'AgentDecisionLog
qui trace les décisions des agents IA). Table IMMUABLE par convention :
aucun endpoint UPDATE/DELETE exposé, CreatedAtOnlyMixin (pas de updated_at).

action est en texte libre (pas un enum PostgreSQL) : le nombre d'actions
métier croît avec le temps (nouvelles entités, nouveaux endpoints), un
enum figé forcerait une migration à chaque ajout. Convention : verbe à
l'infinitif snake_case, ex. "create_exercise", "approve_variant",
"reject_incident".

entry_hash : chaînage cryptographique (hash chaining, même principe
qu'une blockchain simplifiée) — chaque entrée est hashée à partir de son
propre contenu + le hash de l'entrée précédente. Si une ligne est modifiée
ou supprimée au milieu de la chaîne, tous les hashs suivants deviennent
invalides : la falsification devient détectable, pas juste "difficile".
Calcul et vérification de la chaîne : dans audit_log_repository.py
(jamais dans ce modèle — pure structure de données).
"""
import uuid
from enum import StrEnum

from sqlalchemy import Boolean, Enum as PgEnum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import CreatedAtOnlyMixin, UUIDPKMixin


class AuditSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AuditLog(Base, UUIDPKMixin, CreatedAtOnlyMixin):
    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: "Exercise"
    entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)

    # {"before": {...}, "after": {...}} — quoi exactement a changé
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6-safe
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    severity: Mapped[AuditSeverity] = mapped_column(
        PgEnum(AuditSeverity, name="audit_severity"),
        nullable=False,
        default=AuditSeverity.INFO,
    )

    # entry_hash: DEPRECATED - Ce champ n'est plus utilisé ni chaîné. Rendu nullable pour compatibilité.
    entry_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Note: user_full_name est positionné dynamiquement en mémoire
    # par le service pour AuditLogRead, pas comme colonne ORM.

