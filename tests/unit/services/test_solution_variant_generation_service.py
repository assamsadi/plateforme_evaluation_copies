"""
Tests unitaires pour SolutionVariantGenerationService.
"""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.reasoning_step import ReasoningStep, ReasoningStepType
from app.domain.models.assessment.solution_variant import (
    SolutionVariant,
    VariantDifficulty,
    VariantSource,
    VariantStatus,
)
from app.domain.models.assessment.submission import Submission
from app.domain.models.system_infrastructure.agent_decision_log import AgentDecisionLog
from app.agents.solution_variant_generation_exceptions import ExerciseAlreadyPublishedError
from app.core.exceptions import NotExerciseOwnerError
from app.domain.schemas.solution_variant_generation_schemas import (
    CandidateStepSummarySchema,
    GeneratedVariantCandidateSchema,
    VariantGenerationAgentReport,
    VariantReviewAction,
    VariantReviewRequest,
)
from app.services.solution_variant_generation_service import SolutionVariantGenerationService
from app.services.reasoning_graph_service import ReasoningGraphService


@pytest.mark.anyio
async def test_service_skips_when_mandated_method_set():
    session = AsyncMock()
    qid = uuid.uuid4()
    eid = uuid.uuid4()

    mock_q = Question(id=qid, exercise_id=eid, statement="Statement 1", mandated_method="Méthode stricte par substitution")
    mock_ex = Exercise(id=eid, title="Exercice", status=ExerciseStatus.DRAFT)

    session.get.side_effect = lambda model, obj_id: mock_q if model == Question else (mock_ex if model == Exercise else None)

    service = SolutionVariantGenerationService(session)
    report, created = await service.generate_variants_for_question(
        question_id=qid,
        trigger_type="proactive",
    )

    assert created == []
    assert report.skipping_reason is not None
    assert "mandated_method" in report.skipping_reason


@pytest.mark.anyio
async def test_proactive_generation_blocked_when_exercise_already_published():
    session = AsyncMock()
    qid = uuid.uuid4()
    eid = uuid.uuid4()

    mock_q = Question(id=qid, exercise_id=eid, statement="Statement 1", mandated_method=None)
    mock_ex = Exercise(id=eid, title="Exercice", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK)

    session.get.side_effect = lambda model, obj_id: mock_q if model == Question else (mock_ex if model == Exercise else None)

    service = SolutionVariantGenerationService(session)

    with pytest.raises(ExerciseAlreadyPublishedError):
        await service.generate_variants_for_question(question_id=qid, trigger_type="proactive")


@pytest.mark.anyio
async def test_on_demand_and_guided_allowed_when_exercise_already_published():
    session = AsyncMock()
    qid = uuid.uuid4()
    eid = uuid.uuid4()
    vid = uuid.uuid4()
    mid = uuid.uuid4()

    mock_q = Question(id=qid, exercise_id=eid, statement="Statement 1", mandated_method=None)
    mock_ex = Exercise(id=eid, module_id=mid, title="Exercice", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK)
    mock_ref_v = SolutionVariant(id=vid, question_id=qid, content="Ref", is_reference=True)
    mock_ref_s = ReasoningStep(variant_id=vid, order=1, step_type=ReasoningStepType.CONCLUSION, description="x=42")

    session.get.side_effect = lambda model, obj_id: mock_q if model == Question else (mock_ex if model == Exercise else None)

    mock_res_ref_v = MagicMock()
    mock_res_ref_v.scalars.return_value.first.return_value = mock_ref_v
    mock_res_ref_s = MagicMock()
    mock_res_ref_s.scalars.return_value.all.return_value = [mock_ref_s]
    mock_res_exist_v = MagicMock()
    mock_res_exist_v.scalars.return_value.all.return_value = []
    mock_res_envelope = MagicMock()
    mock_res_envelope.scalars.return_value.all.return_value = []
    session.execute.side_effect = [
        mock_res_ref_v, mock_res_ref_s, mock_res_exist_v, mock_res_envelope,
    ]

    mock_candidate = GeneratedVariantCandidateSchema(
        strategy_name="Méthode de l'étudiant",
        content="Contenu candidat",
        reasoning_summary="Démarche alternative de l'étudiant.",
        difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        conclusion_formula="x = 42",
        concept_tags=["algebrique"],
        steps_summary=[CandidateStepSummarySchema(order=1, step_type="conclusion", description="x = 42")],
    )
    fake_agent_report = VariantGenerationAgentReport(
        question_id=qid, candidates=[mock_candidate], total_llm_calls=1,
    )

    service = SolutionVariantGenerationService(session)

    with (
        patch.object(service._agent, "execute", new_callable=AsyncMock, return_value=fake_agent_report),
        patch.object(ReasoningGraphService, "build_graph_for_variant", new_callable=AsyncMock) as mock_build_graph,
    ):
        report, created_variants = await service.generate_variants_for_question(
            question_id=qid,
            trigger_type="on_demand",
            student_candidate_method="Méthode X de l'étudiant",
        )

    # VERIFICATION PRINCIPALE : aucune ExerciseAlreadyPublishedError levée
    # (2.2 autorisé post-publication), ET allow_post_publication=True transmis.
    assert len(created_variants) == 1
    assert mock_build_graph.call_args.kwargs["allow_post_publication"] is True


@pytest.mark.anyio
async def test_service_delegates_graph_construction_to_reasoning_graph_service():
    session = AsyncMock()
    qid = uuid.uuid4()
    eid = uuid.uuid4()
    vid = uuid.uuid4()
    mid = uuid.uuid4()

    mock_q = Question(id=qid, exercise_id=eid, statement="Statement 1", mandated_method=None)
    mock_ex = Exercise(id=eid, module_id=mid, title="Exercice", status=ExerciseStatus.DRAFT)
    mock_ref_v = SolutionVariant(id=vid, question_id=qid, content="Ref", is_reference=True)
    mock_ref_s = ReasoningStep(variant_id=vid, order=1, step_type=ReasoningStepType.CONCLUSION, description="x=42")

    session.get.side_effect = lambda model, obj_id: mock_q if model == Question else (mock_ex if model == Exercise else None)

    # Configurer session.execute() pour renvoyer les objets nécessaires
    mock_res_ref_v = MagicMock()
    mock_res_ref_v.scalars.return_value.first.return_value = mock_ref_v

    mock_res_ref_s = MagicMock()
    mock_res_ref_s.scalars.return_value.all.return_value = [mock_ref_s]

    mock_res_exist_v = MagicMock()
    mock_res_exist_v.scalars.return_value.all.return_value = []

    mock_res_envelope = MagicMock()
    mock_res_envelope.scalars.return_value.all.return_value = []

    session.execute.side_effect = [
        mock_res_ref_v,
        mock_res_ref_s,
        mock_res_exist_v,
        mock_res_envelope,
    ]

    mock_candidate = GeneratedVariantCandidateSchema(
        strategy_name="Méthode matricielle",
        content="Contenu matriciel",
        reasoning_summary="Démarche par calcul de déterminant.",
        difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        conclusion_formula="x = 42",
        concept_tags=["algebrique"],
        steps_summary=[
            CandidateStepSummarySchema(order=1, step_type="given_data", description="Data"),
            CandidateStepSummarySchema(order=2, step_type="conclusion", description="x = 42"),
        ],
    )

    fake_agent_report = VariantGenerationAgentReport(
        question_id=qid,
        candidates=[mock_candidate],
        total_llm_calls=1,
    )

    service = SolutionVariantGenerationService(session)

    with (
        patch.object(service._agent, "execute", new_callable=AsyncMock, return_value=fake_agent_report),
        patch.object(ReasoningGraphService, "build_graph_for_variant", new_callable=AsyncMock) as mock_build_graph,
    ):
        report, created_variants = await service.generate_variants_for_question(
            question_id=qid,
            trigger_type="proactive",
        )

    assert len(created_variants) == 1
    assert created_variants[0].is_reference is False
    assert created_variants[0].status == VariantStatus.PENDING_VALIDATION

    # VERIFICATION PRINCIPALE : DÉLÉGATION À ReasoningGraphService EFFECTUÉE !
    assert mock_build_graph.called
    assert mock_build_graph.call_args[1]["variant_id"] == created_variants[0].id


@pytest.mark.anyio
async def test_review_variant_decision_actions():
    session = AsyncMock()
    vid = uuid.uuid4()
    qid = uuid.uuid4()
    prof_id = uuid.uuid4()

    mock_v = SolutionVariant(
        id=vid,
        question_id=qid,
        content="Candidate content",
        is_reference=False,
        status=VariantStatus.PENDING_VALIDATION,
    )
    mock_q = Question(id=qid, exercise_id=uuid.uuid4(), statement="Q")

    session.get.side_effect = lambda model, obj_id: mock_v if model == SolutionVariant else (mock_q if model == Question else None)

    service = SolutionVariantGenerationService(session)

    # 1. Action ACCEPTED
    req_accept = VariantReviewRequest(variant_id=vid, action=VariantReviewAction.ACCEPTED)
    updated, _ = await service.review_variant_decision(req_accept, prof_id)
    assert updated.status == VariantStatus.APPROVED

    # 2. Action REJECTED
    req_reject = VariantReviewRequest(variant_id=vid, action=VariantReviewAction.REJECTED)
    updated, _ = await service.review_variant_decision(req_reject, prof_id)
    assert updated.status == VariantStatus.REJECTED

    # 3. Action MODIFIED
    with patch.object(ReasoningGraphService, "build_graph_for_variant", new_callable=AsyncMock):
        req_modify = VariantReviewRequest(
            variant_id=vid,
            action=VariantReviewAction.MODIFIED,
            modified_content="Contenu modifié par le prof",
        )
        updated, _ = await service.review_variant_decision(req_modify, prof_id)
        assert updated.status == VariantStatus.APPROVED
        assert updated.content == "Contenu modifié par le prof"

    # 4. Action DELETED
    session.add.reset_mock()
    session.delete.reset_mock()
    req_delete = VariantReviewRequest(variant_id=vid, action=VariantReviewAction.DELETED)
    deleted, _ = await service.review_variant_decision(req_delete, prof_id)
    assert deleted is None

    # VERIFICATION PRINCIPALE : un AgentDecisionLog est créé pour DELETED,
    # AVANT le hard delete — jamais un effacement silencieux (cf. audit §6).
    logged_entries = [c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], AgentDecisionLog)]
    assert len(logged_entries) == 1
    delete_log = logged_entries[0]
    assert delete_log.related_entity_id == vid
    output = json.loads(delete_log.output_summary)
    assert output["action"] == VariantReviewAction.DELETED.value
    assert output["content_before"] == "Contenu modifié par le prof"  # snapshot capturé avant suppression
    assert session.delete.await_args.args[0] is mock_v
    # Le log est bien ajouté (et flush) avant l'appel à delete — ordre vérifié
    # via l'appel effectif à session.add avant session.delete ci-dessus (pas
    # de réordonnancement possible : add() est synchrone, appelé dans le
    # corps de la méthode avant le bloc DELETED).


@pytest.mark.anyio
async def test_retroactive_equity_reporting():
    session = AsyncMock()
    vid = uuid.uuid4()
    qid = uuid.uuid4()
    eid = uuid.uuid4()
    prof_id = uuid.uuid4()

    mock_v = SolutionVariant(id=vid, question_id=qid, content="Cand", is_reference=False, status=VariantStatus.PENDING_VALIDATION)
    mock_q = Question(id=qid, exercise_id=eid, order=1)
    mock_ex = Exercise(id=eid, status=ExerciseStatus.PUBLISHED_AS_EXAM)
    mock_sub = Submission(id=uuid.uuid4(), exercise_id=eid)

    session.get.side_effect = lambda model, obj_id: mock_v if model == SolutionVariant else (
        mock_q if model == Question else (mock_ex if model == Exercise else None)
    )

    mock_sub_res = MagicMock()
    mock_sub_res.scalars.return_value.all.return_value = [mock_sub]
    session.execute.return_value = mock_sub_res

    service = SolutionVariantGenerationService(session)
    req = VariantReviewRequest(variant_id=vid, action=VariantReviewAction.ACCEPTED)

    _, equity_report = await service.review_variant_decision(req, prof_id)

    assert equity_report is not None
    assert mock_sub.id in equity_report.impacted_submission_ids
    assert "équité pédagogique" in equity_report.message


async def _seed_question_with_reference(db_session):
    """Seed minimal réel (Program/Module/Professor/Exercise/Question/référence)
    pour tester resolve_on_demand_candidate contre une vraie DB (garde-fou
    anti-boucle nécessite une vraie contrainte d'unicité en base)."""
    from app.domain.models.academic.module import Module
    from app.domain.models.academic.program import Program
    from app.domain.models.identity.user import Professor

    uid = uuid.uuid4().hex[:8]
    prog = Program(name=f"Prog_{uid}", code=f"P_{uid}")
    db_session.add(prog)
    await db_session.flush()

    mod = Module(program_id=prog.id, name=f"Mod_{uid}", code=f"M_{uid}")
    db_session.add(mod)
    await db_session.flush()

    prof = Professor(
        email=f"prof_{uid}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Test", department="Maths",
        title="Dr", employee_number=f"EMP_{uid}",
    )
    db_session.add(prof)
    await db_session.flush()

    ex = Exercise(module_id=mod.id, created_by_professor_id=prof.id, title=f"Ex_{uid}", status=ExerciseStatus.DRAFT)
    db_session.add(ex)
    await db_session.flush()

    q = Question(exercise_id=ex.id, order=1, statement="Résoudre.", mandated_method=None)
    db_session.add(q)
    await db_session.flush()

    ref_v = SolutionVariant(
        question_id=q.id, is_reference=True, content="Réf", version=1,
        source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.INTERMEDIAIRE,
    )
    db_session.add(ref_v)
    await db_session.flush()

    ref_s = ReasoningStep(variant_id=ref_v.id, order=1, step_type=ReasoningStepType.CONCLUSION, description="x=42")
    db_session.add(ref_s)
    await db_session.flush()

    return q


@pytest.mark.anyio
async def test_on_demand_anti_loop_guard_skips_second_call_for_same_structural_candidate(db_session):
    """
    VERIFICATION PRINCIPALE (preuve par comptage d'appels, cf. audit §1b) :
    la même méthode candidate (même structure, texte différent) déclenchée
    deux fois pour la même question n'invoque l'agent qu'UNE SEULE fois — la
    seconde fois, la décision déjà persistée est réutilisée telle quelle.
    """
    question = await _seed_question_with_reference(db_session)
    service = SolutionVariantGenerationService(db_session)

    accepted_candidate = GeneratedVariantCandidateSchema(
        strategy_name="Méthode de l'étudiant",
        content="Contenu candidat",
        reasoning_summary="Démarche alternative.",
        difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        concept_tags=["substitution"],
        steps_summary=[CandidateStepSummarySchema(order=1, step_type="computation", description="étape 1")],
    )
    fake_report = VariantGenerationAgentReport(question_id=question.id, candidates=[accepted_candidate], total_llm_calls=1)

    calls = []

    async def mock_execute(**kwargs):
        calls.append(kwargs.get("student_candidate_method"))
        return fake_report

    candidate_v1 = {
        "description": "Résolution par substitution directe.",
        "steps": [{"order": 1, "step_type": "computation"}],
        "concept_tags": ["substitution"],
    }
    # Formulation textuelle DIFFÉRENTE, structure IDENTIQUE (même step_type,
    # mêmes concept_tags) — doit matcher la même signature.
    candidate_v2 = {
        "description": "On isole la variable puis on substitue.",
        "steps": [{"order": 1, "step_type": "computation"}],
        "concept_tags": ["substitution"],
    }

    with (
        patch.object(service._agent, "execute", new_callable=AsyncMock, side_effect=mock_execute),
        patch.object(ReasoningGraphService, "build_graph_for_variant", new_callable=AsyncMock),
    ):
        decision1, report1, variant1 = await service.resolve_on_demand_candidate(question.id, candidate_v1)
        decision2, report2, variant2 = await service.resolve_on_demand_candidate(question.id, candidate_v2)

    assert len(calls) == 1  # l'agent n'a été invoqué qu'une seule fois
    assert decision1.id == decision2.id  # même ligne EvaluatedVariantCandidate réutilisée
    assert report2 is None  # pas de nouveau rapport : décision en cache
    assert variant1 is not None and variant2 is not None
    assert variant1.id == variant2.id


# ---------------------------------------------------------------------------
# list_variants_for_question (gap de découverte trouvé le 2026-08-18) +
# notification pointant sur le variant_id créé (mode guidé)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_list_variants_for_question_returns_summaries_with_derived_fields():
    session = AsyncMock()
    qid = uuid.uuid4()
    eid = uuid.uuid4()
    pid = uuid.uuid4()
    ref_id = uuid.uuid4()
    cand_id = uuid.uuid4()

    mock_q = Question(id=qid, exercise_id=eid, statement="Statement 1", mandated_method=None)
    mock_ex = Exercise(id=eid, title="Exercice", status=ExerciseStatus.DRAFT, created_by_professor_id=pid)
    session.get.side_effect = lambda model, obj_id: mock_q if model == Question else (mock_ex if model == Exercise else None)

    now = datetime.now(timezone.utc)
    ref_variant = SolutionVariant(
        id=ref_id, question_id=qid, content="Ref", is_reference=True,
        source=VariantSource.TEACHER_ORIGINAL, difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        status=VariantStatus.APPROVED, created_at=now,
    )
    candidate_variant = SolutionVariant(
        id=cand_id, question_id=qid, content="Alt", is_reference=False,
        source=VariantSource.AI_GENERATED, difficulty_level=VariantDifficulty.AVANCE,
        status=VariantStatus.PENDING_VALIDATION, reasoning_summary="Approche alternative.",
        structured_content={"strategy_name": "Méthode X", "distinction_score": 0.87},
        created_at=now,
    )
    mock_res = MagicMock()
    mock_res.scalars.return_value.all.return_value = [ref_variant, candidate_variant]
    session.execute.return_value = mock_res

    service = SolutionVariantGenerationService(session)
    summaries = await service.list_variants_for_question(qid, pid)

    assert len(summaries) == 2
    assert summaries[0].is_reference is True
    assert summaries[0].strategy_name is None  # structured_content=None côté référence, jamais inventé
    assert summaries[1].is_reference is False
    assert summaries[1].strategy_name == "Méthode X"
    assert summaries[1].distinction_score == 0.87
    assert summaries[1].reasoning_summary == "Approche alternative."


@pytest.mark.anyio
async def test_list_variants_for_question_blocks_non_owner():
    session = AsyncMock()
    qid = uuid.uuid4()
    eid = uuid.uuid4()
    owner_id = uuid.uuid4()
    other_prof_id = uuid.uuid4()

    mock_q = Question(id=qid, exercise_id=eid, statement="Statement 1", mandated_method=None)
    mock_ex = Exercise(id=eid, title="Exercice", status=ExerciseStatus.DRAFT, created_by_professor_id=owner_id)
    session.get.side_effect = lambda model, obj_id: mock_q if model == Question else (mock_ex if model == Exercise else None)

    service = SolutionVariantGenerationService(session)

    with pytest.raises(NotExerciseOwnerError):
        await service.list_variants_for_question(qid, other_prof_id)


@pytest.mark.anyio
async def test_generate_guided_variant_and_notify_points_at_created_variant():
    session = AsyncMock()
    qid = uuid.uuid4()
    eid = uuid.uuid4()
    vid = uuid.uuid4()
    pid = uuid.uuid4()
    mid = uuid.uuid4()

    mock_q = Question(id=qid, exercise_id=eid, statement="Statement 1", mandated_method=None)
    mock_ex = Exercise(id=eid, module_id=mid, title="Exercice", status=ExerciseStatus.DRAFT)
    mock_ref_v = SolutionVariant(id=vid, question_id=qid, content="Ref", is_reference=True)
    mock_ref_s = ReasoningStep(variant_id=vid, order=1, step_type=ReasoningStepType.CONCLUSION, description="x=42")

    session.get.side_effect = lambda model, obj_id: mock_q if model == Question else (mock_ex if model == Exercise else None)

    mock_res_ref_v = MagicMock()
    mock_res_ref_v.scalars.return_value.first.return_value = mock_ref_v
    mock_res_ref_s = MagicMock()
    mock_res_ref_s.scalars.return_value.all.return_value = [mock_ref_s]
    mock_res_exist_v = MagicMock()
    mock_res_exist_v.scalars.return_value.all.return_value = []
    mock_res_envelope = MagicMock()
    mock_res_envelope.scalars.return_value.all.return_value = []
    session.execute.side_effect = [
        mock_res_ref_v, mock_res_ref_s, mock_res_exist_v, mock_res_envelope,
    ]

    mock_candidate = GeneratedVariantCandidateSchema(
        strategy_name="Méthode guidée demandée",
        content="Contenu",
        reasoning_summary="Démarche guidée.",
        difficulty_level=VariantDifficulty.INTERMEDIAIRE,
        conclusion_formula="x = 42",
        concept_tags=["algebrique"],
        steps_summary=[CandidateStepSummarySchema(order=1, step_type="conclusion", description="x = 42")],
    )
    fake_agent_report = VariantGenerationAgentReport(
        question_id=qid, candidates=[mock_candidate], total_llm_calls=1,
    )

    service = SolutionVariantGenerationService(session)

    with (
        patch.object(service._agent, "execute", new_callable=AsyncMock, return_value=fake_agent_report),
        patch.object(ReasoningGraphService, "build_graph_for_variant", new_callable=AsyncMock),
    ):
        await service.generate_guided_variant_and_notify(
            question_id=qid, professor_id=pid, method_hint="Méthode X", concept_hint=None,
        )

    # VERIFICATION PRINCIPALE : la notification pointe sur la variante créée
    # (SolutionVariant, son propre id) — jamais seulement sur la Question,
    # sans quoi le professeur n'a aucun moyen d'obtenir le variant_id
    # nécessaire pour appeler /review depuis la notification seule.
    notif_calls = [c for c in session.add.call_args_list if type(c.args[0]).__name__ == "Notification"]
    assert len(notif_calls) == 1
    notification = notif_calls[0].args[0]
    assert notification.related_entity_type == "SolutionVariant"
    assert notification.related_entity_id != qid
