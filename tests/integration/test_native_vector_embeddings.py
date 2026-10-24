"""
Test d'intégration — Vector(384) natif pgvector (câblage Priorité 2,
chantier RAG). Contre le VRAI Docker Postgres de ce projet
(pgvector/pgvector:pg16, cf. docker-compose.yml), extension réellement
active — plus un test qui mocke/simule la disponibilité de pgvector comme
tests/unit/repositories/test_rag_repository.py (qui reste valide pour le
repli NumPy, non affecté par ce câblage).

Couvre :
  1. _check_pgvector() détecte réellement l'extension sur CE Postgres.
  2. search_similar() emprunte réellement la branche SQL pgvector (pas
     NumPy) et retourne un résultat correct.
  3. Écriture ORM (list[float] direct, Vector(384)) réussit contre la
     colonne native — round-trip lecture/écriture exact.

Le test du garde-fou de migration (échec explicite si pgvector absent) vit
dans tests/unit/test_migration_native_vector_embeddings.py — pur (connexion
mockée, aucun DB réel), déplacé hors de ce dossier car tests/integration/
conftest.py applique un fixture autouse db_session (async) à tout ce
dossier, y compris des tests synchrones qui n'en ont pas besoin.
"""
import uuid

import pytest

from app.core.embeddings import embed_text
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationSeverity,
    ClarificationStatus,
    ReasoningClarificationRequest,
)
from app.domain.models.assessment.validated_alternative_answer import ValidatedAlternativeAnswer
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.repositories.rag_repository import _check_pgvector, search_similar
import app.repositories.rag_repository as rag_repository_module


@pytest.mark.anyio
async def test_check_pgvector_detects_real_extension(db_session):
    """
    L'extension vector est réellement active sur CE Postgres Docker
    (pgvector/pgvector:pg16, cf. docker-compose.yml) — pas seulement sur
    l'installation locale directe utilisée pour le diagnostic initial.
    """
    rag_repository_module._pgvector_available = None  # force une redétection réelle
    detected = await _check_pgvector(db_session)
    assert detected is True


async def _seed_question(db_session):
    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()

    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    db_session.add(module)
    await db_session.flush()

    user_repo = SQLAlchemyUserRepository(db_session)
    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Vec", department="Maths", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice vector natif", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    question = Question(exercise_id=exercise.id, order=1, statement="Question test vector natif.")
    db_session.add(question)
    await db_session.flush()

    return question, professor


@pytest.mark.anyio
async def test_orm_write_read_round_trip_native_vector(db_session):
    """
    Écriture ORM directe (list[float], jamais json.dumps) contre la colonne
    Vector(384) native, relecture exacte — les deux tables concernées.
    """
    question, professor = await _seed_question(db_session)
    vec = embed_text("Texte de test pour le round-trip vector natif.")
    assert vec is not None and len(vec) == 384

    answer = ValidatedAlternativeAnswer(
        question_id=question.id, criterion_id="crit-vec", answer_text="Réponse test.",
        validated_by_professor_id=professor.id, embedding=vec,
    )
    clarif = ReasoningClarificationRequest(
        related_entity_type="Question", related_entity_id=question.id,
        agent_question="Question test vector natif ?", proposed_answer=None,
        severity=ClarificationSeverity.BLOCKING, status=ClarificationStatus.PENDING,
        criterion_id=None, embedding=vec,
    )
    db_session.add_all([answer, clarif])
    await db_session.flush()

    reloaded_answer = await db_session.get(ValidatedAlternativeAnswer, answer.id)
    reloaded_clarif = await db_session.get(ReasoningClarificationRequest, clarif.id)

    assert isinstance(reloaded_answer.embedding, list)
    assert len(reloaded_answer.embedding) == 384
    assert reloaded_answer.embedding == pytest.approx(vec, abs=1e-6)

    assert isinstance(reloaded_clarif.embedding, list)
    assert len(reloaded_clarif.embedding) == 384
    assert reloaded_clarif.embedding == pytest.approx(vec, abs=1e-6)


@pytest.mark.anyio
async def test_search_similar_uses_real_pgvector_sql_branch(db_session):
    """
    search_similar() emprunte réellement la branche SQL pgvector (<=> natif),
    pas le repli NumPy — confirmé en vérifiant explicitement _check_pgvector
    AVANT l'appel (la branche empruntée dépend directement de cette valeur).
    Aucune modification de search_similar() n'a été nécessaire (cf. rapport).
    """
    question, professor = await _seed_question(db_session)
    text = "Méthode par récurrence pour démontrer la propriété."
    vec = embed_text(text)

    answer = ValidatedAlternativeAnswer(
        question_id=question.id, criterion_id="crit-vec-search", answer_text=text,
        validated_by_professor_id=professor.id, embedding=vec,
    )
    db_session.add(answer)
    await db_session.flush()

    rag_repository_module._pgvector_available = None
    assert await _check_pgvector(db_session) is True  # confirme la branche empruntée

    matches = await search_similar(
        session=db_session, embedding_query=vec,
        table_name="validated_alternative_answers", embedding_column="embedding",
        id_column="id", payload_columns=["answer_text"],
        filter_clauses="question_id = :question_id AND criterion_id = :criterion_id",
        filter_params={"question_id": str(question.id), "criterion_id": "crit-vec-search"},
        top_k=1, similarity_threshold=0.85,
    )

    assert len(matches) == 1
    assert matches[0].similarity == pytest.approx(1.0, abs=1e-4)
    assert matches[0].payload["answer_text"] == text
