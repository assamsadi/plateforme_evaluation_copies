import uuid
from decimal import Decimal
import pytest
from pydantic import ValidationError

from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.schemas.exercise_schemas import (
    BaremeCreate,
    CriterionCreate,
    ExerciseCreateRequest,
    ExercisePublishRequest,
    QuestionCreate,
)


def test_bareme_criteria_sum_exceeds_total():
    with pytest.raises(ValidationError) as exc:
        BaremeCreate(
            points=Decimal("10.0"),
            criteria=[
                CriterionCreate(label="Criterion 1", points=Decimal("6.0")),
                CriterionCreate(label="Criterion 2", points=Decimal("5.0")),
            ],
        )
    assert "dépace le total du barème" in str(exc.value) or "dépasse" in str(exc.value)


def test_bareme_criteria_valid():
    b = BaremeCreate(
        points=Decimal("10.0"),
        criteria=[
            CriterionCreate(label="Criterion 1", points=Decimal("5.0")),
            CriterionCreate(label="Criterion 2", points=Decimal("5.0")),
        ],
    )
    assert b.points == Decimal("10.0")
    assert len(b.criteria) == 2


def test_exercise_create_request_duplicate_orders():
    mid = uuid.uuid4()
    b = BaremeCreate(points=Decimal("5.0"))
    with pytest.raises(ValidationError) as exc:
        ExerciseCreateRequest(
            module_id=mid,
            title="Test Exercise",
            questions=[
                QuestionCreate(order=1, statement="Q1", bareme=b),
                QuestionCreate(order=1, statement="Q2", bareme=b),  # Duplicate order 1
            ],
        )
    assert "numéros d'ordre des questions doivent être uniques" in str(exc.value)


def test_exercise_publish_request_missing_course_or_deadline():
    with pytest.raises(ValidationError) as exc:
        ExercisePublishRequest(
            status=ExerciseStatus.PUBLISHED_AS_EXAM,
            course_id=None,
            deadline=None,
        )
    assert "obligatoire pour le statut" in str(exc.value)


def test_exercise_publish_request_valid_exam():
    cid = uuid.uuid4()
    from datetime import datetime, timezone
    req = ExercisePublishRequest(
        status=ExerciseStatus.PUBLISHED_AS_EXAM,
        course_id=cid,
        deadline=datetime.now(timezone.utc),
    )
    assert req.course_id == cid
