"""
AgentDecisionLog = trace de CHAQUE décision d'un agent IA (distinct
d'AuditLog qui trace les actions humaines). Répond au critère
d'explicabilité du document CHAABI (§6.1) : "pourquoi une note a été
attribuée, pourquoi ce feedback, pourquoi cette recommandation".

related_entity_type/id : référence polymorphe (pas de vraie FK SQL,
volontairement — un agent peut décider sur N'IMPORTE quelle entité :
Evaluation, Feedback, RecommendedExercise, SolutionVariant...).

model_version : quelle version du modèle a produit cette décision —
correspond à model_registry (§6 du résumé), permet de savoir si une
décision provient d'une version de modèle depuis remplacée.

Enrichissements pour une observabilité LLMOps complète :
- prompt_text/prompt_version : reproductibilité exacte d'une décision
- tools_consulted : explicabilité (RAG/tool calling, sources utilisées)
- execution_time_ms/token counts : performance et coût, par décision
- thread_id/run_id/node_name : corrélation directe avec l'exécution
  LangGraph (quel nœud, quel run, quelle soumission/exercice)
- professor_validation_status/correction : boucle d'amélioration continue,
  cohérent avec le mécanisme few-shot déjà en place (§6 du résumé)

Table immuable (CreatedAtOnlyMixin) : une trace de décision IA ne devrait
jamais être modifiée après coup, seulement consultée (la validation du
prof crée un état supplémentaire, mais ne réécrit jamais la décision
originale de l'agent).
"""
import uuid
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Enum as PgEnum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domain.models.shared.mixins import CreatedAtOnlyMixin, UUIDPKMixin


class ProfessorValidationStatus(StrEnum):
    NOT_REVIEWED = "not_reviewed"
    VALIDATED = "validated"
    CORRECTED = "corrected"


class AgentDecisionLog(Base, UUIDPKMixin, CreatedAtOnlyMixin):
    __tablename__ = "agent_decision_logs"

    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: "comparison_agent"
    related_entity_type: Mapped[str] = mapped_column(String(100), nullable=False)  # ex: "Evaluation"
    related_entity_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)

    # --- Reproductibilité ---
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Explicabilité (RAG / tool calling) ---
    # Ex: [{"type": "tool_call", "name": "search_similar_variants"},
    #      {"type": "rag_document", "source": "correction_id:..."}]
    tools_consulted: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # --- Performance et coût ---
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count_output: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Traçabilité LangGraph ---
    thread_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    node_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Validation humaine (amélioration continue) ---
    professor_validation_status: Mapped[ProfessorValidationStatus] = mapped_column(
        PgEnum(ProfessorValidationStatus, name="professor_validation_status"),
        nullable=False,
        default=ProfessorValidationStatus.NOT_REVIEWED,
    )
    professor_correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    validated_by_professor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("professors.id"), nullable=True
    )