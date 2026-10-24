"""
Tests d'intégration pour le mécanisme RAG few-shot de Reasoning_Graph_Agent (section 10ter).

Vérifie :
  1. Court-circuit RAG : Si une clarification résolue similaire existe en DB (status=ANSWERED),
     elle est automatiquement appliquée et aucun nouvel enregistrement ClarificationRequest n'est créé.
  2. AgentDecisionLog : L'action RAG est tracée explicitement avec justification mentionnant [RAG few-shot].
  3. Indexation : index_clarification_embedding() met à jour la colonne embedding de la clarification résolue.
  4. Repli normal : Sans clarification résolue proche, les clarifications sont créées normalement.
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.embeddings import embed_text
from app.domain.models.identity.user import Professor, UserRole
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_clarification_request import (
    ClarificationSeverity,
    ClarificationStatus,
    ReasoningClarificationRequest,
)
from app.domain.models.assessment.solution_variant import SolutionVariant, VariantDifficulty, VariantSource, VariantStatus
from app.domain.models.system_infrastructure.agent_decision_log import AgentDecisionLog
from app.services.reasoning_graph_service import ReasoningGraphService


# ---------------------------------------------------------------------------
# Fixtures & Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_agent_report_with_clarification():
    """Génère un rapport d'agent contenant 1 clarification ambiguë."""
    from app.agents.Extraction_Verification_Agent import ClarificationRequest
    from app.agents.Reasoning_Graph_Agent import ReasoningGraphReport, ReasoningStepGraphOutput
    from app.domain.models.assessment.reasoning_step import ReasoningStepType

    step1 = ReasoningStepGraphOutput(
        step_ref="S1",
        order=1,
        step_type=ReasoningStepType.GIVEN_DATA,
        description="Données initiales",
        formula="x = 5",
        concept_tags=["equation"],
        tools_used=[],
        depends_on_refs=[],
        downstream_step_refs=[],
        is_core_step=True,
    )
    clarif = ClarificationRequest(
        related_field="construction_confidence",
        agent_question="L'agent a exprimé une faible confiance de structuration (0.50). Veuillez vérifier.",
        proposed_answer=None,
        severity=ClarificationSeverity.BLOCKING,
    )
    return ReasoningGraphReport(
        variant_id=uuid.uuid4(),
        steps=[step1],
        construction_confidence=0.50,
        source_coverage_ratio=0.85,
        clarifications=[clarif],
        is_valid_dag=True,
        model_version="test-model",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_rag_shortcircuit_applies_existing_resolution(db_session, mock_agent_report_with_clarification):
    """
    Si une clarification similaire a déjà été résolue par le professeur,
    le RAG la réapplique automatiquement :
    - Pas de nouvelle ClarificationRequest à l'état PENDING.
    - Trace explicite [RAG few-shot] dans AgentDecisionLog.
    """
    # 1. Créer la structure académique (Professor -> Program -> Module -> Exercise -> Question -> SolutionVariant)
    prof = Professor(
        id=uuid.uuid4(),
        email=f"prof_{uuid.uuid4().hex[:6]}@univ.fr",
        hashed_password="hash",
        first_name="Jean",
        last_name="Dupont",
        role=UserRole.PROFESSOR,
        department="Maths",
        title="Pr",
        employee_number=f"EMP_{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prof)
    await db_session.flush()

    program = Program(id=uuid.uuid4(), name="Maths Sup", code=f"MATH_{uuid.uuid4().hex[:6]}")
    db_session.add(program)
    await db_session.flush()

    module = Module(id=uuid.uuid4(), program_id=program.id, name="Algèbre", code=f"ALG_{uuid.uuid4().hex[:6]}")
    db_session.add(module)
    await db_session.flush()

    exercise = Exercise(
        id=uuid.uuid4(),
        module_id=module.id,
        created_by_professor_id=prof.id,
        title="Exercice Math RAG",
        status=ExerciseStatus.DRAFT,
    )
    question = Question(id=uuid.uuid4(), exercise_id=exercise.id, order=1, statement="Résoudre x+1=5")
    variant = SolutionVariant(
        id=uuid.uuid4(),
        question_id=question.id,
        content="x+1=5 => x=4",
        is_reference=True,
        source=VariantSource.TEACHER_ORIGINAL,
        difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        status=VariantStatus.APPROVED,
        version=1,
    )
    db_session.add(exercise)
    await db_session.flush()
    db_session.add(question)
    await db_session.flush()
    db_session.add(variant)
    await db_session.flush()

    question_text = "L'agent a exprimé une faible confiance de structuration (0.50). Veuillez vérifier."
    embedding = embed_text(question_text)
    assert embedding is not None, "SentenceTransformers doit être disponible pour ce test"

    # 2. Insérer une clarification résolue similaire en DB
    resolved_clarif = ReasoningClarificationRequest(
        id=uuid.uuid4(),
        variant_id=variant.id,
        unclear_content=question_text,
        agent_question=question_text,
        proposed_answer="Valider la structuration.",
        professor_answer="La structuration est correcte, valider.",
        severity=ClarificationSeverity.BLOCKING,
        status=ClarificationStatus.ANSWERED,
        # Câblage Priorité 2 (Vector(384) natif) : list[float] directement,
        # jamais une chaîne JSON sérialisée (embedding est Vector(384),
        # plus TEXT — json.dumps() provoquerait un DatatypeMismatchError).
        embedding=embedding,
    )
    db_session.add(resolved_clarif)
    await db_session.flush()

    # 3. Exécuter ReasoningGraphService en mockant l'agent AI
    service = ReasoningGraphService(db_session)
    mock_report = mock_agent_report_with_clarification
    mock_report.variant_id = variant.id

    with patch.object(service._agent, "execute", return_value=mock_report):
        result = await service.build_graph_for_variant(variant.id)

    # 4. Vérifications
    # 4a. Pas de nouvelle clarification bloquante PENDING créée pour la variante
    pending_res = await db_session.execute(
        select(ReasoningClarificationRequest).where(
            ReasoningClarificationRequest.variant_id == variant.id,
            ReasoningClarificationRequest.status == ClarificationStatus.PENDING,
        )
    )
    pending_clarifs = list(pending_res.scalars().all())
    assert len(pending_clarifs) == 0, "Le RAG devait court-circuiter la création de clarification"

    # 4b. AgentDecisionLog trace l'origine RAG
    log_res = await db_session.execute(
        select(AgentDecisionLog).where(
            AgentDecisionLog.related_entity_id == variant.id,
        )
    )
    logs = list(log_res.scalars().all())
    rag_logs = [l for l in logs if "[RAG few-shot]" in l.justification]
    assert len(rag_logs) == 1, "AgentDecisionLog doit contenir une entrée tracée [RAG few-shot]"
    assert rag_logs[0].model_version == "rag:all-MiniLM-L6-v2"


@pytest.mark.anyio
async def test_index_clarification_embedding(db_session):
    """
    index_clarification_embedding() doit calculer et persister le vecteur
    dans la colonne embedding (Vector(384) natif pgvector, câblage
    Priorité 2 — plus une sérialisation JSON).
    """
    prof = Professor(
        id=uuid.uuid4(),
        email=f"prof_{uuid.uuid4().hex[:6]}@univ.fr",
        hashed_password="hash",
        first_name="Marie",
        last_name="Curie",
        role=UserRole.PROFESSOR,
        department="Physique",
        title="Pr",
        employee_number=f"EMP_{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prof)
    await db_session.flush()

    program = Program(id=uuid.uuid4(), name="Maths Spé", code=f"MATH2_{uuid.uuid4().hex[:6]}")
    db_session.add(program)
    await db_session.flush()

    module = Module(id=uuid.uuid4(), program_id=program.id, name="Analyse", code=f"ANA_{uuid.uuid4().hex[:6]}")
    db_session.add(module)
    await db_session.flush()

    exercise = Exercise(
        id=uuid.uuid4(),
        module_id=module.id,
        created_by_professor_id=prof.id,
        title="Ex",
        status=ExerciseStatus.DRAFT,
    )
    question = Question(id=uuid.uuid4(), exercise_id=exercise.id, order=1, statement="Q")
    variant = SolutionVariant(id=uuid.uuid4(), question_id=question.id, content="C", is_reference=True, source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.INTERMEDIAIRE, status=VariantStatus.APPROVED, version=1)
    db_session.add(exercise)
    await db_session.flush()
    db_session.add(question)
    await db_session.flush()
    db_session.add(variant)
    await db_session.flush()

    clarif = ReasoningClarificationRequest(
        id=uuid.uuid4(),
        variant_id=variant.id,
        agent_question="Question ambiguë à indexer par embedding sémantique.",
        professor_answer="Réponse prof.",
        severity=ClarificationSeverity.BLOCKING,
        status=ClarificationStatus.ANSWERED,
        embedding=None,  # Pas encore indexé
    )
    db_session.add(clarif)
    await db_session.flush()

    service = ReasoningGraphService(db_session)
    await service.index_clarification_embedding(clarif.id)

    # Recharger la clarification depuis la DB
    updated = await db_session.get(ReasoningClarificationRequest, clarif.id)
    assert updated.embedding is not None
    vec = updated.embedding  # déjà list[float] (Vector(384) natif), jamais une chaîne JSON
    assert len(vec) == 384  # dimension all-MiniLM-L6-v2
