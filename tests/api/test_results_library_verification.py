import uuid
from decimal import Decimal

import pytest

from app.domain.models.assessment.feedback_version import FeedbackAuthorType
from app.domain.models.system_infrastructure.audit_log import AuditSeverity
from app.domain.models.system_infrastructure.integrity_alert import IntegrityAlertStatus
from app.domain.models.system_infrastructure.data_privacy_request import PrivacyRequestType


def _make_evaluation_read():
    return {
        "id": str(uuid.uuid4()),
        "submission_id": str(uuid.uuid4()),
        "question_id": str(uuid.uuid4()),
        "question_order": 1,
        "score": "8.5",
        "classic_criteria_observed": [],
        "criteria": [],
    }


def _make_feedback_version_read():
    return {
        "id": str(uuid.uuid4()),
        "feedback_id": str(uuid.uuid4()),
        "version_number": 1,
        "content": "Bien joué !",
        "author_type": FeedbackAuthorType.TEACHER.value,
        "author_full_name": "Bob Martin",
    }


def _make_grade_appeal_read():
    return {
        "id": str(uuid.uuid4()),
        "submission_id": str(uuid.uuid4()),
        "evaluation_id": str(uuid.uuid4()),
        "extraction_correction_id": None,
        "student_id": str(uuid.uuid4()),
        "student_full_name": "Alice Dupont",
        "reason": "Note incorrecte",
        "original_score": "8.5",
        "status": "pending",
        "resolution": None,
        "revised_score": None,
        "resolved_by_professor_id": None,
        "review_comment": None,
        "resolved_at": None,
        "ai_reevaluation_score": None,
        "ai_reevaluation_justification": None,
        "ai_reevaluation_criteria": None,
    }


@pytest.mark.anyio
async def test_get_evaluation_success(professor_client, mock_evaluation_service):
    """
    Bug corrigé (audit résultats professeur) : le routeur appelait
    evaluation_service.get_evaluation(evaluation_id) sans requesting_user —
    méthode inexistante avant ce correctif (AttributeError -> 500 à chaque
    appel réel, masqué ici par un AsyncMock nu qui accepte n'importe quel
    nom d'attribut). Signature réelle désormais (evaluation_id, current_user).
    """
    mock_evaluation_service.get_evaluation.return_value = _make_evaluation_read()
    response = await professor_client.get(f"/api/v1/evaluations/{uuid.uuid4()}")
    assert response.status_code == 200
    mock_evaluation_service.get_evaluation.assert_awaited_once()


@pytest.mark.anyio
async def test_get_evaluation_forbidden(student_client, mock_evaluation_service):
    """
    Faille corrigée (audit résultats professeur) : aucun contrôle d'accès
    n'existait auparavant — un étudiant pouvait consulter l'évaluation de
    N'IMPORTE QUELLE soumission. Le contrôle vit dans EvaluationService.
    _authorize_submission_access (ForbiddenError -> 403 via le handler
    global), simulé ici via side_effect (même pattern que
    test_get_student_competency_profile_professor_without_exercise_in_module_forbidden).
    """
    from app.core.exceptions import ForbiddenError

    mock_evaluation_service.get_evaluation.side_effect = ForbiddenError(
        "Un étudiant ne peut consulter que ses propres évaluations."
    )
    response = await student_client.get(f"/api/v1/evaluations/{uuid.uuid4()}")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_list_evaluations_for_submission(professor_client, mock_evaluation_service):
    """
    Bug corrigé (audit résultats professeur) : le routeur appelait
    evaluation_service.list_evaluations_by_submission(submission_id),
    méthode inexistante avant ce correctif (même masquage AsyncMock que
    get_evaluation ci-dessus). Nom réel : list_evaluations_for_submission.
    """
    mock_evaluation_service.list_evaluations_for_submission.return_value = [_make_evaluation_read()]
    response = await professor_client.get(f"/api/v1/submissions/{uuid.uuid4()}/evaluations")
    assert response.status_code == 200
    mock_evaluation_service.list_evaluations_for_submission.assert_awaited_once()


@pytest.mark.anyio
async def test_list_evaluations_for_submission_forbidden(student_client, mock_evaluation_service):
    from app.core.exceptions import ForbiddenError

    mock_evaluation_service.list_evaluations_for_submission.side_effect = ForbiddenError(
        "Un étudiant ne peut consulter que ses propres évaluations."
    )
    response = await student_client.get(f"/api/v1/submissions/{uuid.uuid4()}/evaluations")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_submission_copy_report_success(professor_client, mock_evaluation_service):
    """
    Gap fermé (audit résultats professeur) : EvaluationService.get_copy_report
    existait déjà mais n'était exposé par AUCUN endpoint.
    """
    submission_id = uuid.uuid4()
    mock_evaluation_service.get_copy_report_for_professor.return_value = {
        "submission_id": str(submission_id),
        "overview": {
            "questions_sans_ambiguite": 2,
            "questions_necessitant_un_regard": 1,
            "consigne_non_respectee_count": 0,
        },
        "questions": [],
    }
    response = await professor_client.get(f"/api/v1/submissions/{submission_id}/copy-report")
    assert response.status_code == 200
    mock_evaluation_service.get_copy_report_for_professor.assert_awaited_once_with(
        submission_id, "00000000-0000-4000-a000-000000000002"
    )


@pytest.mark.anyio
async def test_get_submission_copy_report_requires_professor(student_client, mock_evaluation_service):
    response = await student_client.get(f"/api/v1/submissions/{uuid.uuid4()}/copy-report")
    assert response.status_code == 403


@pytest.mark.anyio
async def test_list_feedbacks_for_evaluation(admin_client, mock_feedback_service):
    mock_feedback_service.list_versions_by_evaluation.return_value = [_make_feedback_version_read()]
    response = await admin_client.get(f"/api/v1/evaluations/{uuid.uuid4()}/feedbacks")
    assert response.status_code == 200
    mock_feedback_service.list_versions_by_evaluation.assert_awaited_once()


@pytest.mark.anyio
async def test_submit_grade_appeal_success(student_client, mock_grade_appeal_service):
    mock_grade_appeal_service.file_appeal.return_value = _make_grade_appeal_read()
    submission_id = uuid.uuid4()
    evaluation_id = uuid.uuid4()
    payload = {
        "submission_id": str(submission_id),
        "evaluation_id": str(evaluation_id),
        "reason": "Note incorrecte",
    }
    response = await student_client.post("/api/v1/appeals", json=payload)
    assert response.status_code == 201
    mock_grade_appeal_service.file_appeal.assert_awaited_once_with(
        submission_id=submission_id,
        student_id="00000000-0000-4000-a000-000000000001",
        reason="Note incorrecte",
        evaluation_id=evaluation_id,
        extraction_correction_id=None,
    )


@pytest.mark.anyio
async def test_submit_grade_appeal_requires_student(professor_client, mock_grade_appeal_service):
    payload = {
        "submission_id": str(uuid.uuid4()),
        "evaluation_id": str(uuid.uuid4()),
        "reason": "Note incorrecte",
    }
    response = await professor_client.post("/api/v1/appeals", json=payload)
    assert response.status_code == 403


@pytest.mark.anyio
async def test_list_pending_appeals_success(professor_client, mock_grade_appeal_service):
    from app.domain.repositories.pagination import CursorPage

    mock_grade_appeal_service.list_pending_for_professor.return_value = CursorPage(
        items=[_make_grade_appeal_read()], next_cursor=None, has_more=False
    )
    response = await professor_client.get("/api/v1/appeals/pending")
    assert response.status_code == 200
    mock_grade_appeal_service.list_pending_for_professor.assert_awaited_once_with(
        "00000000-0000-4000-a000-000000000002", cursor=None, limit=50
    )


@pytest.mark.anyio
async def test_resolve_grade_appeal_success(professor_client, mock_grade_appeal_service):
    mock_grade_appeal_service.resolve_appeal.return_value = _make_grade_appeal_read()
    appeal_id = uuid.uuid4()
    response = await professor_client.post(
        f"/api/v1/appeals/{appeal_id}/resolve",
        json={"resolution": "grade_upheld", "review_comment": "Note correcte."},
    )
    assert response.status_code == 200
    mock_grade_appeal_service.resolve_appeal.assert_awaited_once_with(
        appeal_id=appeal_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
        resolution="grade_upheld",
        review_comment="Note correcte.",
        revised_score=None,
    )


@pytest.mark.anyio
async def test_resolve_grade_appeal_grade_revised_requires_revised_score(
    professor_client, mock_grade_appeal_service,
):
    """
    Gap fermé (audit espace professeur) : le champ revised_score était
    documenté comme requis pour toute résolution != grade_upheld, mais
    rien ne l'imposait réellement — cf. nouveau model_validator sur
    GradeAppealResolutionRequest.
    """
    appeal_id = uuid.uuid4()
    response = await professor_client.post(
        f"/api/v1/appeals/{appeal_id}/resolve",
        json={"resolution": "grade_revised", "review_comment": "Corrigé."},
    )
    assert response.status_code == 422
    mock_grade_appeal_service.resolve_appeal.assert_not_awaited()


@pytest.mark.anyio
async def test_resolve_grade_appeal_grade_revised_with_score_succeeds(
    professor_client, mock_grade_appeal_service,
):
    mock_grade_appeal_service.resolve_appeal.return_value = _make_grade_appeal_read()
    appeal_id = uuid.uuid4()
    response = await professor_client.post(
        f"/api/v1/appeals/{appeal_id}/resolve",
        json={"resolution": "grade_revised", "revised_score": "9.5", "review_comment": "Corrigé."},
    )
    assert response.status_code == 200
    mock_grade_appeal_service.resolve_appeal.assert_awaited_once_with(
        appeal_id=appeal_id,
        requesting_professor_id="00000000-0000-4000-a000-000000000002",
        resolution="grade_revised",
        review_comment="Corrigé.",
        revised_score=Decimal("9.5"),
    )


@pytest.mark.anyio
async def test_get_my_statistics(student_client, mock_statistics_service):
    mock_statistics_service.get_student_stats.return_value = {"total": 10, "average": 8.5}
    response = await student_client.get("/api/v1/students/me/stats")
    assert response.status_code == 200
    mock_statistics_service.get_student_stats.assert_awaited_once()


@pytest.mark.anyio
async def test_get_my_competency_profile(student_client, fake_student, mock_competency_assessment_service):
    """
    Correctif découvertes annexes (priorité 3) — délègue désormais à
    CompetencyAssessmentService.get_report (StatisticsService.
    get_student_competency_profile, cassé, retiré), même mécanisme que
    GET /students/{student_id}/competency-profile. module_id requis
    (donnée scopée par module).
    """
    module_id = uuid.uuid4()
    mock_competency_assessment_service.get_report.return_value = {
        "student_id": str(fake_student.id), "module_id": str(module_id),
        "generated_at": "2026-08-12T00:00:00Z", "lines": [],
    }
    response = await student_client.get(f"/api/v1/students/me/competency-profile?module_id={module_id}")
    assert response.status_code == 200
    mock_competency_assessment_service.get_report.assert_awaited_once_with(
        uuid.UUID(str(fake_student.id)), module_id,
    )


# ---------------------------------------------------------------------------
# GET /students/{student_id}/competency-profile (câblage Partie 2/2, C2PCT)
# ---------------------------------------------------------------------------

def _make_student_competency_report(student_id, module_id):
    return {
        "student_id": str(student_id), "module_id": str(module_id),
        "generated_at": "2026-08-12T00:00:00Z", "lines": [],
    }


@pytest.mark.anyio
async def test_get_student_competency_profile_self_success(
    student_client, fake_student, mock_competency_assessment_service,
):
    module_id = uuid.uuid4()
    mock_competency_assessment_service.get_report.return_value = _make_student_competency_report(
        fake_student.id, module_id,
    )
    response = await student_client.get(
        f"/api/v1/students/{fake_student.id}/competency-profile?module_id={module_id}"
    )
    assert response.status_code == 200
    mock_competency_assessment_service.get_report.assert_awaited_once_with(
        uuid.UUID(str(fake_student.id)), module_id,
    )
    mock_competency_assessment_service.get_report_as_professor.assert_not_called()


@pytest.mark.anyio
async def test_get_student_competency_profile_student_other_forbidden(
    student_client, mock_competency_assessment_service,
):
    other_student_id = uuid.uuid4()
    module_id = uuid.uuid4()
    response = await student_client.get(
        f"/api/v1/students/{other_student_id}/competency-profile?module_id={module_id}"
    )
    assert response.status_code == 403
    mock_competency_assessment_service.get_report.assert_not_awaited()


@pytest.mark.anyio
async def test_get_student_competency_profile_professor_success(
    professor_client, fake_professor, mock_competency_assessment_service,
):
    student_id = uuid.uuid4()
    module_id = uuid.uuid4()
    mock_competency_assessment_service.get_report_as_professor.return_value = (
        _make_student_competency_report(student_id, module_id)
    )
    response = await professor_client.get(
        f"/api/v1/students/{student_id}/competency-profile?module_id={module_id}"
    )
    assert response.status_code == 200
    mock_competency_assessment_service.get_report_as_professor.assert_awaited_once_with(
        professor_id=uuid.UUID(str(fake_professor.id)), student_id=student_id, module_id=module_id,
    )


@pytest.mark.anyio
async def test_get_student_competency_profile_professor_without_exercise_in_module_forbidden(
    professor_client, mock_competency_assessment_service,
):
    """
    Le contrôle "le professeur enseigne ce module" est délégué au service
    (ExerciseRepository.exists_professor_exercise_in_module) — ForbiddenError
    levée là-bas doit être mappée 403 par le handler global (app/main.py),
    pas rattrapée localement dans le routeur.
    """
    from app.core.exceptions import ForbiddenError

    mock_competency_assessment_service.get_report_as_professor.side_effect = ForbiddenError(
        "Le professeur n'a aucun exercice dans ce module."
    )
    response = await professor_client.get(
        f"/api/v1/students/{uuid.uuid4()}/competency-profile?module_id={uuid.uuid4()}"
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_student_competency_profile_admin_forbidden(
    admin_client, mock_competency_assessment_service,
):
    """Ni étudiant (self) ni professeur -> 403, même pour un admin (spec explicite du ticket)."""
    response = await admin_client.get(
        f"/api/v1/students/{uuid.uuid4()}/competency-profile?module_id={uuid.uuid4()}"
    )
    assert response.status_code == 403
    mock_competency_assessment_service.get_report.assert_not_awaited()
    mock_competency_assessment_service.get_report_as_professor.assert_not_awaited()


def _make_recommended_exercise_read():
    return {
        "id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "module_id": str(uuid.uuid4()),
        "competency_code": "algorithmic_structuring",
        "category": "remediation",
        "status": "active",
        "submission_id": str(uuid.uuid4()),
        "exercise_id": str(uuid.uuid4()),
        "exercise_title": "Examen final",
        "reason": "À revoir",
        "relevance_score": "0.85",
    }


@pytest.mark.anyio
async def test_get_my_recommendations(student_client, mock_recommendation_service):
    mock_recommendation_service.get_student_dashboard.return_value = [_make_recommended_exercise_read()]
    response = await student_client.get("/api/v1/library/recommendations")
    assert response.status_code == 200
    mock_recommendation_service.get_student_dashboard.assert_awaited_once()


@pytest.mark.anyio
async def test_create_recommendation_success(professor_client, fake_professor, mock_recommendation_service):
    """
    Fermeture de la faille d'accès (chantier Recommendation_Agent, Phase 3) —
    seul un professeur peut désormais appeler ce point d'écriture (avant :
    n'importe quel rôle authentifié, cf. test_create_recommendation_requires_
    professor ci-dessous pour la preuve du changement).
    """
    mock_recommendation_service.create_recommendation.return_value = _make_recommended_exercise_read()
    response = await professor_client.post(
        f"/api/v1/library/recommendations?submission_id={uuid.uuid4()}&exercise_id={uuid.uuid4()}"
        f"&competency_code=algorithmic_structuring&reason=À+revoir&relevance_score=0.85"
    )
    assert response.status_code == 201
    mock_recommendation_service.create_recommendation.assert_awaited_once()
    _, kwargs = mock_recommendation_service.create_recommendation.await_args
    assert str(kwargs["requesting_professor_id"]) == str(fake_professor.id)


@pytest.mark.anyio
async def test_create_recommendation_requires_professor(student_client, mock_recommendation_service):
    """Un étudiant (ou tout rôle non-PROFESSOR) est rejeté avant même d'atteindre le service."""
    response = await student_client.post(
        f"/api/v1/library/recommendations?submission_id={uuid.uuid4()}&exercise_id={uuid.uuid4()}"
        f"&competency_code=algorithmic_structuring&reason=À+revoir&relevance_score=0.85"
    )
    assert response.status_code == 403
    mock_recommendation_service.create_recommendation.assert_not_awaited()


@pytest.mark.anyio
async def test_create_recommendation_professor_without_exercise_in_module_forbidden(
    professor_client, mock_recommendation_service,
):
    """
    Le contrôle "le professeur enseigne ce module" est délégué au service
    (ExerciseRepository.exists_professor_exercise_in_module) — ForbiddenError
    levée là-bas doit être mappée 403 par le handler global, même principe
    que GET /students/{id}/competency-profile.
    """
    from app.core.exceptions import ForbiddenError

    mock_recommendation_service.create_recommendation.side_effect = ForbiddenError(
        "Le professeur n'a aucun exercice dans ce module."
    )
    response = await professor_client.post(
        f"/api/v1/library/recommendations?submission_id={uuid.uuid4()}&exercise_id={uuid.uuid4()}"
        f"&competency_code=algorithmic_structuring&reason=À+revoir&relevance_score=0.85"
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# GET /students/{student_id}/recommendations (clôture du chantier
# Recommendation_Agent — traçabilité professeur, même couple self/professeur
# que GET /students/{student_id}/competency-profile ci-dessus).
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_student_recommendations_self_success(
    student_client, fake_student, mock_recommendation_service,
):
    module_id = uuid.uuid4()
    mock_recommendation_service.get_student_dashboard_for_module.return_value = [
        _make_recommended_exercise_read()
    ]
    response = await student_client.get(
        f"/api/v1/students/{fake_student.id}/recommendations?module_id={module_id}"
    )
    assert response.status_code == 200
    mock_recommendation_service.get_student_dashboard_for_module.assert_awaited_once_with(
        uuid.UUID(str(fake_student.id)), module_id,
    )
    mock_recommendation_service.get_student_dashboard_as_professor.assert_not_called()


@pytest.mark.anyio
async def test_get_student_recommendations_student_other_forbidden(
    student_client, mock_recommendation_service,
):
    other_student_id = uuid.uuid4()
    module_id = uuid.uuid4()
    response = await student_client.get(
        f"/api/v1/students/{other_student_id}/recommendations?module_id={module_id}"
    )
    assert response.status_code == 403
    mock_recommendation_service.get_student_dashboard_for_module.assert_not_awaited()


@pytest.mark.anyio
async def test_get_student_recommendations_professor_success(
    professor_client, fake_professor, mock_recommendation_service,
):
    student_id = uuid.uuid4()
    module_id = uuid.uuid4()
    mock_recommendation_service.get_student_dashboard_as_professor.return_value = [
        _make_recommended_exercise_read()
    ]
    response = await professor_client.get(
        f"/api/v1/students/{student_id}/recommendations?module_id={module_id}"
    )
    assert response.status_code == 200
    mock_recommendation_service.get_student_dashboard_as_professor.assert_awaited_once_with(
        professor_id=uuid.UUID(str(fake_professor.id)), student_id=student_id, module_id=module_id,
    )


@pytest.mark.anyio
async def test_get_student_recommendations_professor_without_exercise_in_module_forbidden(
    professor_client, mock_recommendation_service,
):
    from app.core.exceptions import ForbiddenError

    mock_recommendation_service.get_student_dashboard_as_professor.side_effect = ForbiddenError(
        "Le professeur n'a aucun exercice dans ce module."
    )
    response = await professor_client.get(
        f"/api/v1/students/{uuid.uuid4()}/recommendations?module_id={uuid.uuid4()}"
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_get_student_recommendations_admin_forbidden(
    admin_client, mock_recommendation_service,
):
    """Ni étudiant (self) ni professeur -> 403, même pour un admin (même règle que competency-profile)."""
    response = await admin_client.get(
        f"/api/v1/students/{uuid.uuid4()}/recommendations?module_id={uuid.uuid4()}"
    )
    assert response.status_code == 403
    mock_recommendation_service.get_student_dashboard_for_module.assert_not_awaited()
    mock_recommendation_service.get_student_dashboard_as_professor.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /students/{id}/recommendations/{id}/generate-video +
# POST /students/{id}/recommendations/{id}/notebook-chat (§7, Partie 2/2) —
# réservés à l'étudiant lui-même, jamais un professeur.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_generate_video_overview_self_success(student_client, fake_student, mock_recommendation_service):
    recommendation_id = uuid.uuid4()
    mock_recommendation_service.request_video_overview.return_value = {
        "video_overview_status": "pending", "video_overview_url": None,
    }
    response = await student_client.post(
        f"/api/v1/students/{fake_student.id}/recommendations/{recommendation_id}/generate-video"
    )
    assert response.status_code == 200
    assert response.json() == {"video_overview_status": "pending", "video_overview_url": None}
    mock_recommendation_service.request_video_overview.assert_awaited_once_with(
        requesting_student_id=uuid.UUID(str(fake_student.id)), recommendation_id=recommendation_id,
    )


@pytest.mark.anyio
async def test_generate_video_overview_requires_self_not_other_student(student_client, mock_recommendation_service):
    other_student_id = uuid.uuid4()
    response = await student_client.post(
        f"/api/v1/students/{other_student_id}/recommendations/{uuid.uuid4()}/generate-video"
    )
    assert response.status_code == 403
    mock_recommendation_service.request_video_overview.assert_not_awaited()


@pytest.mark.anyio
async def test_generate_video_overview_forbidden_for_professor(professor_client, mock_recommendation_service):
    """Réservé à l'étudiant — un professeur, même légitime par ailleurs, est toujours refusé ici."""
    response = await professor_client.post(
        f"/api/v1/students/{uuid.uuid4()}/recommendations/{uuid.uuid4()}/generate-video"
    )
    assert response.status_code == 403
    mock_recommendation_service.request_video_overview.assert_not_awaited()


@pytest.mark.anyio
async def test_generate_video_overview_no_notebook_returns_404(student_client, fake_student, mock_recommendation_service):
    from app.core.exceptions import NotebookNotFoundError

    recommendation_id = uuid.uuid4()
    mock_recommendation_service.request_video_overview.side_effect = NotebookNotFoundError(recommendation_id)
    response = await student_client.post(
        f"/api/v1/students/{fake_student.id}/recommendations/{recommendation_id}/generate-video"
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_ask_notebook_chat_self_success(student_client, fake_student, mock_recommendation_service):
    recommendation_id = uuid.uuid4()
    mock_recommendation_service.ask_notebook_chat.return_value = "Voici pourquoi..."
    response = await student_client.post(
        f"/api/v1/students/{fake_student.id}/recommendations/{recommendation_id}/notebook-chat",
        json={"question": "Pourquoi ma maîtrise est-elle faible ?"},
    )
    assert response.status_code == 200
    assert response.json() == {"answer": "Voici pourquoi..."}
    mock_recommendation_service.ask_notebook_chat.assert_awaited_once_with(
        requesting_student_id=uuid.UUID(str(fake_student.id)), recommendation_id=recommendation_id,
        question="Pourquoi ma maîtrise est-elle faible ?",
    )


@pytest.mark.anyio
async def test_ask_notebook_chat_forbidden_for_professor(professor_client, mock_recommendation_service):
    response = await professor_client.post(
        f"/api/v1/students/{uuid.uuid4()}/recommendations/{uuid.uuid4()}/notebook-chat",
        json={"question": "Une question ?"},
    )
    assert response.status_code == 403
    mock_recommendation_service.ask_notebook_chat.assert_not_awaited()


@pytest.mark.anyio
async def test_ask_notebook_chat_service_failure_returns_503(student_client, fake_student, mock_recommendation_service):
    from app.core.exceptions import NotebookLMUnavailableError

    mock_recommendation_service.ask_notebook_chat.side_effect = NotebookLMUnavailableError("nb-1")
    response = await student_client.post(
        f"/api/v1/students/{fake_student.id}/recommendations/{uuid.uuid4()}/notebook-chat",
        json={"question": "Une question ?"},
    )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# GET /students/{id}/submissions/{id}/feedback (chantier Feedback_Agent, §7)
# — réservé à l'étudiant lui-même, jamais un professeur (même garde que les
# endpoints vidéo/chat ci-dessus).
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_get_submission_feedback_self_success(student_client, fake_student, mock_feedback_report_service):
    from datetime import datetime, timezone

    from app.domain.schemas.evaluation_schemas import FeedbackReportRead

    submission_id = uuid.uuid4()
    mock_feedback_report_service.get_by_submission_for_student.return_value = FeedbackReportRead(
        submission_id=submission_id,
        feedback_text="Relis ta boucle : que vérifies-tu avant d'y entrer ?",
        competencies_addressed=["algorithmic_structuring"],
        generated_at=datetime.now(timezone.utc),
    )

    response = await student_client.get(
        f"/api/v1/students/{fake_student.id}/submissions/{submission_id}/feedback"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["submission_id"] == str(submission_id)
    assert "?" in body["feedback_text"]
    assert body["competencies_addressed"] == ["algorithmic_structuring"]
    mock_feedback_report_service.get_by_submission_for_student.assert_awaited_once_with(
        submission_id=submission_id, requesting_student_id=uuid.UUID(str(fake_student.id)),
    )


@pytest.mark.anyio
async def test_get_submission_feedback_requires_self_not_other_student(student_client, mock_feedback_report_service):
    other_student_id = uuid.uuid4()
    response = await student_client.get(
        f"/api/v1/students/{other_student_id}/submissions/{uuid.uuid4()}/feedback"
    )
    assert response.status_code == 403
    mock_feedback_report_service.get_by_submission_for_student.assert_not_awaited()


@pytest.mark.anyio
async def test_get_submission_feedback_forbidden_for_professor(professor_client, mock_feedback_report_service):
    response = await professor_client.get(
        f"/api/v1/students/{uuid.uuid4()}/submissions/{uuid.uuid4()}/feedback"
    )
    assert response.status_code == 403
    mock_feedback_report_service.get_by_submission_for_student.assert_not_awaited()


@pytest.mark.anyio
async def test_get_submission_feedback_not_yet_generated_returns_404(
    student_client, fake_student, mock_feedback_report_service,
):
    from app.core.exceptions import FeedbackReportNotFoundError

    submission_id = uuid.uuid4()
    mock_feedback_report_service.get_by_submission_for_student.side_effect = FeedbackReportNotFoundError(submission_id)

    response = await student_client.get(
        f"/api/v1/students/{fake_student.id}/submissions/{submission_id}/feedback"
    )

    assert response.status_code == 404


def _make_integrity_alert_read():
    return {
        "id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "student_full_name": "Alice Dupont",
        "trigger_type": "suspicious_pattern",
        "auto_generated": True,
        "evidence": {},
        "reason": "Copie suspecte",
        "status": IntegrityAlertStatus.PENDING.value,
        "action_taken": None,
        "reviewed_by_user_id": None,
        "review_notes": None,
        "reviewed_at": None,
        "created_at": "2024-01-01T00:00:00Z",
    }


def _make_data_privacy_request_read():
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "user_full_name": "Dana Petit",
        "request_type": PrivacyRequestType.ACCESS_EXPORT.value,
        "status": "pending",
        "legal_deadline": "2024-02-01T00:00:00Z",
        "identity_verified": False,
        "processed_by_user_id": None,
        "processed_at": None,
        "resolution_detail": None,
        "retention_or_rejection_reason": None,
        "export_file_url": None,
        "export_file_expires_at": None,
        "created_at": "2024-01-01T00:00:00Z",
    }


def _make_audit_log_read():
    return {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "user_full_name": "Charlie Bernard",
        "entity_type": "auth",
        "entity_id": str(uuid.uuid4()),
        "action": "login",
        "diff": None,
        "success": True,
        "severity": AuditSeverity.INFO.value,
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.mark.anyio
async def test_list_unresolved_integrity_alerts(admin_client, mock_integrity_service):
    mock_integrity_service.list_pending.return_value = [_make_integrity_alert_read()]
    response = await admin_client.get("/api/v1/integrity/alerts/unresolved")
    assert response.status_code == 200
    mock_integrity_service.list_pending.assert_awaited_once()


@pytest.mark.anyio
async def test_resolve_integrity_alert(admin_client, mock_integrity_service):
    mock_integrity_service.review_alert.return_value = _make_integrity_alert_read()
    alert_id = uuid.uuid4()
    response = await admin_client.post(
        f"/api/v1/integrity/alerts/{alert_id}/resolve",
        json={"status": "confirmed", "action_taken": "warning_issued", "review_notes": "OK"},
    )
    assert response.status_code == 200
    mock_integrity_service.review_alert.assert_awaited_once()


@pytest.mark.anyio
class TestFlagStudentManually:
    """
    Gap fermé (audit espace admin) : IntegrityService.flag_student()
    existait déjà, complète, mais aucun endpoint ne l'exposait.
    """

    async def test_professor_can_flag(self, professor_client, mock_integrity_service):
        mock_integrity_service.flag_student.return_value = _make_integrity_alert_read()
        student_id = uuid.uuid4()
        response = await professor_client.post(
            "/api/v1/integrity/alerts",
            json={
                "student_id": str(student_id),
                "trigger_type": "suspected_plagiarism",
                "reason": "Similitude anormale avec une autre copie",
                "evidence": {"similarity_score": 0.95},
            },
        )
        assert response.status_code == 201
        mock_integrity_service.flag_student.assert_awaited_once_with(
            student_id=student_id,
            trigger_type="suspected_plagiarism",
            reason="Similitude anormale avec une autre copie",
            evidence={"similarity_score": 0.95},
            auto_generated=False,
        )

    async def test_admin_can_flag(self, admin_client, mock_integrity_service):
        mock_integrity_service.flag_student.return_value = _make_integrity_alert_read()
        response = await admin_client.post(
            "/api/v1/integrity/alerts",
            json={
                "student_id": str(uuid.uuid4()),
                "trigger_type": "manual_flag",
                "reason": "Signalement direct",
            },
        )
        assert response.status_code == 201

    async def test_student_forbidden(self, student_client, mock_integrity_service):
        response = await student_client.post(
            "/api/v1/integrity/alerts",
            json={
                "student_id": str(uuid.uuid4()),
                "trigger_type": "manual_flag",
                "reason": "Signalement direct",
            },
        )
        assert response.status_code == 403
        mock_integrity_service.flag_student.assert_not_awaited()

    async def test_auto_only_trigger_rejected(self, professor_client, mock_integrity_service):
        """HIGH_REJECTION_RATE/SYSTEMATIC_CONTESTATION sont réservés à la génération automatique."""
        response = await professor_client.post(
            "/api/v1/integrity/alerts",
            json={
                "student_id": str(uuid.uuid4()),
                "trigger_type": "high_rejection_rate",
                "reason": "Tentative de contournement",
            },
        )
        assert response.status_code == 422
        mock_integrity_service.flag_student.assert_not_awaited()


@pytest.mark.anyio
async def test_create_privacy_request(student_client, mock_data_privacy_service):
    mock_data_privacy_service.submit_request.return_value = _make_data_privacy_request_read()
    response = await student_client.post(
        "/api/v1/privacy/requests", json={"request_type": "access_export"}
    )
    assert response.status_code == 201
    mock_data_privacy_service.submit_request.assert_awaited_once()


@pytest.mark.anyio
async def test_list_pending_privacy_requests(admin_client, mock_data_privacy_service):
    mock_data_privacy_service.list_pending_for_dpo.return_value = [_make_data_privacy_request_read()]
    response = await admin_client.get("/api/v1/privacy/requests/pending")
    assert response.status_code == 200
    mock_data_privacy_service.list_pending_for_dpo.assert_awaited_once()


@pytest.mark.anyio
async def test_get_privacy_request(admin_client, mock_data_privacy_service):
    mock_data_privacy_service.get_request.return_value = _make_data_privacy_request_read()
    request_id = uuid.uuid4()
    response = await admin_client.get(f"/api/v1/privacy/requests/{request_id}")
    assert response.status_code == 200
    mock_data_privacy_service.get_request.assert_awaited_once_with(request_id)


@pytest.mark.anyio
async def test_verify_privacy_request_identity(admin_client, mock_data_privacy_service):
    mock_data_privacy_service.verify_identity.return_value = _make_data_privacy_request_read()
    request_id = uuid.uuid4()
    response = await admin_client.post(
        f"/api/v1/privacy/requests/{request_id}/verify-identity",
        json={"verification_method": "email"},
    )
    assert response.status_code == 200
    mock_data_privacy_service.verify_identity.assert_awaited_once_with(
        request_id=request_id, verification_method="email"
    )


@pytest.mark.anyio
async def test_start_processing_privacy_request(admin_client, mock_data_privacy_service):
    mock_data_privacy_service.start_processing.return_value = _make_data_privacy_request_read()
    request_id = uuid.uuid4()
    response = await admin_client.post(f"/api/v1/privacy/requests/{request_id}/start-processing")
    assert response.status_code == 200
    mock_data_privacy_service.start_processing.assert_awaited_once()


@pytest.mark.anyio
async def test_complete_erasure_privacy_request(admin_client, mock_data_privacy_service):
    mock_data_privacy_service.complete_erasure.return_value = _make_data_privacy_request_read()
    request_id = uuid.uuid4()
    response = await admin_client.post(
        f"/api/v1/privacy/requests/{request_id}/complete-erasure",
        json={"resolution_detail": "full_deletion", "reason": None},
    )
    assert response.status_code == 200
    mock_data_privacy_service.complete_erasure.assert_awaited_once()


@pytest.mark.anyio
async def test_reject_privacy_request(admin_client, mock_data_privacy_service):
    mock_data_privacy_service.reject_request.return_value = _make_data_privacy_request_read()
    request_id = uuid.uuid4()
    response = await admin_client.post(
        f"/api/v1/privacy/requests/{request_id}/reject",
        json={"reason": "Demande incomplète"},
    )
    assert response.status_code == 200
    mock_data_privacy_service.reject_request.assert_awaited_once()
    call_kwargs = mock_data_privacy_service.reject_request.await_args.kwargs
    assert call_kwargs["request_id"] == request_id
    assert call_kwargs["reason"] == "Demande incomplète"


@pytest.mark.anyio
async def test_list_audit_logs(admin_client, mock_audit_service):
    mock_audit_service.list_logs.return_value = {
        "items": [_make_audit_log_read()],
        "next_cursor": None,
        "has_more": False,
    }
    response = await admin_client.get("/api/v1/admin/audit-logs")
    assert response.status_code == 200
    mock_audit_service.list_logs.assert_awaited_once()


@pytest.mark.anyio
async def test_list_audit_logs_requires_admin(student_client, mock_audit_service):
    response = await student_client.get("/api/v1/admin/audit-logs")
    assert response.status_code == 403


