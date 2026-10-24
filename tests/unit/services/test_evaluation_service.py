from decimal import Decimal
import uuid
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.agents.Comparative_Evaluation_Agent import DecisionEntry
from app.agents.Pedagogical_Evaluation_Agent import (
    CompetencyReportLine,
    CompetencyScoreDetail,
    QuestionReport,
    QuestionScoreResult,
    SubquestionScoreDetail,
)
from app.core.exceptions import (
    ExerciseNotFoundError,
    ForbiddenError,
    NotExerciseOwnerError,
    SubmissionNotFoundError,
    SubmissionPendingArbitrationError,
)
from app.domain.models.assessment.evaluation import Evaluation
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.identity.user import UserRole
from app.domain.repositories.pagination import CursorPage
from app.services.evaluation_service import EvaluationService


@pytest.mark.anyio
async def test_record_evaluation_submission_not_found():
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = None

    service = EvaluationService(AsyncMock(), sub_repo, AsyncMock(), AsyncMock())
    with pytest.raises(SubmissionNotFoundError):
        await service.record_evaluation(
            submission_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            score=Decimal("10"),
            classic_criteria_observed=[],
            criteria_data=[],
        )


@pytest.mark.anyio
async def test_record_evaluation_success():
    """
    Retrait du mécanisme Niveau 1 : record_evaluation() est un persisteur
    générique, il ne connaît plus aucune compétence C2PCT — plus aucune
    dépendance vers un profile_repo (retiré du constructeur, cf. docstring
    module point 8).
    """
    sid = uuid.uuid4()
    qid = uuid.uuid4()

    mock_submission = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4())
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = mock_submission

    mock_eval = Evaluation(
        id=uuid.uuid4(),
        submission_id=sid,
        question_id=qid,
        score=Decimal("8.5"),
        classic_criteria_observed=[],
    )
    eval_repo = AsyncMock()
    eval_repo.create_with_criteria.return_value = mock_eval

    mock_exercise = MagicMock(id=mock_submission.exercise_id, module_id=uuid.uuid4(), questions=[])
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = mock_exercise

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())

    result = await service.record_evaluation(
        submission_id=sid,
        question_id=qid,
        score=Decimal("8.5"),
        classic_criteria_observed=[{"criterion": "exactitude", "score": 85, "justification": "Ok"}],
        criteria_data=[],
    )

    assert result.score == Decimal("8.5")
    eval_repo.create_with_criteria.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 4/4 — Précondition PENDING_ARBITRATION (TODO résolu)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_record_evaluation_blocked_when_submission_pending_arbitration():
    """
    Une soumission avec au moins une contestation encore en attente de
    décision professeur ne peut jamais être évaluée (§2 étape 6) — vérifié
    AVANT toute écriture (create_with_criteria jamais appelé).
    """
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(status=SubmissionStatus.PENDING_ARBITRATION)
    eval_repo = AsyncMock()

    service = EvaluationService(eval_repo, sub_repo, AsyncMock(), AsyncMock())

    with pytest.raises(SubmissionPendingArbitrationError):
        await service.record_evaluation(
            submission_id=uuid.uuid4(),
            question_id=uuid.uuid4(),
            score=Decimal("10"),
            classic_criteria_observed=[],
            criteria_data=[],
        )

    eval_repo.create_with_criteria.assert_not_awaited()


# ---------------------------------------------------------------------------
# Phase 4/4 — record_question_score (intégration Pedagogical_Evaluation_Agent)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_record_question_score_persists_one_criteria_row_per_competency():
    """
    Une ligne EvaluationCriteria PAR COMPÉTENCE (jamais par sous-question),
    competency_code + subquestion_detail JSONB, classic_criteria_observed
    vide (cet agent ne le produit pas).
    """
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    bareme_id = uuid.uuid4()

    mock_submission = MagicMock(
        id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4(),
        status=SubmissionStatus.PENDING_EVALUATION,
    )
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = mock_submission

    mock_eval = Evaluation(
        id=uuid.uuid4(), submission_id=sid, question_id=qid,
        score=Decimal("8.57"), classic_criteria_observed=[],
    )
    eval_repo = AsyncMock()
    eval_repo.create_with_criteria.return_value = mock_eval

    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(id=mock_submission.exercise_id, module_id=uuid.uuid4(), questions=[])

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())

    result_score = QuestionScoreResult(
        question_id=qid,
        total_score=Decimal("8.57"),
        competency_scores=[
            CompetencyScoreDetail(
                competency_code=C2PCTSkillCode.DATA_AND_PLANNING,
                covered_subquestion_ids=["1.1", "1.2"],
                covered_count=2,
                successful_count=2,
                success_rate=Decimal("1"),
                bareme_share=Decimal("8.57"),
                points_awarded=Decimal("8.57"),
                subquestion_detail=[
                    SubquestionScoreDetail("1.1", True, True, "new_llm_judgment"),
                    SubquestionScoreDetail("1.2", True, True, "new_llm_judgment"),
                ],
            ),
        ],
    )

    result = await service.record_question_score(sid, bareme_id, result_score)

    assert result.score == Decimal("8.57")
    eval_repo.create_with_criteria.assert_awaited_once()
    call_kwargs = eval_repo.create_with_criteria.await_args.kwargs
    assert call_kwargs["classic_criteria_observed"] == []
    assert len(call_kwargs["criteria_data"]) == 1
    row = call_kwargs["criteria_data"][0]
    assert row["bareme_id"] == bareme_id
    assert row["competency_code"] == C2PCTSkillCode.DATA_AND_PLANNING
    assert row["points_awarded"] == Decimal("8.57")
    assert "criterion_id" not in row  # ligne compétence : jamais criterion_id
    assert row["subquestion_detail"]["covered_count"] == 2
    assert row["subquestion_detail"]["successful_count"] == 2
    assert row["subquestion_detail"]["subquestions"][0]["subquestion_id"] == "1.1"


# ---------------------------------------------------------------------------
# Câblage copy_report — record_question_score(question_report=...) + get_copy_report
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_record_question_score_forwards_copy_report_detail_when_provided():
    """
    question_report fourni -> create_with_criteria reçoit copy_report_detail
    = QuestionReport.to_dict() (persistance telle quelle, aucun recalcul ici).
    """
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    bareme_id = uuid.uuid4()

    mock_submission = MagicMock(
        id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4(),
        status=SubmissionStatus.PENDING_EVALUATION,
    )
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = mock_submission

    mock_eval = Evaluation(
        id=uuid.uuid4(), submission_id=sid, question_id=qid,
        score=Decimal("6.00"), classic_criteria_observed=[],
    )
    eval_repo = AsyncMock()
    eval_repo.create_with_criteria.return_value = mock_eval

    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(id=mock_submission.exercise_id, module_id=uuid.uuid4(), questions=[])

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())

    result_score = QuestionScoreResult(
        question_id=qid, total_score=Decimal("6.00"),
        competency_scores=[
            CompetencyScoreDetail(
                competency_code=C2PCTSkillCode.DATA_AND_PLANNING,
                covered_count=1, successful_count=1, success_rate=Decimal("1"),
                bareme_share=Decimal("6.00"), points_awarded=Decimal("6.00"),
            ),
        ],
    )
    decision_entry = DecisionEntry(
        subquestion_id="1.1", competency=C2PCTSkillCode.DATA_AND_PLANNING,
        decision="REUSED_FROM_STEP_JUDGMENT", reason="...", evidence_reference=None,
    )
    question_report = QuestionReport(
        question_id=qid, note=Decimal("6.00"), bareme_points=Decimal("6.00"),
        competency_lines=[
            CompetencyReportLine(
                competency=C2PCTSkillCode.DATA_AND_PLANNING,
                subquestions_covered_by_professor=1, subquestions_succeeded_by_student=1,
                bareme_share=Decimal("6.00"), points_awarded=Decimal("6.00"),
                decisions=[decision_entry],
            ),
        ],
        consigne_respected=True,
    )

    await service.record_question_score(sid, bareme_id, result_score, question_report=question_report)

    call_kwargs = eval_repo.create_with_criteria.await_args.kwargs
    assert call_kwargs["copy_report_detail"] == question_report.to_dict()
    assert call_kwargs["copy_report_detail"]["consigne_respected"] is True
    assert call_kwargs["copy_report_detail"]["competency_lines"][0]["decisions"][0]["decision"] == "REUSED_FROM_STEP_JUDGMENT"


@pytest.mark.anyio
async def test_record_question_score_copy_report_detail_none_when_not_provided():
    """Rétrocompatibilité — question_report omis -> copy_report_detail=None, jamais deviné."""
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    bareme_id = uuid.uuid4()

    mock_submission = MagicMock(
        id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4(),
        status=SubmissionStatus.PENDING_EVALUATION,
    )
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = mock_submission

    mock_eval = Evaluation(
        id=uuid.uuid4(), submission_id=sid, question_id=qid,
        score=Decimal("6.00"), classic_criteria_observed=[],
    )
    eval_repo = AsyncMock()
    eval_repo.create_with_criteria.return_value = mock_eval

    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(id=mock_submission.exercise_id, module_id=uuid.uuid4(), questions=[])

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())

    result_score = QuestionScoreResult(question_id=qid, total_score=Decimal("6.00"), competency_scores=[])

    await service.record_question_score(sid, bareme_id, result_score)

    call_kwargs = eval_repo.create_with_criteria.await_args.kwargs
    assert call_kwargs["copy_report_detail"] is None


def _make_evaluation_with_report(question_report: QuestionReport | None) -> Evaluation:
    ev = Evaluation(
        id=uuid.uuid4(), submission_id=uuid.uuid4(), question_id=uuid.uuid4(),
        score=Decimal("0"), classic_criteria_observed=[],
    )
    ev.copy_report_detail = question_report.to_dict() if question_report is not None else None
    return ev


@pytest.mark.anyio
async def test_get_copy_report_assembles_multi_question_mixed_competencies():
    """
    CopyReport assemblé correctement sur plusieurs questions/compétences
    mixtes : une question sans ambiguïté (aucune décision), une question
    avec une décision INCORRECT (nécessite un regard), une question avec
    consigne_respected=False.
    """
    sid = uuid.uuid4()

    q1_clean = QuestionReport(
        question_id=uuid.uuid4(), note=Decimal("6.00"), bareme_points=Decimal("6.00"),
        competency_lines=[
            CompetencyReportLine(
                competency=C2PCTSkillCode.DATA_AND_PLANNING,
                subquestions_covered_by_professor=1, subquestions_succeeded_by_student=1,
                bareme_share=Decimal("6.00"), points_awarded=Decimal("6.00"),
                decisions=[],  # aucune décision -> sans ambiguïté
            ),
        ],
        consigne_respected=None,
    )
    q2_incorrect = QuestionReport(
        question_id=uuid.uuid4(), note=Decimal("0.00"), bareme_points=Decimal("4.00"),
        competency_lines=[
            CompetencyReportLine(
                competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING,
                subquestions_covered_by_professor=1, subquestions_succeeded_by_student=0,
                bareme_share=Decimal("4.00"), points_awarded=Decimal("0.00"),
                decisions=[
                    DecisionEntry(
                        subquestion_id="3.1", competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING,
                        decision="INCORRECT", reason="...", evidence_reference=None,
                    ),
                ],
            ),
        ],
        consigne_respected=False,
    )
    q3_reused_only = QuestionReport(
        question_id=uuid.uuid4(), note=Decimal("5.00"), bareme_points=Decimal("5.00"),
        competency_lines=[
            CompetencyReportLine(
                competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING,
                subquestions_covered_by_professor=1, subquestions_succeeded_by_student=1,
                bareme_share=Decimal("5.00"), points_awarded=Decimal("5.00"),
                decisions=[
                    DecisionEntry(
                        subquestion_id="3.2", competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING,
                        decision="REUSED_FROM_STEP_JUDGMENT", reason="...", evidence_reference=None,
                    ),
                ],
            ),
        ],
        consigne_respected=True,
    )

    eval_repo = AsyncMock()
    eval_repo.list_by_submission.return_value = [
        _make_evaluation_with_report(q1_clean),
        _make_evaluation_with_report(q2_incorrect),
        _make_evaluation_with_report(q3_reused_only),
        _make_evaluation_with_report(None),  # ligne antérieure au câblage -> ignorée
    ]

    service = EvaluationService(eval_repo, AsyncMock(), AsyncMock(), AsyncMock())

    report = await service.get_copy_report(sid)

    assert report.submission_id == sid
    assert len(report.questions) == 3  # la ligne None est bien exclue

    # REUSED_FROM_STEP_JUDGMENT seul ne compte jamais comme "nécessitant un
    # regard" -> q1 (rien) et q3 (reused seul) sont "sans ambiguïté".
    assert report.overview["questions_sans_ambiguite"] == 2
    assert report.overview["questions_necessitant_un_regard"] == 1
    assert report.overview["consigne_non_respectee_count"] == 1


@pytest.mark.anyio
async def test_get_copy_report_empty_submission_yields_zeroed_overview():
    eval_repo = AsyncMock()
    eval_repo.list_by_submission.return_value = []
    service = EvaluationService(eval_repo, AsyncMock(), AsyncMock(), AsyncMock())

    report = await service.get_copy_report(uuid.uuid4())

    assert report.questions == []
    assert report.overview == {
        "questions_sans_ambiguite": 0,
        "questions_necessitant_un_regard": 0,
        "consigne_non_respectee_count": 0,
    }


# ---------------------------------------------------------------------------
# list_by_exercise_for_professor (gap : liste des copies d'un exercice)
# ---------------------------------------------------------------------------

def _make_student(student_id, first_name="Jean", last_name="Martin"):
    return MagicMock(id=student_id, first_name=first_name, last_name=last_name)


@pytest.mark.anyio
async def test_list_by_exercise_for_professor_success():
    exercise_id = uuid.uuid4()
    professor_id = uuid.uuid4()
    evaluated_sid = uuid.uuid4()
    pending_sid = uuid.uuid4()
    evaluated_student_id = uuid.uuid4()
    pending_student_id = uuid.uuid4()

    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(id=exercise_id, created_by_professor_id=professor_id)

    evaluated_submission = MagicMock(
        id=evaluated_sid, student_id=evaluated_student_id, attempt_number=1,
        status=SubmissionStatus.EVALUATED, created_at="2026-08-21T00:00:00Z",
    )
    pending_submission = MagicMock(
        id=pending_sid, student_id=pending_student_id, attempt_number=1,
        status=SubmissionStatus.PENDING_EVALUATION, created_at="2026-08-21T00:00:00Z",
    )
    sub_repo = AsyncMock()
    sub_repo.list_by_exercise.return_value = CursorPage(
        items=[evaluated_submission, pending_submission], next_cursor=None, has_more=False
    )

    user_repo = AsyncMock()
    user_repo.get_by_id.side_effect = lambda sid: (
        _make_student(evaluated_student_id) if sid == evaluated_student_id else _make_student(pending_student_id, "Alice", "Dupont")
    )

    eval_repo = AsyncMock()
    eval_repo.get_total_score_for_submission.return_value = Decimal("14.5")

    service = EvaluationService(eval_repo, sub_repo, ex_repo, user_repo)

    result = await service.list_by_exercise_for_professor(exercise_id, professor_id)

    assert len(result.items) == 2
    assert result.items[0].total_score == Decimal("14.5")
    assert result.items[0].student_full_name == "Jean Martin"
    assert result.items[1].total_score is None
    assert result.items[1].student_full_name == "Alice Dupont"
    eval_repo.get_total_score_for_submission.assert_awaited_once_with(evaluated_sid)
    sub_repo.list_by_exercise.assert_awaited_once_with(exercise_id, cursor=None, limit=50)


@pytest.mark.anyio
async def test_list_by_exercise_for_professor_not_found():
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = None
    service = EvaluationService(AsyncMock(), AsyncMock(), ex_repo, AsyncMock())

    with pytest.raises(ExerciseNotFoundError):
        await service.list_by_exercise_for_professor(uuid.uuid4(), uuid.uuid4())


@pytest.mark.anyio
async def test_list_by_exercise_for_professor_rejects_non_owner():
    exercise_id = uuid.uuid4()
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(id=exercise_id, created_by_professor_id=uuid.uuid4())
    sub_repo = AsyncMock()

    service = EvaluationService(AsyncMock(), sub_repo, ex_repo, AsyncMock())

    with pytest.raises(NotExerciseOwnerError):
        await service.list_by_exercise_for_professor(exercise_id, uuid.uuid4())
    sub_repo.list_by_exercise.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_evaluation / list_evaluations_for_submission (faille de contrôle
# d'accès corrigée — cf. docstring _authorize_submission_access)
# ---------------------------------------------------------------------------

def _make_user(role, user_id):
    return MagicMock(id=user_id, role=role)


@pytest.mark.anyio
async def test_get_evaluation_student_self_success():
    student_id = uuid.uuid4()
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    eid = uuid.uuid4()

    mock_evaluation = Evaluation(
        id=eid, submission_id=sid, question_id=qid, score=Decimal("8.5"), classic_criteria_observed=[],
    )
    eval_repo = AsyncMock()
    eval_repo.get_by_id.return_value = mock_evaluation

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(
        id=sid, exercise_id=uuid.uuid4(), student_id=student_id,
    )

    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(questions=[])

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())
    result = await service.get_evaluation(eid, _make_user(UserRole.STUDENT, student_id))

    assert result.id == eid


@pytest.mark.anyio
async def test_get_evaluation_student_other_forbidden():
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    eid = uuid.uuid4()

    eval_repo = AsyncMock()
    eval_repo.get_by_id.return_value = Evaluation(
        id=eid, submission_id=sid, question_id=qid, score=Decimal("8.5"), classic_criteria_observed=[],
    )
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4())

    service = EvaluationService(eval_repo, sub_repo, AsyncMock(), AsyncMock())

    with pytest.raises(ForbiddenError):
        await service.get_evaluation(eid, _make_user(UserRole.STUDENT, uuid.uuid4()))


@pytest.mark.anyio
async def test_get_evaluation_professor_owner_success():
    professor_id = uuid.uuid4()
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    eid = uuid.uuid4()

    eval_repo = AsyncMock()
    eval_repo.get_by_id.return_value = Evaluation(
        id=eid, submission_id=sid, question_id=qid, score=Decimal("8.5"), classic_criteria_observed=[],
    )
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4())
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(created_by_professor_id=professor_id, questions=[])

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())
    result = await service.get_evaluation(eid, _make_user(UserRole.PROFESSOR, professor_id))

    assert result.id == eid


@pytest.mark.anyio
async def test_get_evaluation_professor_non_owner_forbidden():
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    eid = uuid.uuid4()

    eval_repo = AsyncMock()
    eval_repo.get_by_id.return_value = Evaluation(
        id=eid, submission_id=sid, question_id=qid, score=Decimal("8.5"), classic_criteria_observed=[],
    )
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4())
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(created_by_professor_id=uuid.uuid4(), questions=[])

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())

    with pytest.raises(ForbiddenError):
        await service.get_evaluation(eid, _make_user(UserRole.PROFESSOR, uuid.uuid4()))


@pytest.mark.anyio
async def test_get_evaluation_admin_forbidden():
    """Ni étudiant (self) ni professeur -> 403, même pour un admin (même règle que competency-profile)."""
    sid = uuid.uuid4()
    eid = uuid.uuid4()

    eval_repo = AsyncMock()
    eval_repo.get_by_id.return_value = Evaluation(
        id=eid, submission_id=sid, question_id=uuid.uuid4(), score=Decimal("8.5"), classic_criteria_observed=[],
    )
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4())

    service = EvaluationService(eval_repo, sub_repo, AsyncMock(), AsyncMock())

    with pytest.raises(ForbiddenError):
        await service.get_evaluation(eid, _make_user(UserRole.ADMIN, uuid.uuid4()))


@pytest.mark.anyio
async def test_get_evaluation_not_found():
    eval_repo = AsyncMock()
    eval_repo.get_by_id.return_value = None
    service = EvaluationService(eval_repo, AsyncMock(), AsyncMock(), AsyncMock())

    from app.core.exceptions import EvaluationNotFoundError

    with pytest.raises(EvaluationNotFoundError):
        await service.get_evaluation(uuid.uuid4(), _make_user(UserRole.STUDENT, uuid.uuid4()))


@pytest.mark.anyio
async def test_list_evaluations_for_submission_student_self_success():
    student_id = uuid.uuid4()
    sid = uuid.uuid4()

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=student_id)

    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(questions=[])

    eval_repo = AsyncMock()
    eval_repo.list_by_submission.return_value = []

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())
    result = await service.list_evaluations_for_submission(sid, _make_user(UserRole.STUDENT, student_id))

    assert result == []


@pytest.mark.anyio
async def test_list_evaluations_for_submission_student_other_forbidden():
    sid = uuid.uuid4()
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(id=sid, exercise_id=uuid.uuid4(), student_id=uuid.uuid4())

    service = EvaluationService(AsyncMock(), sub_repo, AsyncMock(), AsyncMock())

    with pytest.raises(ForbiddenError):
        await service.list_evaluations_for_submission(sid, _make_user(UserRole.STUDENT, uuid.uuid4()))


# ---------------------------------------------------------------------------
# get_copy_report_for_professor (gap : jamais exposé par aucun endpoint)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_copy_report_for_professor_success():
    professor_id = uuid.uuid4()
    sid = uuid.uuid4()

    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(id=sid, exercise_id=uuid.uuid4())
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(created_by_professor_id=professor_id)
    eval_repo = AsyncMock()
    eval_repo.list_by_submission.return_value = []

    service = EvaluationService(eval_repo, sub_repo, ex_repo, AsyncMock())
    report = await service.get_copy_report_for_professor(sid, professor_id)

    assert report.submission_id == sid


@pytest.mark.anyio
async def test_get_copy_report_for_professor_rejects_non_owner():
    sid = uuid.uuid4()
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = MagicMock(id=sid, exercise_id=uuid.uuid4())
    ex_repo = AsyncMock()
    ex_repo.get_by_id.return_value = MagicMock(created_by_professor_id=uuid.uuid4())

    service = EvaluationService(AsyncMock(), sub_repo, ex_repo, AsyncMock())

    with pytest.raises(NotExerciseOwnerError):
        await service.get_copy_report_for_professor(sid, uuid.uuid4())


@pytest.mark.anyio
async def test_get_copy_report_for_professor_submission_not_found():
    sub_repo = AsyncMock()
    sub_repo.get_by_id.return_value = None
    service = EvaluationService(AsyncMock(), sub_repo, AsyncMock(), AsyncMock())

    with pytest.raises(SubmissionNotFoundError):
        await service.get_copy_report_for_professor(uuid.uuid4(), uuid.uuid4())
