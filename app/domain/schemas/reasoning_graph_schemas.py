"""
Schémas Pydantic pour Reasoning_Graph_Agent et ReasoningGraphService.
"""
import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.assessment.reasoning_step import ReasoningStepType
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode


class CompetencyWeightRead(BaseModel):
    code: C2PCTSkillCode
    weight: float = Field(..., ge=0.0, le=1.0)


class ReasoningStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    variant_id: uuid.UUID
    order: int
    step_type: ReasoningStepType
    description: str
    formula: str | None = None
    concept_tags: list[str] = []
    tools_used: list[str] = []
    related_competency_code: C2PCTSkillCode | None = None
    extraction_signals: dict | None = None
    version: int = 1
    superseded_by: uuid.UUID | None = None
    created_at: datetime | None = None


class ReasoningGraphRead(BaseModel):
    variant_id: uuid.UUID
    construction_confidence: float
    is_valid_dag: bool
    step_count: int
    blocking_clarification_count: int = 0
    model_version: str | None = None


class QuestionCascadeInvalidationReport(BaseModel):
    """Compte-rendu d'invalidation en cascade scopée par question."""
    question_id: uuid.UUID
    question_order: int
    invalidated_variant_ids: list[uuid.UUID]
    professor_message: str
