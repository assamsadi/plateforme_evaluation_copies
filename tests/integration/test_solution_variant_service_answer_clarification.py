"""
Test d'intégration ciblé — correctif SolutionVariantService.answer_clarification.

Bug réel trouvé lors du chantier RAG (câblage HITL indexation, Priorité 1) :
answer_clarification() appelait self._clarification_repo.answer(request_id=,
professor_id=, answer=) alors que la VRAIE signature du repository est
answer(request_id, professor_answer, answered_by_professor_id) — un
TypeError certain à l'exécution, jamais détecté par les tests unitaires
existants car ceux-ci mockent entièrement clarification_repo (AsyncMock
accepte n'importe quel kwarg silencieusement, ne peut pas détecter un
mauvais nom de paramètre). Ce test utilise le VRAI repository contre une
vraie DB pour que ce genre de régression soit détectable à l'avenir.
"""
import uuid

import pytest
from sqlalchemy import select

from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationStatus,
    ReasoningClarificationRequest,
)
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.repositories.reasoning_clarification_request_repository import (
    SQLAlchemyReasoningClarificationRequestRepository,
)
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.repositories.validated_alternative_answer_repository import (
    SQLAlchemyValidatedAlternativeAnswerRepository,
)
from app.services.solution_variant_service import SolutionVariantService


@pytest.mark.anyio
async def test_answer_clarification_persists_real_answer_via_real_repository(db_session):
    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add(module)
    await db_session.flush()

    user_repo = SQLAlchemyUserRepository(db_session)
    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Fix", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice answer_clarification", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    question = Question(exercise_id=exercise.id, order=1, statement="Question test.")
    db_session.add(question)
    await db_session.flush()

    clarification = ReasoningClarificationRequest(
        related_entity_type="Question", related_entity_id=question.id,
        agent_question="Le barème proposé est-il correct ?",
        proposed_answer=None,
    )
    db_session.add(clarification)
    await db_session.flush()

    service = SolutionVariantService(
        variant_repo=SQLAlchemySolutionVariantRepository(db_session),
        clarification_repo=SQLAlchemyReasoningClarificationRequestRepository(db_session),
        user_repo=user_repo,
        validated_answer_repo=SQLAlchemyValidatedAlternativeAnswerRepository(db_session),
    )

    result = await service.answer_clarification(
        request_id=clarification.id, professor_id=professor.id, answer="Oui, c'est correct.",
    )

    assert result.status == ClarificationStatus.ANSWERED
    assert result.professor_answer == "Oui, c'est correct."
    assert result.answered_by_professor_id == professor.id
    assert result.answered_by_professor_name == "Prof Fix"

    stmt = select(ReasoningClarificationRequest).where(ReasoningClarificationRequest.id == clarification.id)
    persisted = (await db_session.execute(stmt)).scalar_one()
    assert persisted.professor_answer == "Oui, c'est correct."
    assert persisted.answered_by_professor_id == professor.id
    assert persisted.status == ClarificationStatus.ANSWERED
