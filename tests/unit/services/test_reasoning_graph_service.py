"""
Tests unitaires pour ReasoningGraphService.

Couverture :
- Build de graphe et persistance transactionnelle complète (steps, deps, log, clarifs)
- Exception si variante introuvable
- Exception si exercice déjà publié (ExerciseAlreadyPublishedError)
- Exécution parallélisée build_graphs_for_variants_parallel
- Invalidation en cascade scopée par question (invalidate_cascade_for_question)
- Incrémentation de version et superseded_by lors de la régénération d'un graphe
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.Reasoning_Graph_Agent import ReasoningGraphReport, ReasoningStepGraphOutput
from app.agents.reasoning_graph_exceptions import (
    ExerciseAlreadyPublishedError,
    VariantNotFoundError,
)
from app.domain.models import Module, Professor, Program
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepType
from app.domain.models.assessment.solution_variant import (
    SolutionVariant,
    VariantDifficulty,
    VariantSource,
    VariantStatus,
)
from app.services.reasoning_graph_service import ReasoningGraphService


async def _create_test_exercise(
    db_session: AsyncSession,
    status: ExerciseStatus = ExerciseStatus.DRAFT,
) -> Exercise:
    uid = uuid.uuid4().hex[:8]
    prog = Program(name=f"Prog_{uid}", code=f"P_{uid}")
    db_session.add(prog)
    await db_session.flush()

    mod = Module(program_id=prog.id, name=f"Mod_{uid}", code=f"M_{uid}")
    db_session.add(mod)
    await db_session.flush()

    prof = Professor(
        email=f"prof_{uid}@test.com",
        hashed_password="hash",
        first_name="Prof",
        last_name="Test",
        department="Maths",
        title="Dr",
        employee_number=f"EMP_{uid}",
    )
    db_session.add(prof)
    await db_session.flush()

    ex = Exercise(
        module_id=mod.id,
        created_by_professor_id=prof.id,
        title=f"Exercice_{uid}",
        status=status,
    )
    db_session.add(ex)
    await db_session.flush()
    return ex


def _fake_report(step_ids: list[uuid.UUID]) -> ReasoningGraphReport:
    """
    Reasoning_Graph_Agent v2 (cf. mémoire de session) : enrichit des
    ReasoningStep déjà persistés, jamais un texte brut — step_ref DOIT
    correspondre à un vrai ReasoningStep.id existant pour que
    build_graph_for_variant puisse le retrouver (steps_by_id.get(...)),
    sinon l'enrichissement de ce step est silencieusement ignoré (cf.
    docstring build_graph_for_variant : "ne devrait jamais arriver : step_ref
    vient de existing_steps lui-même" — vrai seulement si l'appelant, ici le
    test, respecte ce contrat).
    """
    return ReasoningGraphReport(
        variant_id=uuid.uuid4(),  # jamais lu par build_graph_for_variant, indicatif seulement
        steps=[
            ReasoningStepGraphOutput(
                step_ref=str(step_ids[0]),
                order=1,
                step_type=ReasoningStepType.GIVEN_DATA,
                description="Donnée initiale",
                source_span="Donnée",
            ),
            ReasoningStepGraphOutput(
                step_ref=str(step_ids[1]),
                order=2,
                step_type=ReasoningStepType.CONCLUSION,
                description="Résultat final",
                depends_on_refs=[str(step_ids[0])],
                downstream_step_refs=[],
                source_span="Résultat",
            ),
        ],
        construction_confidence=0.9,
        clarifications=[],
        is_valid_dag=True,
        model_version="groq:llama-3.3-70b",
    )


@pytest.mark.anyio
class TestReasoningGraphService:
    async def test_build_graph_for_variant_success(self, db_session: AsyncSession):
        exercise = await _create_test_exercise(db_session, ExerciseStatus.DRAFT)

        question = Question(
            exercise_id=exercise.id,
            order=1,
            statement="Statement Q1",
        )
        db_session.add(question)
        await db_session.flush()

        variant = SolutionVariant(
            question_id=question.id,
            content="Décomposition texte test",
            is_reference=True,
            source=VariantSource.TEACHER_ORIGINAL,
            difficulty_level=VariantDifficulty.FACILE,
            status=VariantStatus.APPROVED,
        )
        db_session.add(variant)
        await db_session.flush()

        # Reasoning_Graph_Agent v2 (cf. mémoire de session) : enrichit des
        # ReasoningStep déjà persistés par Agent 4 — jamais un texte brut à
        # reparser. build_graph_for_variant exige donc qu'au moins un
        # ReasoningStep existe déjà pour la variante.
        step1 = ReasoningStep(
            variant_id=variant.id, order=1, step_type=ReasoningStepType.GIVEN_DATA,
            description="Donnée initiale",
        )
        step2 = ReasoningStep(
            variant_id=variant.id, order=2, step_type=ReasoningStepType.CONCLUSION,
            description="Résultat final",
        )
        db_session.add_all([step1, step2])
        await db_session.flush()

        service = ReasoningGraphService(db_session)
        report_mock = _fake_report([step1.id, step2.id])

        with patch.object(service._agent, "execute", return_value=report_mock):
            result = await service.build_graph_for_variant(variant.id)

        assert result.variant_id == variant.id
        assert result.step_count == 2
        assert result.is_valid_dag is True
        assert result.construction_confidence == 0.9

        # Mise à jour EN PLACE : mêmes lignes ReasoningStep, jamais une
        # nouvelle version qui supersède les précédentes.
        await db_session.refresh(step1)
        await db_session.refresh(step2)
        assert step1.version == 1
        assert step2.version == 1
        assert step1.superseded_by is None
        assert step2.superseded_by is None
        assert step2.extraction_signals is not None
        assert step2.extraction_signals.get("downstream_step_refs") == []

    async def test_build_graph_for_variant_not_found_raises(self, db_session: AsyncSession):
        service = ReasoningGraphService(db_session)
        with pytest.raises(VariantNotFoundError):
            await service.build_graph_for_variant(uuid.uuid4())

    async def test_build_graph_for_published_exercise_raises(self, db_session: AsyncSession):
        exercise = await _create_test_exercise(db_session, ExerciseStatus.PUBLISHED_AS_EXAM)

        question = Question(exercise_id=exercise.id, order=1, statement="Q1")
        db_session.add(question)
        await db_session.flush()

        variant = SolutionVariant(
            question_id=question.id,
            content="Texte",
            is_reference=True,
            source=VariantSource.TEACHER_ORIGINAL,
            difficulty_level=VariantDifficulty.FACILE,
        )
        db_session.add(variant)
        await db_session.flush()

        service = ReasoningGraphService(db_session)
        with pytest.raises(ExerciseAlreadyPublishedError):
            await service.build_graph_for_variant(variant.id)

    async def test_invalidate_cascade_for_question(self, db_session: AsyncSession):
        exercise = await _create_test_exercise(db_session, ExerciseStatus.DRAFT)

        question = Question(exercise_id=exercise.id, order=1, statement="Q1")
        db_session.add(question)
        await db_session.flush()

        var_ref = SolutionVariant(
            question_id=question.id,
            content="Ref",
            is_reference=True,
            source=VariantSource.TEACHER_ORIGINAL,
            difficulty_level=VariantDifficulty.FACILE,
            status=VariantStatus.APPROVED,
        )
        var_derived1 = SolutionVariant(
            question_id=question.id,
            content="Variante 1",
            is_reference=False,
            source=VariantSource.AI_GENERATED,
            difficulty_level=VariantDifficulty.INTERMEDIAIRE,
            status=VariantStatus.APPROVED,
        )
        var_derived2 = SolutionVariant(
            question_id=question.id,
            content="Variante 2",
            is_reference=False,
            source=VariantSource.AI_GENERATED,
            difficulty_level=VariantDifficulty.AVANCE,
            status=VariantStatus.APPROVED,
        )
        db_session.add_all([var_ref, var_derived1, var_derived2])
        await db_session.flush()

        service = ReasoningGraphService(db_session)
        cascade_report = await service.invalidate_cascade_for_question(question.id)

        assert cascade_report.question_id == question.id
        assert len(cascade_report.invalidated_variant_ids) == 2
        assert var_derived1.id in cascade_report.invalidated_variant_ids
        assert var_derived2.id in cascade_report.invalidated_variant_ids
        assert var_derived1.status == VariantStatus.PENDING_VALIDATION
        assert "Invalidé suite à la modification" in var_derived1.review_comment
        # La référence n'est pas modifiée par la cascade
        assert var_ref.status == VariantStatus.APPROVED

    async def test_build_graphs_for_variants_parallel(self, db_session: AsyncSession):
        exercise = await _create_test_exercise(db_session, ExerciseStatus.DRAFT)

        question = Question(exercise_id=exercise.id, order=1, statement="Q1")
        db_session.add(question)
        await db_session.flush()

        v1 = SolutionVariant(
            question_id=question.id,
            content="V1",
            is_reference=True,
            source=VariantSource.TEACHER_ORIGINAL,
            difficulty_level=VariantDifficulty.FACILE,
        )
        v2 = SolutionVariant(
            question_id=question.id,
            content="V2",
            is_reference=False,
            source=VariantSource.AI_GENERATED,
            difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        )
        db_session.add_all([v1, v2])
        await db_session.flush()

        service = ReasoningGraphService(db_session)

        async def fake_build(vid: uuid.UUID, trace_id: str | None = None):
            report = _fake_report([uuid.uuid4(), uuid.uuid4()])
            return MagicMock(
                variant_id=vid,
                construction_confidence=report.construction_confidence,
                is_valid_dag=True,
                step_count=2,
            )

        with patch.object(service, "build_graph_for_variant", side_effect=fake_build):
            results = await service.build_graphs_for_variants_parallel([v1.id, v2.id])

        assert len(results) == 2
        assert all(not isinstance(r, Exception) for r in results)

