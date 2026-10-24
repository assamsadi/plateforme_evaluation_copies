"""
Tests unitaires — FeedbackReportService (chantier "Feedback Intelligent", §7).

Couvre :
1. Précondition PENDING_ARBITRATION — vérifiée AVANT toute lecture/appel
   LLM, même principe que CompetencyAssessmentService.assess_submission.
2. SubmissionNotFoundError si la soumission n'existe pas.
3. Chemin nominal : profil + recommandations réunis, agent appelé, résultat
   persisté via le repository.
4. Repli sur le profil complet si Recommendation_Agent n'a retenu aucune
   compétence cette fois-ci (jamais un feedback bâti sur rien).
5. get_by_submission_for_student — 404 si absent, 403 si un autre étudiant.
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.Competency_Assessment_Agent import CompetencyProfileLine, StudentCompetencyReport
from app.agents.Feedback_Agent import FeedbackReport
from app.core.exceptions import (
    FeedbackReportNotFoundError,
    ForbiddenError,
    SubmissionNotFoundError,
    SubmissionPendingArbitrationError,
)
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.services.feedback_report_service import FeedbackReportService

AS = C2PCTSkillCode.ALGORITHMIC_STRUCTURING
DAP = C2PCTSkillCode.DATA_AND_PLANNING


def _service(
    feedback_report_repo=None, competency_assessment_service=None,
    recommendation_repo=None, exercise_repo=None, submission_repo=None, agent=None,
) -> FeedbackReportService:
    return FeedbackReportService(
        feedback_report_repo=feedback_report_repo or AsyncMock(),
        competency_assessment_service=competency_assessment_service or AsyncMock(),
        recommendation_repo=recommendation_repo or AsyncMock(),
        exercise_repo=exercise_repo or AsyncMock(),
        submission_repo=submission_repo or AsyncMock(),
        agent=agent,
    )


@pytest.mark.anyio
async def test_pending_arbitration_blocks_generation():
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = MagicMock(status=SubmissionStatus.PENDING_ARBITRATION)
    competency_service = AsyncMock()
    agent = AsyncMock()

    service = _service(submission_repo=submission_repo, competency_assessment_service=competency_service, agent=agent)

    with pytest.raises(SubmissionPendingArbitrationError):
        await service.generate_feedback(
            submission_id=uuid.uuid4(), student_id=uuid.uuid4(), module_id=uuid.uuid4(), ctx=MagicMock(),
        )

    competency_service.get_report.assert_not_called()
    agent.generate_feedback.assert_not_called()


@pytest.mark.anyio
async def test_submission_not_found_raises():
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = None
    service = _service(submission_repo=submission_repo)

    with pytest.raises(SubmissionNotFoundError):
        await service.generate_feedback(
            submission_id=uuid.uuid4(), student_id=uuid.uuid4(), module_id=uuid.uuid4(), ctx=MagicMock(),
        )


@pytest.mark.anyio
async def test_nominal_path_gathers_context_calls_agent_and_persists():
    student_id, submission_id, module_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = MagicMock(status=SubmissionStatus.EVALUATED)

    line = CompetencyProfileLine(
        competency=AS, mastery_level=Decimal("30.00"), trend="DECLINING", evaluations_count=2,
        weaknesses=["3.1 (Boucles)"], identified_difficulties=["Condition d'arrêt jamais formulée"],
        strengths=["Bonne décomposition"],
    )
    competency_service = AsyncMock()
    competency_service.get_report.return_value = StudentCompetencyReport(
        student_id=student_id, module_id=module_id, generated_at=MagicMock(), lines=[line],
    )

    exercise_id = uuid.uuid4()
    recommendation = MagicMock(competency_code=AS, exercise_id=exercise_id, reason="Faiblesse persistante.")
    recommendation_repo = AsyncMock()
    recommendation_repo.list_by_submission.return_value = [recommendation]

    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = MagicMock(title="Exercice de boucles")

    produced_report = FeedbackReport(
        student_id=student_id, submission_id=submission_id,
        feedback_text="Relis ta boucle : que vérifies-tu avant d'y entrer ?",
        competencies_addressed=[AS], generated_at=MagicMock(),
    )
    agent = AsyncMock()
    agent.generate_feedback.return_value = produced_report

    feedback_report_repo = AsyncMock()

    service = _service(
        feedback_report_repo=feedback_report_repo, competency_assessment_service=competency_service,
        recommendation_repo=recommendation_repo, exercise_repo=exercise_repo,
        submission_repo=submission_repo, agent=agent,
    )

    result = await service.generate_feedback(
        submission_id=submission_id, student_id=student_id, module_id=module_id, ctx=MagicMock(),
    )

    assert result is produced_report

    # L'agent doit recevoir la compétence réellement retenue par Recommendation_Agent, avec ses vraies difficultés.
    call_kwargs = agent.generate_feedback.call_args.kwargs
    assert len(call_kwargs["competencies"]) == 1
    assert call_kwargs["competencies"][0].competency == AS
    assert call_kwargs["competencies"][0].identified_difficulties == ["Condition d'arrêt jamais formulée"]
    assert len(call_kwargs["recommendations"]) == 1
    assert call_kwargs["recommendations"][0].exercise_title == "Exercice de boucles"

    feedback_report_repo.create.assert_awaited_once_with(
        student_id=student_id, module_id=module_id, submission_id=submission_id,
        feedback_text=produced_report.feedback_text,
        competencies_addressed=[AS.value],
    )


@pytest.mark.anyio
async def test_falls_back_to_full_profile_when_no_recommendation_retained():
    """Aucune compétence retenue par Recommendation_Agent cette fois -> repli sur le profil complet (jamais rien)."""
    student_id, submission_id, module_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = MagicMock(status=SubmissionStatus.EVALUATED)

    line_as = CompetencyProfileLine(
        competency=AS, mastery_level=Decimal("95.00"), trend="STABLE", evaluations_count=3,
        strengths=["Excellente maîtrise des boucles"],
    )
    line_dap = CompetencyProfileLine(
        competency=DAP, mastery_level=Decimal("90.00"), trend="IMPROVING", evaluations_count=2,
        strengths=["Bonne planification"],
    )
    competency_service = AsyncMock()
    competency_service.get_report.return_value = StudentCompetencyReport(
        student_id=student_id, module_id=module_id, generated_at=MagicMock(), lines=[line_as, line_dap],
    )

    recommendation_repo = AsyncMock()
    recommendation_repo.list_by_submission.return_value = []  # rien de retenu

    agent = AsyncMock()
    agent.generate_feedback.return_value = FeedbackReport(
        student_id=student_id, submission_id=submission_id,
        feedback_text="Continue ainsi, comment pourrais-tu aller encore plus loin ?",
        competencies_addressed=[AS, DAP], generated_at=MagicMock(),
    )

    service = _service(
        competency_assessment_service=competency_service, recommendation_repo=recommendation_repo,
        submission_repo=submission_repo, agent=agent,
    )

    await service.generate_feedback(
        submission_id=submission_id, student_id=student_id, module_id=module_id, ctx=MagicMock(),
    )

    call_kwargs = agent.generate_feedback.call_args.kwargs
    assert {c.competency for c in call_kwargs["competencies"]} == {AS, DAP}


@pytest.mark.anyio
async def test_get_by_submission_not_found_raises_404_equivalent():
    feedback_report_repo = AsyncMock()
    feedback_report_repo.get_by_submission.return_value = None
    service = _service(feedback_report_repo=feedback_report_repo)

    with pytest.raises(FeedbackReportNotFoundError):
        await service.get_by_submission_for_student(uuid.uuid4(), uuid.uuid4())


@pytest.mark.anyio
async def test_get_by_submission_other_student_forbidden():
    owner_id = uuid.uuid4()
    record = MagicMock(student_id=owner_id)
    feedback_report_repo = AsyncMock()
    feedback_report_repo.get_by_submission.return_value = record
    service = _service(feedback_report_repo=feedback_report_repo)

    with pytest.raises(ForbiddenError):
        await service.get_by_submission_for_student(uuid.uuid4(), uuid.uuid4())
