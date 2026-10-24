import uuid
import pytest
from pydantic import ValidationError

from app.domain.models.assessment.reasoning_step import ReasoningStepType
from app.domain.models.assessment.solution_variant import (
    VariantDifficulty,
    VariantSource,
)


from app.domain.schemas.solution_schemas import (
    ReasoningStepCreate,
    SolutionVariantCreate,
)


def test_solution_variant_duplicate_step_refs():
    qid = uuid.uuid4()
    with pytest.raises(ValidationError) as exc:
        SolutionVariantCreate(
            question_id=qid,
            content="Solution content",
            source=VariantSource.TEACHER_ORIGINAL,
            difficulty_level=VariantDifficulty.INTERMEDIAIRE,
            reasoning_steps=[
                ReasoningStepCreate(step_ref="s1", order=1, step_type=ReasoningStepType.GIVEN_DATA, description="Step 1"),
                ReasoningStepCreate(step_ref="s1", order=2, step_type=ReasoningStepType.COMPUTATION, description="Step 2"),
            ],
        )
    assert "step_ref doivent être uniques" in str(exc.value)


def test_solution_variant_self_dependency():
    qid = uuid.uuid4()
    with pytest.raises(ValidationError) as exc:
        SolutionVariantCreate(
            question_id=qid,
            content="Solution content",
            source=VariantSource.TEACHER_ORIGINAL,
            difficulty_level=VariantDifficulty.INTERMEDIAIRE,
            reasoning_steps=[
                ReasoningStepCreate(
                    step_ref="s1",
                    order=1,
                    step_type=ReasoningStepType.GIVEN_DATA,
                    description="Step 1",
                    depends_on_refs=["s1"],  # Self-dependency
                ),
            ],
        )
    assert "ne peut pas dépendre d'elle-même" in str(exc.value)


def test_solution_variant_cycle_detection():
    qid = uuid.uuid4()
    with pytest.raises(ValidationError) as exc:
        SolutionVariantCreate(
            question_id=qid,
            content="Solution content",
            source=VariantSource.TEACHER_ORIGINAL,
            difficulty_level=VariantDifficulty.INTERMEDIAIRE,
            reasoning_steps=[
                ReasoningStepCreate(
                    step_ref="s1", order=1, step_type=ReasoningStepType.GIVEN_DATA, description="Step 1", depends_on_refs=["s2"]
                ),
                ReasoningStepCreate(
                    step_ref="s2", order=2, step_type=ReasoningStepType.COMPUTATION, description="Step 2", depends_on_refs=["s1"]
                ),
            ],
        )
    assert "Cycle détecté" in str(exc.value)


def test_solution_variant_valid_dag():
    qid = uuid.uuid4()
    variant = SolutionVariantCreate(
        question_id=qid,
        content="Solution content",
        source=VariantSource.TEACHER_ORIGINAL,
        difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        reasoning_steps=[
            ReasoningStepCreate(step_ref="s1", order=1, step_type=ReasoningStepType.GIVEN_DATA, description="Step 1"),
            ReasoningStepCreate(
                step_ref="s2", order=2, step_type=ReasoningStepType.COMPUTATION, description="Step 2", depends_on_refs=["s1"]
            ),
        ],
    )
    assert len(variant.reasoning_steps) == 2

