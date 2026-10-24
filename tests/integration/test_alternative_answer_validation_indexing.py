"""
Test d'intégration — câblage HITL indexation RAG (Priorité 1) :
clarification MULTIPLE_DISTINCT_ANSWERS créée par comparative_evaluation_
node -> professeur valide/rejette via SolutionVariantService.
validate_alternative_answer_clarification -> ValidatedAlternativeAnswer
indexée (embedding réel) uniquement sur acceptation, immédiatement
retrouvable par une recherche de similarité.

Contre une vraie DB (Postgres réel) — embeddings réels via sentence-
transformers, seul le jugement LLM de cohérence est mocké (même idiome
que test_comparative_evaluation_agent_rag_isolation.py).
"""
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agents.Extraction_Verification_Agent import CorrectionMode
from app.core.embeddings import embed_text
from app.core.exceptions import InvalidClarificationTypeError
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.bareme import Bareme, BaremeValidationStatus
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.extraction_correction import (
    ExtractionContentType,
    ExtractionCorrection,
    ExtractionEvidenceLevel,
)
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationSeverity,
    ClarificationStatus,
    ReasoningClarificationRequest,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.assessment.validated_alternative_answer import ValidatedAlternativeAnswer
from app.domain.repositories.reasoning_clarification_request_repository import (
    SQLAlchemyReasoningClarificationRequestRepository,
)
from app.domain.repositories.solution_variant_repository import SQLAlchemySolutionVariantRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.domain.repositories.validated_alternative_answer_repository import (
    SQLAlchemyValidatedAlternativeAnswerRepository,
)
from app.graph.nodes.comparative_evaluation_node import comparative_evaluation_node
from app.graph.state import PipelineState
from app.repositories.rag_repository import search_similar
from app.services.solution_variant_service import SolutionVariantService

LLM_PATCH_TARGET = "app.agents.Comparative_Evaluation_Agent.invoke_llm_with_fallback"

STUDENT_TEXT = (
    "Méthode alternative : utiliser le théorème de Thalès plutôt que la "
    "trigonométrie pour retrouver la longueur manquante."
)


def _mock_llm_response(payload: dict) -> tuple:
    """
    Le payload dict brut est renvoyé tel quel comme `result` (2026-08-18) —
    Comparative_Evaluation_Agent._call_llm_json fait maintenant
    response_schema.model_validate(result) ; l'ancien mock (.content, JSON
    en prose) simulait un comportement devenu obsolète, cf. mémoire de
    session.
    """
    fake_spec = MagicMock()
    fake_spec.provider = "groq"
    fake_spec.model_name = "llama-3.3-70b"
    return (payload, fake_spec, False, {"total_tokens": 100})


async def _seed_scenario(db_session):
    """Retourne (exercise, submission, question, professor)."""
    user_repo = SQLAlchemyUserRepository(db_session)

    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add_all([group, module])
    await db_session.flush()

    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="RAG", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Student",
        student_number=f"STU_{uuid.uuid4()}"[:20], group_id=group.id,
        enrollment_year=2024, level="L3",
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice validation alternative", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.PENDING_OCR, document_path="submissions/doc.pdf",
        document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    question = Question(
        exercise_id=exercise.id, order=1, statement="Calculer la longueur manquante.",
    )
    db_session.add(question)
    await db_session.flush()

    bareme = Bareme(
        question_id=question.id, points=Decimal("4.00"),
        criteria=[{
            "id": "crit-mda", "label": "Méthode utilisée", "points": 4.0,
            "correction_mode": CorrectionMode.MULTIPLE_DISTINCT_ANSWERS.value,
            "verifiable_conditions": [], "disqualifying": False, "test_cases": [],
            "reference_code": None, "expected_complexity": None,
        }],
        validation_status=BaremeValidationStatus.CONFIRMED,
    )
    db_session.add(bareme)

    correction = ExtractionCorrection(
        submission_id=submission.id, question_id=question.id,
        image_crop_path="crops/block1.png", page_number=1,
        content_type=ExtractionContentType.TEXT,
        prediction_ocr=STUDENT_TEXT,
        confidence_score=Decimal("0.9"), bounding_box={"x": 0, "y": 0, "w": 10, "h": 10},
        evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
    )
    db_session.add(correction)
    await db_session.flush()

    return exercise, submission, question, professor


def _make_state(exercise, submission) -> PipelineState:
    now = datetime.now(timezone.utc)
    return PipelineState(
        thread_id=str(submission.id), flow_type="student_evaluation", trace_id=str(submission.id),
        exercise_id=str(exercise.id), submission_id=str(submission.id), module_id=str(exercise.module_id),
        student_id=str(submission.student_id), raw_file_path=submission.document_path,
        mime_type="application/pdf", created_at=now, updated_at=now,
    )


@asynccontextmanager
async def _reuse_session(db_session):
    yield db_session


async def _run_node_and_get_clarification(db_session, exercise, submission, question):
    """Exécute comparative_evaluation_node (LLM coherence mocké COHERENT, aucun match RAG existant)."""
    payload = {"coherence_score": 0.9, "reason": "Effort réel, méthode alternative plausible."}

    with (
        patch(LLM_PATCH_TARGET, new_callable=AsyncMock) as mock_llm,
        patch(
            "app.graph.nodes.comparative_evaluation_node.get_db_context",
            lambda: _reuse_session(db_session),
        ),
    ):
        mock_llm.return_value = _mock_llm_response(payload)
        await comparative_evaluation_node(_make_state(exercise, submission))

    stmt = select(ReasoningClarificationRequest).where(
        ReasoningClarificationRequest.related_entity_id == question.id,
        ReasoningClarificationRequest.criterion_id == "crit-mda",
    )
    return (await db_session.execute(stmt)).scalar_one()


@pytest.mark.anyio
async def test_clarification_created_by_node_is_pending_with_full_answer_text(db_session):
    """
    comparative_evaluation_node persiste réellement la clarification
    "réponse alternative inédite" -> ligne PENDING, criterion_id renseigné,
    unclear_content porte le texte COMPLET (pas tronqué comme agent_question).
    """
    exercise, submission, question, _professor = await _seed_scenario(db_session)

    clarif = await _run_node_and_get_clarification(db_session, exercise, submission, question)

    assert clarif.status == ClarificationStatus.PENDING
    assert clarif.severity == ClarificationSeverity.BLOCKING
    assert clarif.related_entity_type == "Question"
    assert clarif.criterion_id == "crit-mda"
    assert clarif.unclear_content == STUDENT_TEXT
    assert clarif.proposed_answer == "Valider cette réponse alternative comme correcte."


@pytest.mark.anyio
async def test_accepting_indexes_immediately_retrievable_validated_answer(db_session):
    """
    Scénario complet demandé par le ticket : clarification créée ->
    professeur VALIDE -> nouvelle ValidatedAlternativeAnswer avec embedding
    calculé -> immédiatement retrouvable par une recherche similaire.
    """
    exercise, submission, question, professor = await _seed_scenario(db_session)
    clarif = await _run_node_and_get_clarification(db_session, exercise, submission, question)

    service = SolutionVariantService(
        variant_repo=SQLAlchemySolutionVariantRepository(db_session),
        clarification_repo=SQLAlchemyReasoningClarificationRequestRepository(db_session),
        user_repo=SQLAlchemyUserRepository(db_session),
        validated_answer_repo=SQLAlchemyValidatedAlternativeAnswerRepository(db_session),
    )

    result = await service.validate_alternative_answer_clarification(
        request_id=clarif.id, professor_id=professor.id, accepted=True,
    )

    assert result.status == ClarificationStatus.ANSWERED
    assert result.professor_answer == "Validé comme réponse alternative légitime."
    assert result.answered_by_professor_id == professor.id

    stmt = select(ValidatedAlternativeAnswer).where(
        ValidatedAlternativeAnswer.question_id == question.id,
        ValidatedAlternativeAnswer.criterion_id == "crit-mda",
    )
    answer = (await db_session.execute(stmt)).scalar_one()
    assert answer.answer_text == STUDENT_TEXT
    assert answer.validated_by_professor_id == professor.id
    assert answer.embedding is not None
    # Vector(384) natif pgvector (câblage Priorité 2) — déjà list[float],
    # jamais une chaîne JSON à parser.
    assert len(answer.embedding) == 384

    # Immédiatement retrouvable par une recherche de similarité (même texte
    # -> similarité ~1.0), exactement le chemin RAG interrogé par
    # Comparative_Evaluation_Agent._eval_multiple_distinct_answers.
    query_vec = embed_text(STUDENT_TEXT)
    matches = await search_similar(
        session=db_session, embedding_query=query_vec,
        table_name="validated_alternative_answers", embedding_column="embedding",
        id_column="id", payload_columns=["answer_text"],
        filter_clauses="question_id = :question_id AND criterion_id = :criterion_id",
        filter_params={"question_id": str(question.id), "criterion_id": "crit-mda"},
        top_k=1, similarity_threshold=0.85,
    )
    assert len(matches) == 1
    assert matches[0].payload["answer_text"] == STUDENT_TEXT


@pytest.mark.anyio
async def test_rejecting_indexes_nothing(db_session):
    """Rejet du professeur -> clarification résolue, AUCUNE indexation."""
    exercise, submission, question, professor = await _seed_scenario(db_session)
    clarif = await _run_node_and_get_clarification(db_session, exercise, submission, question)

    service = SolutionVariantService(
        variant_repo=SQLAlchemySolutionVariantRepository(db_session),
        clarification_repo=SQLAlchemyReasoningClarificationRequestRepository(db_session),
        user_repo=SQLAlchemyUserRepository(db_session),
        validated_answer_repo=SQLAlchemyValidatedAlternativeAnswerRepository(db_session),
    )

    result = await service.validate_alternative_answer_clarification(
        request_id=clarif.id, professor_id=professor.id, accepted=False,
    )

    assert result.status == ClarificationStatus.ANSWERED
    assert result.professor_answer == "Rejeté — traité comme incorrect."

    stmt = select(ValidatedAlternativeAnswer).where(
        ValidatedAlternativeAnswer.question_id == question.id,
    )
    assert (await db_session.execute(stmt)).scalars().all() == []


@pytest.mark.anyio
async def test_validate_endpoint_refuses_non_multiple_distinct_answers_clarification(db_session):
    """
    Garde-fou — une clarification SANS criterion_id (ex. Extraction_
    Verification_Agent, related_entity_type="Question" mais pas MULTIPLE_
    DISTINCT_ANSWERS) ne doit JAMAIS être acceptée par ce endpoint dédié :
    jamais un accept/reject deviné pour un type de clarification qui n'a
    pas cette sémantique.
    """
    exercise, submission, question, professor = await _seed_scenario(db_session)

    other_clarif = ReasoningClarificationRequest(
        related_entity_type="Question", related_entity_id=question.id,
        agent_question="Le barème proposé est-il correct ?",
        proposed_answer=None, severity=ClarificationSeverity.BLOCKING,
        criterion_id=None,
    )
    db_session.add(other_clarif)
    await db_session.flush()

    service = SolutionVariantService(
        variant_repo=SQLAlchemySolutionVariantRepository(db_session),
        clarification_repo=SQLAlchemyReasoningClarificationRequestRepository(db_session),
        user_repo=SQLAlchemyUserRepository(db_session),
        validated_answer_repo=SQLAlchemyValidatedAlternativeAnswerRepository(db_session),
    )

    with pytest.raises(InvalidClarificationTypeError):
        await service.validate_alternative_answer_clarification(
            request_id=other_clarif.id, professor_id=professor.id, accepted=True,
        )
