import uuid

import pytest

from app.domain.models.assessment.correction_arbitration import ArbitrationStatus, ArbitrationVerdict
from app.domain.models.assessment.submission_incident import IncidentCategory, IncidentResolution


def _make_correction_arbitration_read():
    return {
        "id": str(uuid.uuid4()),
        "extraction_correction_id": str(uuid.uuid4()),
        "status": ArbitrationStatus.RESOLVED.value,
        "teacher_professor_id": str(uuid.uuid4()),
        "teacher_full_name": "Bob Martin",
        "verdict": ArbitrationVerdict.ACCEPTED.value,
        "comment": "OK",
        "claimed_correction": "version tranchée par le professeur",
        "created_at": "2024-01-01T00:00:00Z",
    }


def _make_submission_incident_read():
    return {
        "id": str(uuid.uuid4()),
        "exercise_id": str(uuid.uuid4()),
        "exercise_title": "Examen final",
        "student_id": str(uuid.uuid4()),
        "student_full_name": "Alice Dupont",
        "reported_by_user_id": str(uuid.uuid4()),
        "parent_incident_id": None,
        "category": IncidentCategory.TECHNICAL.value,
        "incident_occurred_at": "2024-01-01T00:00:00Z",
        "reason": "Problème technique",
        "attachment_url": None,
        "status": "pending",
        "resolution": None,
        "resolution_comment": None,
        "resolved_by_professor_id": None,
        "resolved_at": None,
        "extended_deadline": None,
        "new_submission_id": None,
    }


def _make_pending_correction_arbitration_read():
    return {
        "arbitration_id": str(uuid.uuid4()),
        "extraction_correction_id": str(uuid.uuid4()),
        "submission_id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "student_full_name": "Alice Dupont",
        "exercise_id": str(uuid.uuid4()),
        "exercise_title": "Examen final",
        "question_id": None,
        "prediction_ocr": "42",
        "human_correction": "43",
        "image_crop_url": "https://storage.example.com/signed-crop",
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.mark.anyio
async def test_list_pending_correction_arbitrations(professor_client, mock_arbitration_service):
    mock_arbitration_service.list_pending_corrections_for_professor.return_value = [
        _make_pending_correction_arbitration_read()
    ]
    response = await professor_client.get("/api/v1/arbitrations/corrections/pending")
    assert response.status_code == 200
    mock_arbitration_service.list_pending_corrections_for_professor.assert_awaited_once_with(
        "00000000-0000-4000-a000-000000000002"
    )


@pytest.mark.anyio
async def test_list_pending_incidents(professor_client, mock_arbitration_service):
    mock_arbitration_service.list_pending_incidents_for_professor.return_value = [
        _make_submission_incident_read()
    ]
    response = await professor_client.get("/api/v1/incidents/pending")
    assert response.status_code == 200
    mock_arbitration_service.list_pending_incidents_for_professor.assert_awaited_once_with(
        "00000000-0000-4000-a000-000000000002"
    )


@pytest.mark.anyio
async def test_resolve_extraction_correction(professor_client, mock_arbitration_service):
    mock_arbitration_service.resolve_correction.return_value = _make_correction_arbitration_read()
    payload = {
        "verdict": ArbitrationVerdict.ACCEPTED.value,
        "comment": "OK",
    }
    response = await professor_client.post(
        f"/api/v1/arbitrations/corrections/{uuid.uuid4()}/resolve", json=payload
    )
    assert response.status_code == 200
    mock_arbitration_service.resolve_correction.assert_awaited_once()


@pytest.mark.anyio
async def test_resolve_extraction_correction_requires_professor(student_client, mock_arbitration_service):
    payload = {"verdict": ArbitrationVerdict.ACCEPTED.value, "comment": "OK"}
    response = await student_client.post(
        f"/api/v1/arbitrations/corrections/{uuid.uuid4()}/resolve", json=payload
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_report_submission_incident(admin_client, mock_arbitration_service):
    mock_arbitration_service.report_incident.return_value = _make_submission_incident_read()
    payload = {
        "exercise_id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "category": IncidentCategory.TECHNICAL.value,
        "reason": "Problème technique",
        "incident_occurred_at": "2024-01-01T00:00:00Z",
    }
    response = await admin_client.post("/api/v1/incidents", json=payload)
    assert response.status_code == 201
    mock_arbitration_service.report_incident.assert_awaited_once()


@pytest.mark.anyio
async def test_resolve_submission_incident(professor_client, mock_arbitration_service):
    mock_arbitration_service.resolve_incident.return_value = _make_submission_incident_read()
    payload = {
        "resolution": IncidentResolution.DEADLINE_EXTENDED.value,
        "resolution_comment": "Extension accordée",
        "extended_deadline": "2024-06-05T00:00:00Z",
    }
    response = await professor_client.post(f"/api/v1/incidents/{uuid.uuid4()}/resolve", json=payload)
    assert response.status_code == 200
    mock_arbitration_service.resolve_incident.assert_awaited_once()


@pytest.mark.anyio
async def test_cluster_exercise_incidents(professor_client, mock_arbitration_service):
    mock_arbitration_service.detect_and_cluster.return_value = uuid.uuid4()
    response = await professor_client.post(f"/api/v1/exercises/{uuid.uuid4()}/incidents/cluster")
    assert response.status_code == 200
    assert "root_incident_id" in response.json()
    mock_arbitration_service.detect_and_cluster.assert_awaited_once()


@pytest.mark.anyio
async def test_resolve_incident_cluster(professor_client, mock_arbitration_service):
    mock_arbitration_service.resolve_cluster.return_value = 3
    payload = {
        "resolution": IncidentResolution.JUSTIFIED_ABSENCE.value,
        "resolution_comment": "OK",
    }
    response = await professor_client.post(f"/api/v1/incidents/clusters/{uuid.uuid4()}/resolve", json=payload)
    assert response.status_code == 200
    assert response.json()["resolved_count"] == 3
    mock_arbitration_service.resolve_cluster.assert_awaited_once()


@pytest.mark.anyio
async def test_resolve_incident_cluster_deadline_extended_requires_date(
    professor_client, mock_arbitration_service,
):
    """
    Gap fermé (audit espace professeur) : extended_deadline était
    documenté comme requis pour une résolution DEADLINE_EXTENDED, mais
    rien ne l'imposait réellement — même bug que GradeAppealResolution
    Request, cf. nouveau model_validator sur SubmissionIncidentResolution
    Request. Couvre à la fois le chemin single (resolve_submission_
    incident) et cluster (ce test), le schéma étant partagé.
    """
    payload = {
        "resolution": IncidentResolution.DEADLINE_EXTENDED.value,
        "resolution_comment": "OK",
    }
    response = await professor_client.post(f"/api/v1/incidents/clusters/{uuid.uuid4()}/resolve", json=payload)
    assert response.status_code == 422
    mock_arbitration_service.resolve_cluster.assert_not_awaited()


@pytest.mark.anyio
async def test_resolve_incident_cluster_deadline_extended_with_date_succeeds(
    professor_client, mock_arbitration_service,
):
    mock_arbitration_service.resolve_cluster.return_value = 5
    payload = {
        "resolution": IncidentResolution.DEADLINE_EXTENDED.value,
        "resolution_comment": "OK",
        "extended_deadline": "2024-06-05T00:00:00Z",
    }
    response = await professor_client.post(f"/api/v1/incidents/clusters/{uuid.uuid4()}/resolve", json=payload)
    assert response.status_code == 200
    assert response.json()["resolved_count"] == 5
    mock_arbitration_service.resolve_cluster.assert_awaited_once()


def _make_solution_variant_read():
    return {
        "id": str(uuid.uuid4()),
        "question_id": str(uuid.uuid4()),
        "content": "Solution détaillée",
        "structured_content": None,
        "reasoning_summary": None,
        "source": "teacher_manual",
        "difficulty_level": "intermediaire",
        "is_reference": False,
        "status": "pending_validation",
        "validated_by_professor_id": None,
        "review_comment": None,
        "reasoning_steps": [],
    }


@pytest.mark.anyio
async def test_create_solution_variant(professor_client, mock_solution_variant_service):
    mock_solution_variant_service.create_variant.return_value = _make_solution_variant_read()
    payload = {
        "question_id": str(uuid.uuid4()),
        "content": "Solution détaillée",
        "source": "teacher_manual",
        "difficulty_level": "intermediaire",
        "is_reference": False,
        "reasoning_steps": [],
    }
    response = await professor_client.post("/api/v1/solution-variants", json=payload)
    assert response.status_code == 201
    mock_solution_variant_service.create_variant.assert_awaited_once()


@pytest.mark.anyio
async def test_validate_solution_variant(professor_client, mock_solution_variant_service):
    mock_solution_variant_service.validate_variant.return_value = _make_solution_variant_read()
    payload = {"status": "approved", "review_comment": "OK"}
    response = await professor_client.post(f"/api/v1/solution-variants/{uuid.uuid4()}/validate", json=payload)
    assert response.status_code == 200
    mock_solution_variant_service.validate_variant.assert_awaited_once()


@pytest.mark.anyio
async def test_get_reasoning_graph(admin_client, mock_solution_variant_service):
    mock_solution_variant_service.get_ordered_reasoning_graph.return_value = []
    response = await admin_client.get(f"/api/v1/solution-variants/{uuid.uuid4()}/reasoning-graph")
    assert response.status_code == 200
    mock_solution_variant_service.get_ordered_reasoning_graph.assert_awaited_once()


@pytest.mark.anyio
async def test_list_pending_clarifications(professor_client, mock_solution_variant_service):
    mock_solution_variant_service.list_pending_clarifications.return_value = []
    response = await professor_client.get("/api/v1/clarifications/pending")
    assert response.status_code == 200
    mock_solution_variant_service.list_pending_clarifications.assert_awaited_once()


@pytest.mark.anyio
async def test_answer_clarification(professor_client, mock_solution_variant_service):
    mock_solution_variant_service.answer_clarification.return_value = {
        "id": str(uuid.uuid4()),
        "variant_id": str(uuid.uuid4()),
        "related_entity_type": None,
        "related_entity_id": None,
        "unclear_content": "Passage flou",
        "agent_question": "Que signifie x?",
        "proposed_answer": None,
        "severity": "blocking",
        "status": "answered",
        "professor_answer": "Voici la réponse",
        "answered_by_professor_id": str(uuid.uuid4()),
        "answered_by_professor_name": "Bob Martin",
        "answered_at": "2024-01-01T00:00:00Z",
        "resulting_step_id": None,
        "created_at": "2024-01-01T00:00:00Z",
    }
    payload = {"professor_answer": "Voici la réponse"}
    response = await professor_client.post(f"/api/v1/clarifications/{uuid.uuid4()}/answer", json=payload)
    assert response.status_code == 200
    mock_solution_variant_service.answer_clarification.assert_awaited_once()


@pytest.mark.anyio
async def test_validate_alternative_answer_accepted(professor_client, mock_solution_variant_service):
    mock_solution_variant_service.validate_alternative_answer_clarification.return_value = {
        "id": str(uuid.uuid4()),
        "variant_id": None,
        "related_entity_type": "Question",
        "related_entity_id": str(uuid.uuid4()),
        "criterion_id": "crit-mda",
        "unclear_content": "Méthode alternative de l'étudiant.",
        "agent_question": "Une réponse alternative inédite... est-elle valide ?",
        "proposed_answer": "Valider cette réponse alternative comme correcte.",
        "severity": "blocking",
        "status": "answered",
        "professor_answer": "Validé comme réponse alternative légitime.",
        "answered_by_professor_id": str(uuid.uuid4()),
        "answered_by_professor_name": "Bob Martin",
        "answered_at": "2024-01-01T00:00:00Z",
        "resulting_step_id": None,
        "created_at": "2024-01-01T00:00:00Z",
    }
    payload = {"accepted": True}
    response = await professor_client.post(
        f"/api/v1/clarifications/{uuid.uuid4()}/validate-alternative-answer", json=payload,
    )
    assert response.status_code == 200
    assert response.json()["criterion_id"] == "crit-mda"
    mock_solution_variant_service.validate_alternative_answer_clarification.assert_awaited_once()