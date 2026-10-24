import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import SubmissionNotFoundError, SubmissionPendingArbitrationError
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_profile import CompetencyTrend
from app.services.competency_assessment_service import CompetencyAssessmentService

AS = C2PCTSkillCode.ALGORITHMIC_STRUCTURING


@dataclass
class _FakeSettings:
    """Stub minimal — jamais une dépendance vers get_settings()/l'environnement réel dans un test unitaire."""
    COMPETENCY_DECAY_FACTOR: Decimal = Decimal("0.9")
    COMPETENCY_TREND_THRESHOLD_PERCENT: Decimal = Decimal("5.0")
    COMPETENCY_PERSISTENT_WEAKNESS_THRESHOLD: Decimal = Decimal("0.5")
    COMPETENCY_PERSISTENT_WEAKNESS_WINDOW: int = 3
    COMPETENCY_STRENGTH_RATIO_THRESHOLD: Decimal = Decimal("0.8")
    COMPETENCY_WEAKNESS_RATIO_THRESHOLD: Decimal = Decimal("0.3")


def _make_service(evaluation_repo=None, exercise_repo=None, submission_repo=None,
                   observation_repo=None, profile_repo=None):
    return CompetencyAssessmentService(
        evaluation_repo=evaluation_repo or AsyncMock(),
        exercise_repo=exercise_repo or AsyncMock(),
        submission_repo=submission_repo or AsyncMock(),
        observation_repo=observation_repo or AsyncMock(),
        profile_repo=profile_repo or AsyncMock(),
        settings=_FakeSettings(),
    )


@pytest.mark.anyio
async def test_assess_submission_raises_when_submission_not_found():
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = None
    service = _make_service(submission_repo=submission_repo)

    with pytest.raises(SubmissionNotFoundError):
        await service.assess_submission(uuid.uuid4())


@pytest.mark.anyio
async def test_assess_submission_blocked_when_submission_pending_arbitration():
    """Précondition PENDING_ARBITRATION — jamais une soumission encore incertaine ne contribue à un profil."""
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = MagicMock(status=SubmissionStatus.PENDING_ARBITRATION)
    evaluation_repo = AsyncMock()

    service = _make_service(submission_repo=submission_repo, evaluation_repo=evaluation_repo)

    with pytest.raises(SubmissionPendingArbitrationError):
        await service.assess_submission(uuid.uuid4())

    evaluation_repo.list_by_submission.assert_not_awaited()
    evaluation_repo.list_criteria_for_submission.assert_not_awaited()


@pytest.mark.anyio
async def test_assess_submission_persists_observation_and_updates_profile_cache():
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    eid = uuid.uuid4()
    student_id = uuid.uuid4()
    module_id = uuid.uuid4()

    submission = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=student_id,
                            status=SubmissionStatus.PENDING_EVALUATION)
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = submission

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(module_id=module_id)

    evaluation = MagicMock(id=eid, question_id=qid, copy_report_detail=None)
    evaluation_repo = AsyncMock()
    evaluation_repo.list_by_submission.return_value = [evaluation]

    subquestion_outcomes = [
        {"subquestion_id": "3.1", "addressed": True, "is_correct": True},
        {"subquestion_id": "3.2", "addressed": True, "is_correct": True},
    ]
    criterion = MagicMock(
        evaluation_id=eid, competency_code=AS,
        subquestion_detail={
            "covered_count": 2, "successful_count": 2,
            "subquestions": subquestion_outcomes, "success_rate": 1.0,
        },
    )
    evaluation_repo.list_criteria_for_submission.return_value = [criterion]

    observation_repo = AsyncMock()
    observation_repo.list_recent.return_value = [
        SimpleNamespace(
            performance_copie=Decimal("1.00000"),
            subquestions_covered_count=2,
            subquestions_succeeded_count=2,
            question_ids=[str(qid)],
            subquestion_outcomes=subquestion_outcomes,
            decision_reasons=[],
            created_at=datetime.now(timezone.utc),
        )
    ]
    profile_repo = AsyncMock()

    service = _make_service(
        evaluation_repo=evaluation_repo, exercise_repo=exercise_repo,
        submission_repo=submission_repo, observation_repo=observation_repo,
        profile_repo=profile_repo,
    )

    lines = await service.assess_submission(sid)

    observation_repo.create.assert_awaited_once_with(
        student_id=student_id, module_id=module_id, competency_code=AS, submission_id=sid,
        performance_copie=Decimal("1.00000"), subquestions_covered_count=2,
        subquestions_succeeded_count=2, question_ids=[str(qid)],
        subquestion_outcomes=subquestion_outcomes, decision_reasons=[],
    )

    assert len(lines) == 1
    line = lines[0]
    assert line.mastery_level == Decimal("100.00")
    assert line.trend == "INSUFFICIENT_DATA"  # une seule observation dans l'historique -> jamais devinée
    assert line.evaluations_count == 1
    assert line.confidence_level == Decimal("0.20")

    profile_repo.upsert.assert_awaited_once_with(
        student_id=student_id, competency_code=AS, module_id=module_id,
        mastery_level=Decimal("100.00"), trend=CompetencyTrend.INSUFFICIENT_DATA,
        evaluations_count=1, confidence_level=Decimal("0.20"), is_persistent_weakness=False,
    )


@pytest.mark.anyio
async def test_assess_submission_extracts_decision_reasons_from_copy_report_detail():
    """decision_reasons (champ enrichi) viennent de Evaluation.copy_report_detail, jamais recalculés."""
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    eid = uuid.uuid4()
    student_id = uuid.uuid4()
    module_id = uuid.uuid4()

    submission = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=student_id,
                            status=SubmissionStatus.PENDING_EVALUATION)
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = submission

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(module_id=module_id)

    copy_report_detail = {
        "question_id": str(qid), "note": "0.00", "bareme_points": "4.00",
        "consigne_respected": None,
        "competency_lines": [
            {
                "competency": AS.value,
                "subquestions_covered_by_professor": 1, "subquestions_succeeded_by_student": 0,
                "bareme_share": "4.00", "points_awarded": "0.00",
                "decisions": [
                    {
                        "subquestion_id": "3.1", "competency": AS.value, "decision": "INCORRECT",
                        "reason": "Étapes décrites dans le désordre.", "evidence_reference": None,
                    },
                ],
            },
        ],
    }
    evaluation = MagicMock(id=eid, question_id=qid, copy_report_detail=copy_report_detail)
    evaluation_repo = AsyncMock()
    evaluation_repo.list_by_submission.return_value = [evaluation]

    criterion = MagicMock(
        evaluation_id=eid, competency_code=AS,
        subquestion_detail={
            "covered_count": 1, "successful_count": 0,
            "subquestions": [{"subquestion_id": "3.1", "addressed": True, "is_correct": False}],
            "success_rate": 0.0,
        },
    )
    evaluation_repo.list_criteria_for_submission.return_value = [criterion]

    observation_repo = AsyncMock()
    observation_repo.list_recent.return_value = []
    service = _make_service(
        evaluation_repo=evaluation_repo, exercise_repo=exercise_repo,
        submission_repo=submission_repo, observation_repo=observation_repo,
    )

    await service.assess_submission(sid)

    call_kwargs = observation_repo.create.await_args.kwargs
    assert call_kwargs["decision_reasons"] == [
        {"subquestion_id": "3.1", "decision": "INCORRECT", "reason": "Étapes décrites dans le désordre."},
    ]


@pytest.mark.anyio
async def test_get_report_groups_observations_by_competency():
    student_id, module_id = uuid.uuid4(), uuid.uuid4()

    observation_repo = AsyncMock()
    observation_repo.list_all_by_student_and_module.return_value = [
        SimpleNamespace(
            competency_code=AS, performance_copie=Decimal("0.80000"),
            subquestions_covered_count=2, subquestions_succeeded_count=2,
            question_ids=[str(uuid.uuid4())], subquestion_outcomes=[], decision_reasons=[],
            created_at=datetime.now(timezone.utc),
        ),
    ]
    service = _make_service(observation_repo=observation_repo)

    result = await service.get_report(student_id, module_id)

    assert result.student_id == student_id
    assert result.module_id == module_id
    assert len(result.lines) == 1
    assert result.lines[0].competency == AS


# ---------------------------------------------------------------------------
# get_report_as_professor — câblage Partie 2/2 (endpoint API)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_report_as_professor_succeeds_when_professor_has_exercise_in_module():
    professor_id, student_id, module_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    exercise_repo = AsyncMock()
    exercise_repo.exists_professor_exercise_in_module.return_value = True
    observation_repo = AsyncMock()
    observation_repo.list_all_by_student_and_module.return_value = []
    service = _make_service(exercise_repo=exercise_repo, observation_repo=observation_repo)

    result = await service.get_report_as_professor(professor_id, student_id, module_id)

    exercise_repo.exists_professor_exercise_in_module.assert_awaited_once_with(
        professor_id=professor_id, module_id=module_id,
    )
    assert result.student_id == student_id
    assert result.module_id == module_id
    assert result.lines == []


@pytest.mark.anyio
async def test_get_report_as_professor_forbidden_when_professor_has_no_exercise_in_module():
    from app.core.exceptions import ForbiddenError

    exercise_repo = AsyncMock()
    exercise_repo.exists_professor_exercise_in_module.return_value = False
    observation_repo = AsyncMock()
    service = _make_service(exercise_repo=exercise_repo, observation_repo=observation_repo)

    with pytest.raises(ForbiddenError):
        await service.get_report_as_professor(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())

    observation_repo.list_all_by_student_and_module.assert_not_awaited()
