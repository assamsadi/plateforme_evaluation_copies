"""
Test d'intégration — câblage Priorité 3 : isolation RAG entre
validated_alternative_answers (Comparative_Evaluation_Agent,
MULTIPLE_DISTINCT_ANSWERS) et reasoning_clarification_requests
(Reasoning_Graph_Agent, few-shot §10ter).

Contre une vraie DB (embeddings réels via sentence-transformers, pas de
mock sur embed_text/search_similar — seul le jugement LLM de cohérence est
mocké, même idiome que tests/unit/agents/test_comparative_evaluation_agent.py).

Preuve en 2 temps, sur le MÊME texte étudiant (similarité ~1.0 garantie) :
  1. Une ReasoningClarificationRequest ANSWERED, avec un embedding calculé
     sur ce texte exact, existe déjà — AUCUNE ValidatedAlternativeAnswer
     n'existe encore. La recherche RAG de _eval_multiple_distinct_answers
     ne doit RIEN trouver (elle ne doit jamais lire
     reasoning_clarification_requests) : verdict non satisfait +
     ClarificationRequest "réponse alternative inédite" créée.
  2. On ajoute ensuite une ValidatedAlternativeAnswer sur le même
     (question_id, criterion_id) avec le même texte : la MÊME recherche
     RAG doit désormais trouver un match, prouvant que la table interrogée
     est bien la bonne (pas juste "aucune des deux ne matche jamais").
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.Comparative_Evaluation_Agent import (
    ComparativeEvaluationAgent,
    CriterionEvaluationInput,
    EvaluationRequest,
    StudentResponseInput,
)
from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import CorrectionMode
from app.core.embeddings import embed_text
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationStatus,
    ReasoningClarificationRequest,
)
from app.domain.models.assessment.validated_alternative_answer import (
    ValidatedAlternativeAnswer,
)
from app.domain.repositories.user_repository import SQLAlchemyUserRepository

LLM_PATCH_TARGET = "app.agents.Comparative_Evaluation_Agent.invoke_llm_with_fallback"

STUDENT_TEXT = (
    "Utiliser la formule de Héron : aire = racine(p(p-a)(p-b)(p-c)), "
    "avec p le demi-périmètre du triangle."
)


def _mock_llm_response(payload: dict) -> tuple:
    """
    Le payload dict brut est renvoyé tel quel comme `result` (2026-08-18) —
    Comparative_Evaluation_Agent._call_llm_json fait maintenant
    response_schema.model_validate(result), donc un dict brut est
    directement consommable, quel que soit le schéma attendu par le site
    d'appel (jamais besoin de connaître le type exact ici). Avant ce fix,
    ce mock simulait l'ancien comportement (JSON extrait par regex d'une
    réponse en prose, .content) — devenu obsolète, cf. mémoire de session.
    """
    fake_spec = MagicMock()
    fake_spec.provider = "groq"
    fake_spec.model_name = "llama-3.3-70b"
    return (payload, fake_spec, False, {"total_tokens": 100})


async def _seed_question(db_session) -> tuple[uuid.UUID, uuid.UUID]:
    """Retourne (question_id, professor_id)."""
    user_repo = SQLAlchemyUserRepository(db_session)

    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add(module)
    await db_session.flush()

    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="RAG", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice isolation RAG", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    question = Question(
        exercise_id=exercise.id, order=1,
        statement="Donner une méthode pour calculer la surface d'un triangle",
    )
    db_session.add(question)
    await db_session.flush()

    return question.id, professor.id


def _build_request(question_id: uuid.UUID) -> EvaluationRequest:
    return EvaluationRequest(
        question_id=question_id,
        question_statement="Donner une méthode pour calculer la surface d'un triangle",
        student_response=StudentResponseInput(
            question_id=question_id, student_answer_text=STUDENT_TEXT,
        ),
        criteria=[
            CriterionEvaluationInput(
                criterion_id="crit_mda", label="Méthode de calcul",
                points=Decimal("2.0"), correction_mode=CorrectionMode.MULTIPLE_DISTINCT_ANSWERS,
            )
        ],
    )


@pytest.mark.anyio
async def test_high_similarity_reasoning_clarification_never_matched(db_session):
    """
    Preuve 1/2 — une ReasoningClarificationRequest ANSWERED avec un
    embedding calculé sur EXACTEMENT le même texte que la réponse
    étudiante (similarité ~1.0, le cas le plus favorable possible à un
    faux positif) ne doit JAMAIS produire de match : la recherche RAG de
    MULTIPLE_DISTINCT_ANSWERS n'interroge jamais cette table.
    """
    question_id, professor_id = await _seed_question(db_session)

    vec = embed_text(STUDENT_TEXT)
    assert vec is not None  # sentence-transformers doit être disponible ici

    clarif = ReasoningClarificationRequest(
        related_entity_type="question",
        related_entity_id=question_id,
        agent_question=STUDENT_TEXT,
        proposed_answer=None,
        status=ClarificationStatus.ANSWERED,
        professor_answer="Oui, méthode valide.",
        answered_by_professor_id=professor_id,
        embedding=vec,  # Vector(384) natif (câblage Priorité 2) — list[float] direct, jamais du JSON
    )
    db_session.add(clarif)
    await db_session.flush()

    agent = ComparativeEvaluationAgent()
    ctx = AgentExecutionContext(
        trace_id="t1", flow_type="student_evaluation", db_session=db_session,
    )
    req = _build_request(question_id)

    payload = {"coherence_score": 0.9, "reason": "Réponse mathématique cohérente"}
    with patch(LLM_PATCH_TARGET, new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _mock_llm_response(payload)
        report = await agent.execute(req, ctx)

    res = report.criterion_results[0]
    # Aucun match malgré une similarité quasi parfaite dans l'AUTRE table :
    # validated_alternative_answers est vide, reasoning_clarification_requests
    # n'est jamais consultée par cette recherche.
    assert res.is_satisfied is False
    assert res.score_ratio == 0.0
    assert res.clarification_request is not None
    assert "alternative inédite" in res.clarification_request.agent_question


@pytest.mark.anyio
async def test_matches_once_validated_alternative_answer_indexed(db_session):
    """
    Preuve 2/2 — même scénario, mais avec la ValidatedAlternativeAnswer
    correspondante réellement indexée (question_id/criterion_id/texte
    identiques) : la recherche doit désormais matcher. Confirme que
    l'absence de match ci-dessus n'est pas un accident (RAG cassé/table
    vide en général) mais bien une isolation stricte par table.
    """
    question_id, professor_id = await _seed_question(db_session)

    # Même texte dans reasoning_clarification_requests que le test
    # précédent (bruit potentiel) — doit rester sans effet ici aussi.
    vec = embed_text(STUDENT_TEXT)
    clarif = ReasoningClarificationRequest(
        related_entity_type="question",
        related_entity_id=question_id,
        agent_question=STUDENT_TEXT,
        proposed_answer=None,
        status=ClarificationStatus.ANSWERED,
        professor_answer="Oui, méthode valide.",
        answered_by_professor_id=professor_id,
        embedding=vec,  # Vector(384) natif (câblage Priorité 2) — list[float] direct, jamais du JSON
    )
    db_session.add(clarif)

    validated_answer = ValidatedAlternativeAnswer(
        question_id=question_id,
        criterion_id="crit_mda",
        answer_text=STUDENT_TEXT,
        validated_by_professor_id=professor_id,
        embedding=vec,  # Vector(384) natif (câblage Priorité 2) — list[float] direct, jamais du JSON
    )
    db_session.add(validated_answer)
    await db_session.flush()

    agent = ComparativeEvaluationAgent()
    ctx = AgentExecutionContext(
        trace_id="t2", flow_type="student_evaluation", db_session=db_session,
    )
    req = _build_request(question_id)

    payload = {"coherence_score": 0.9, "reason": "Réponse mathématique cohérente"}
    with patch(LLM_PATCH_TARGET, new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = _mock_llm_response(payload)
        report = await agent.execute(req, ctx)

    res = report.criterion_results[0]
    assert res.is_satisfied is True
    assert res.score_ratio == 1.0
    assert res.clarification_request is None
