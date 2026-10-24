"""
Tests unitaires pour ExerciseSection et l'agrégat Exercise avec sections.
"""
import uuid
from unittest.mock import AsyncMock

import pytest

from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.exercise_section import ExerciseSection
from app.domain.models.assessment.question import Question
from app.domain.schemas.exercise_schemas import (
    BaremeRead,
    ExerciseRead,
    QuestionRead,
    SectionCreate,
    SectionRead,
)


def test_exercise_section_instantiation():
    sid = uuid.uuid4()
    eid = uuid.uuid4()
    section = ExerciseSection(
        id=sid,
        exercise_id=eid,
        order=1,
        title="Partie A : Algèbre",
    )
    assert section.id == sid
    assert section.exercise_id == eid
    assert section.order == 1
    assert section.title == "Partie A : Algèbre"


def test_section_schema_validation():
    create_dto = SectionCreate(order=1, title="Exercice 1")
    assert create_dto.order == 1
    assert create_dto.title == "Exercice 1"

    sid = uuid.uuid4()
    eid = uuid.uuid4()
    read_dto = SectionRead(id=sid, exercise_id=eid, order=1, title="Exercice 1")
    assert read_dto.id == sid
    assert read_dto.exercise_id == eid
    assert read_dto.order == 1
    assert read_dto.title == "Exercice 1"


def test_exercise_read_includes_sections():
    eid = uuid.uuid4()
    mid = uuid.uuid4()
    pid = uuid.uuid4()
    sid = uuid.uuid4()

    read_dto = ExerciseRead(
        id=eid,
        module_id=mid,
        module_name="Mathématiques",
        course_id=None,
        created_by_professor_id=pid,
        professor_full_name="Prof Test",
        title="Examen Algèbre",
        description="Sujet d'examen",
        status=ExerciseStatus.DRAFT,
        deadline=None,
        difficulty_level=None,
        sections=[SectionRead(id=sid, exercise_id=eid, order=1, title="Partie A")],
        questions=[
            QuestionRead(
                id=uuid.uuid4(),
                exercise_id=eid,
                section_id=sid,
                order=1,
                statement="Question 1.1",
                attachment_path=None,
                bareme=None,
            )
        ],
    )
    assert len(read_dto.sections) == 1
    assert read_dto.sections[0].id == sid
    assert read_dto.questions[0].section_id == sid
