import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import DuplicateIncidentError, IncidentNotFoundError
from app.domain.models.assessment.correction_arbitration import (
    ArbitrationStatus,
    ArbitrationVerdict,
    CorrectionArbitration,
)
from app.domain.models.assessment.submission_incident import (
    IncidentCategory,
    IncidentResolution,
    IncidentStatus,
    SubmissionIncident,
)
from app.services.arbitration_service import ArbitrationService


def _make_correction_arbitration(
    arb_id: uuid.UUID, extraction_id: uuid.UUID, professor_id: uuid.UUID
) -> CorrectionArbitration:
    now = datetime.now(timezone.utc)
    return CorrectionArbitration(
        id=arb_id,
        extraction_correction_id=extraction_id,
        status=ArbitrationStatus.RESOLVED,
        teacher_professor_id=professor_id,
        verdict=ArbitrationVerdict.ACCEPTED,
        comment="Ok",
        created_at=now,
        updated_at=now,
    )


def _make_incident(
    incident_id: uuid.UUID,
    exercise_id: uuid.UUID,
    student_id: uuid.UUID,
    reported_by: uuid.UUID,
    resolution: IncidentResolution | None = None,
) -> SubmissionIncident:
    now = datetime.now(timezone.utc)
    return SubmissionIncident(
        id=incident_id,
        exercise_id=exercise_id,
        student_id=student_id,
        reported_by_user_id=reported_by,
        parent_incident_id=None,
        category=IncidentCategory.TECHNICAL,
        incident_occurred_at=None,
        reason="Scan en panne",
        attachment_path=None,
        status=IncidentStatus.PENDING,
        resolution=resolution,
        resolved_by_professor_id=None,
        resolution_comment=None,
        resolved_at=None,
        extended_deadline=None,
        new_submission_id=None,
        created_at=now,
        updated_at=now,
    )


def _make_student(student_id: uuid.UUID) -> MagicMock:
    s = MagicMock()
    s.id = student_id
    s.first_name = "Alice"
    s.last_name = "Dupont"
    return s


def _make_storage_mock() -> MagicMock:
    storage = MagicMock()
    storage.generate_read_url.return_value = "https://storage.example.com/signed-crop"
    return storage


def _make_default_exercise_repo() -> AsyncMock:
    """
    exercise_title (audit espace professeur, clustering) : _to_incident_
    read()/list_pending_incidents_for_professor lisent désormais exercise.
    title via ce repo — un AsyncMock() nu renverrait un MagicMock pour
    .title (jamais un str), ce qui ferait échouer la validation Pydantic
    SubmissionIncidentRead.exercise_title dans TOUS les tests existants
    qui ne fournissent pas leur propre exercise_repo. Défaut sûr ici.
    """
    repo = AsyncMock()
    exercise = MagicMock()
    exercise.title = "Exercice"
    repo.get_by_id.return_value = exercise
    return repo


def _make_service(
    arbitration_repo=None,
    incident_repo=None,
    submission_repo=None,
    integrity_repo=None,
    user_repo=None,
    extraction_correction_repo=None,
    exercise_repo=None,
    storage_service=None,
) -> ArbitrationService:
    # Câblage teacher_arbitration_node (2026-08-18) — défaut get_by_id=None
    # pour que les tests EXISTANTS (qui ne connaissent rien de ce câblage)
    # n'exercent jamais la branche has_pending_for_submission/update_status/
    # process_arbitration_resolved.delay (qui tenterait un vrai appel Celery
    # non configuré dans ces tests unitaires) — seuls les tests dédiés à ce
    # câblage fournissent un extraction_correction_repo qui retourne un objet.
    default_extraction_repo = AsyncMock()
    default_extraction_repo.get_by_id.return_value = None

    return ArbitrationService(
        arbitration_repo or AsyncMock(),
        incident_repo or AsyncMock(),
        submission_repo or AsyncMock(),
        integrity_repo or AsyncMock(),
        user_repo or AsyncMock(),
        extraction_correction_repo or default_extraction_repo,
        exercise_repo or _make_default_exercise_repo(),
        storage_service=storage_service or _make_storage_mock(),
    )


@pytest.mark.anyio
async def test_resolve_correction_success():
    aid = uuid.uuid4()
    eid = uuid.uuid4()
    pid = uuid.uuid4()
    arbitration = _make_correction_arbitration(aid, eid, pid)

    arbitration_repo = AsyncMock()
    arbitration_repo.create_and_apply_verdict.return_value = arbitration

    user_repo = AsyncMock()
    teacher = MagicMock()
    teacher.first_name = "Alice"
    teacher.last_name = "Dupont"
    user_repo.get_by_id.return_value = teacher

    service = _make_service(arbitration_repo=arbitration_repo, user_repo=user_repo)
    result = await service.resolve_correction(eid, pid, "accepted", "Ok", None)

    assert result.id == aid
    assert result.teacher_full_name == "Alice Dupont"
    arbitration_repo.create_and_apply_verdict.assert_awaited_once_with(
        extraction_correction_id=eid,
        teacher_professor_id=pid,
        verdict="accepted",
        comment="Ok",
        claimed_correction=None,
    )


@pytest.mark.anyio
async def test_resolve_correction_teacher_unknown():
    aid = uuid.uuid4()
    eid = uuid.uuid4()
    pid = uuid.uuid4()
    arbitration = _make_correction_arbitration(aid, eid, pid)

    arbitration_repo = AsyncMock()
    arbitration_repo.create_and_apply_verdict.return_value = arbitration

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = None

    service = _make_service(arbitration_repo=arbitration_repo, user_repo=user_repo)
    result = await service.resolve_correction(eid, pid, "accepted", "Ok", None)

    assert result.teacher_full_name == "Unknown"


@pytest.mark.anyio
async def test_report_incident_success():
    iid = uuid.uuid4()
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    reporter = uuid.uuid4()
    incident = _make_incident(iid, eid, sid, reporter)

    incident_repo = AsyncMock()
    incident_repo.has_pending_incident.return_value = False
    incident_repo.create.return_value = incident

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(incident_repo=incident_repo, user_repo=user_repo)
    result = await service.report_incident(
        eid, sid, reporter, IncidentCategory.TECHNICAL, "Scan en panne", None, None
    )

    assert result.id == iid
    assert result.student_full_name == "Alice Dupont"
    incident_repo.has_pending_incident.assert_awaited_once_with(sid, eid)
    incident_repo.create.assert_awaited_once_with(
        exercise_id=eid,
        student_id=sid,
        reported_by_user_id=reporter,
        category=IncidentCategory.TECHNICAL,
        reason="Scan en panne",
        incident_occurred_at=None,
        attachment_path=None,
    )


@pytest.mark.anyio
async def test_report_incident_duplicate_raises():
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    reporter = uuid.uuid4()

    incident_repo = AsyncMock()
    incident_repo.has_pending_incident.return_value = True

    service = _make_service(incident_repo=incident_repo)
    with pytest.raises(DuplicateIncidentError):
        await service.report_incident(eid, sid, reporter, IncidentCategory.TECHNICAL, "Raison", None, None)
    incident_repo.create.assert_not_awaited()


@pytest.mark.anyio
async def test_detect_and_cluster_no_candidates():
    eid = uuid.uuid4()
    incident_repo = AsyncMock()
    incident_repo.detect_cluster_candidates.return_value = []

    service = _make_service(incident_repo=incident_repo)
    result = await service.detect_and_cluster(eid)

    assert result is None
    incident_repo.set_parent.assert_not_awaited()


@pytest.mark.anyio
async def test_detect_and_cluster_links_children():
    eid = uuid.uuid4()
    root_id = uuid.uuid4()
    child1 = uuid.uuid4()
    child2 = uuid.uuid4()

    incident_repo = AsyncMock()
    incident_repo.detect_cluster_candidates.return_value = [root_id, child1, child2]

    service = _make_service(incident_repo=incident_repo)
    result = await service.detect_and_cluster(eid)

    assert result == root_id
    incident_repo.set_parent.assert_any_await(child1, root_id)
    incident_repo.set_parent.assert_any_await(child2, root_id)


@pytest.mark.anyio
async def test_resolve_incident_not_found():
    iid = uuid.uuid4()
    incident_repo = AsyncMock()
    incident_repo.get_by_id.return_value = None

    service = _make_service(incident_repo=incident_repo)
    with pytest.raises(IncidentNotFoundError):
        await service.resolve_incident(iid, uuid.uuid4(), IncidentResolution.JUSTIFIED_ABSENCE, None)


@pytest.mark.anyio
async def test_resolve_incident_retry_granted_creates_new_submission():
    iid = uuid.uuid4()
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    reporter = uuid.uuid4()
    professor_id = uuid.uuid4()
    incident = _make_incident(iid, eid, sid, reporter)
    resolved = _make_incident(iid, eid, sid, reporter, resolution=IncidentResolution.RETRY_GRANTED)

    incident_repo = AsyncMock()
    incident_repo.get_by_id.return_value = incident
    incident_repo.resolve_single.return_value = resolved

    submission_repo = AsyncMock()
    submission_repo.get_next_attempt_number.return_value = 2
    mock_sub = MagicMock()
    mock_sub.id = uuid.uuid4()
    submission_repo.create.return_value = mock_sub
    resolved.new_submission_id = mock_sub.id

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(
        incident_repo=incident_repo, submission_repo=submission_repo, user_repo=user_repo
    )
    result = await service.resolve_incident(iid, professor_id, IncidentResolution.RETRY_GRANTED, None)

    assert result.new_submission_id == mock_sub.id
    submission_repo.get_next_attempt_number.assert_awaited_once_with(eid, sid)
    submission_repo.create.assert_awaited_once_with(eid, sid, 2)
    incident_repo.resolve_single.assert_awaited_once_with(
        incident_id=iid,
        resolution=IncidentResolution.RETRY_GRANTED,
        resolution_comment=None,
        resolved_by_professor_id=professor_id,
        requesting_professor_id=professor_id,
        extended_deadline=None,
        new_submission_id=mock_sub.id,
    )


@pytest.mark.anyio
async def test_resolve_incident_not_retry_no_new_submission():
    iid = uuid.uuid4()
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    reporter = uuid.uuid4()
    professor_id = uuid.uuid4()
    incident = _make_incident(iid, eid, sid, reporter)
    resolved = _make_incident(iid, eid, sid, reporter, resolution=IncidentResolution.JUSTIFIED_ABSENCE)

    incident_repo = AsyncMock()
    incident_repo.get_by_id.return_value = incident
    incident_repo.resolve_single.return_value = resolved

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(sid)

    service = _make_service(incident_repo=incident_repo, user_repo=user_repo)
    result = await service.resolve_incident(iid, professor_id, IncidentResolution.JUSTIFIED_ABSENCE, "Ok")

    assert result.resolution == IncidentResolution.JUSTIFIED_ABSENCE
    incident_repo.resolve_single.assert_awaited_once_with(
        incident_id=iid,
        resolution=IncidentResolution.JUSTIFIED_ABSENCE,
        resolution_comment="Ok",
        resolved_by_professor_id=professor_id,
        requesting_professor_id=professor_id,
        extended_deadline=None,
        new_submission_id=None,
    )


@pytest.mark.anyio
class TestResolveIncidentTriggersIntegrityCheck:
    """
    Bug corrigé (audit espace admin) : check_integrity() existait,
    correctement câblée vers IntegrityAlertRepository, mais aucun
    appelant ne l'invoquait jamais — HIGH_REJECTION_RATE ne pouvait
    jamais se déclencher malgré une implémentation complète.
    """

    async def test_rejected_resolution_checks_integrity(self):
        iid, eid, sid, reporter, professor_id = (uuid.uuid4() for _ in range(5))
        incident = _make_incident(iid, eid, sid, reporter)
        resolved = _make_incident(iid, eid, sid, reporter, resolution=IncidentResolution.REJECTED)

        incident_repo = AsyncMock()
        incident_repo.get_by_id.return_value = incident
        incident_repo.resolve_single.return_value = resolved
        incident_repo.get_rejection_ratio.return_value = Decimal("0.3")

        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = _make_student(sid)

        service = _make_service(incident_repo=incident_repo, user_repo=user_repo)
        await service.resolve_incident(iid, professor_id, IncidentResolution.REJECTED, "Non retenu")

        incident_repo.get_rejection_ratio.assert_awaited_once_with(sid)

    async def test_non_rejected_resolution_never_checks_integrity(self):
        """Seul un rejet peut faire monter le ratio — jamais appelé sur les 3 autres résolutions."""
        iid, eid, sid, reporter, professor_id = (uuid.uuid4() for _ in range(5))
        incident = _make_incident(iid, eid, sid, reporter)
        resolved = _make_incident(iid, eid, sid, reporter, resolution=IncidentResolution.JUSTIFIED_ABSENCE)

        incident_repo = AsyncMock()
        incident_repo.get_by_id.return_value = incident
        incident_repo.resolve_single.return_value = resolved

        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = _make_student(sid)

        service = _make_service(incident_repo=incident_repo, user_repo=user_repo)
        await service.resolve_incident(iid, professor_id, IncidentResolution.JUSTIFIED_ABSENCE, "Ok")

        incident_repo.get_rejection_ratio.assert_not_awaited()


@pytest.mark.anyio
async def test_resolve_incident_repo_returns_none_raises():
    iid = uuid.uuid4()
    eid = uuid.uuid4()
    sid = uuid.uuid4()
    reporter = uuid.uuid4()
    incident = _make_incident(iid, eid, sid, reporter)

    incident_repo = AsyncMock()
    incident_repo.get_by_id.return_value = incident
    incident_repo.resolve_single.return_value = None

    service = _make_service(incident_repo=incident_repo)
    with pytest.raises(IncidentNotFoundError):
        await service.resolve_incident(iid, uuid.uuid4(), IncidentResolution.JUSTIFIED_ABSENCE, None)


@pytest.mark.anyio
class TestResolveCluster:
    """
    Bug corrigé (audit espace professeur, en construisant l'UI de
    regroupement d'incidents) : resolve_cluster() déléguait auparavant à
    un simple UPDATE en masse qui ne créait JAMAIS de nouvelle Submission
    pour RETRY_GRANTED et ignorait silencieusement extended_deadline —
    corrigé en réutilisant resolve_single() une fois par membre du
    cluster, même logique que resolve_incident() (single).
    """

    async def test_deadline_extended_resolves_each_member_with_date(self):
        parent_id = uuid.uuid4()
        child_id = uuid.uuid4()
        eid = uuid.uuid4()
        sid1, sid2 = uuid.uuid4(), uuid.uuid4()
        reporter = uuid.uuid4()
        professor_id = uuid.uuid4()
        deadline = datetime(2024, 6, 5, tzinfo=timezone.utc)

        root = _make_incident(parent_id, eid, sid1, reporter)
        child = _make_incident(child_id, eid, sid2, reporter)

        incident_repo = AsyncMock()
        incident_repo.list_cluster_members.return_value = [root, child]
        incident_repo.resolve_single.side_effect = [
            _make_incident(parent_id, eid, sid1, reporter, resolution=IncidentResolution.DEADLINE_EXTENDED),
            _make_incident(child_id, eid, sid2, reporter, resolution=IncidentResolution.DEADLINE_EXTENDED),
        ]

        service = _make_service(incident_repo=incident_repo)
        result = await service.resolve_cluster(
            parent_id, professor_id, IncidentResolution.DEADLINE_EXTENDED, "Ok", extended_deadline=deadline,
        )

        assert result == 2
        incident_repo.list_cluster_members.assert_awaited_once_with(parent_id)
        assert incident_repo.resolve_single.await_count == 2
        for call in incident_repo.resolve_single.await_args_list:
            assert call.kwargs["extended_deadline"] == deadline
            assert call.kwargs["resolution"] == IncidentResolution.DEADLINE_EXTENDED
            assert call.kwargs["new_submission_id"] is None

    async def test_retry_granted_creates_new_submission_per_member(self):
        parent_id = uuid.uuid4()
        child_id = uuid.uuid4()
        eid = uuid.uuid4()
        sid1, sid2 = uuid.uuid4(), uuid.uuid4()
        reporter = uuid.uuid4()
        professor_id = uuid.uuid4()

        root = _make_incident(parent_id, eid, sid1, reporter)
        child = _make_incident(child_id, eid, sid2, reporter)

        incident_repo = AsyncMock()
        incident_repo.list_cluster_members.return_value = [root, child]
        incident_repo.resolve_single.side_effect = [
            _make_incident(parent_id, eid, sid1, reporter, resolution=IncidentResolution.RETRY_GRANTED),
            _make_incident(child_id, eid, sid2, reporter, resolution=IncidentResolution.RETRY_GRANTED),
        ]

        submission_repo = AsyncMock()
        submission_repo.get_next_attempt_number.return_value = 2
        new_sub_1, new_sub_2 = MagicMock(), MagicMock()
        new_sub_1.id, new_sub_2.id = uuid.uuid4(), uuid.uuid4()
        submission_repo.create.side_effect = [new_sub_1, new_sub_2]

        service = _make_service(incident_repo=incident_repo, submission_repo=submission_repo)
        result = await service.resolve_cluster(
            parent_id, professor_id, IncidentResolution.RETRY_GRANTED, None,
        )

        assert result == 2
        # Une nouvelle tentative RÉELLE par étudiant du cluster — le bug
        # corrigé aurait laissé submission_repo.create totalement inappelé.
        assert submission_repo.create.await_count == 2
        submission_repo.create.assert_any_await(eid, sid1, 2)
        submission_repo.create.assert_any_await(eid, sid2, 2)
        resolve_calls = incident_repo.resolve_single.await_args_list
        assert resolve_calls[0].kwargs["new_submission_id"] == new_sub_1.id
        assert resolve_calls[1].kwargs["new_submission_id"] == new_sub_2.id

    async def test_rejected_checks_integrity_per_unique_student(self):
        parent_id = uuid.uuid4()
        child_id = uuid.uuid4()
        eid = uuid.uuid4()
        sid1, sid2 = uuid.uuid4(), uuid.uuid4()
        reporter = uuid.uuid4()
        professor_id = uuid.uuid4()

        root = _make_incident(parent_id, eid, sid1, reporter)
        child = _make_incident(child_id, eid, sid2, reporter)

        incident_repo = AsyncMock()
        incident_repo.list_cluster_members.return_value = [root, child]
        incident_repo.resolve_single.side_effect = [
            _make_incident(parent_id, eid, sid1, reporter, resolution=IncidentResolution.REJECTED),
            _make_incident(child_id, eid, sid2, reporter, resolution=IncidentResolution.REJECTED),
        ]
        incident_repo.get_rejection_ratio.return_value = Decimal("0.2")

        service = _make_service(incident_repo=incident_repo)
        await service.resolve_cluster(parent_id, professor_id, IncidentResolution.REJECTED, None)

        assert incident_repo.get_rejection_ratio.await_count == 2
        checked_students = {call.args[0] for call in incident_repo.get_rejection_ratio.await_args_list}
        assert checked_students == {sid1, sid2}

    async def test_empty_cluster_raises_not_found(self):
        incident_repo = AsyncMock()
        incident_repo.list_cluster_members.return_value = []

        service = _make_service(incident_repo=incident_repo)
        with pytest.raises(IncidentNotFoundError):
            await service.resolve_cluster(
                uuid.uuid4(), uuid.uuid4(), IncidentResolution.JUSTIFIED_ABSENCE, None,
            )


@pytest.mark.anyio
async def test_check_integrity_below_threshold_no_alert():
    sid = uuid.uuid4()
    incident_repo = AsyncMock()
    incident_repo.get_rejection_ratio.return_value = Decimal("0.5")

    integrity_repo = AsyncMock()

    service = _make_service(incident_repo=incident_repo, integrity_repo=integrity_repo)
    result = await service.check_integrity(sid)

    assert result == Decimal("0.5")
    integrity_repo.create.assert_not_awaited()


@pytest.mark.anyio
async def test_check_integrity_above_threshold_creates_alert():
    sid = uuid.uuid4()
    incident_repo = AsyncMock()
    incident_repo.get_rejection_ratio.return_value = Decimal("0.8")

    integrity_repo = AsyncMock()

    service = _make_service(incident_repo=incident_repo, integrity_repo=integrity_repo)
    result = await service.check_integrity(sid)

    assert result == Decimal("0.8")
    integrity_repo.create.assert_awaited_once()
    call_kwargs = integrity_repo.create.await_args.kwargs
    assert call_kwargs["student_id"] == sid
    assert call_kwargs["auto_generated"] is True
    assert call_kwargs["evidence"]["rejection_ratio"] == 0.8


@pytest.mark.anyio
async def test_list_pending_corrections_for_professor_success():
    pid = uuid.uuid4()
    arb_id = uuid.uuid4()
    extraction_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    student_id = uuid.uuid4()
    exercise_id = uuid.uuid4()

    arbitration = _make_correction_arbitration(arb_id, extraction_id, pid)
    arbitration.status = ArbitrationStatus.PENDING

    arbitration_repo = AsyncMock()
    arbitration_repo.list_pending_for_professor.return_value = [arbitration]

    extraction = MagicMock()
    extraction.id = extraction_id
    extraction.submission_id = submission_id
    extraction.question_id = None
    extraction.prediction_ocr = "42"
    extraction.human_correction = "43"
    extraction.image_crop_path = "submissions/x/ocr_crops/page_1_block_1.png"
    extraction_repo = AsyncMock()
    extraction_repo.get_by_id.return_value = extraction

    submission = MagicMock()
    submission.id = submission_id
    submission.student_id = student_id
    submission.exercise_id = exercise_id
    submission_repo = AsyncMock()
    submission_repo.get_by_id.return_value = submission

    exercise = MagicMock()
    exercise.title = "Examen final"
    exercise_repo = AsyncMock()
    exercise_repo.get_by_id.return_value = exercise

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(student_id)

    service = _make_service(
        arbitration_repo=arbitration_repo,
        extraction_correction_repo=extraction_repo,
        submission_repo=submission_repo,
        exercise_repo=exercise_repo,
        user_repo=user_repo,
    )
    result = await service.list_pending_corrections_for_professor(pid)

    assert len(result) == 1
    assert result[0].arbitration_id == arb_id
    assert result[0].student_full_name == "Alice Dupont"
    assert result[0].exercise_title == "Examen final"
    assert result[0].image_crop_url is not None


@pytest.mark.anyio
async def test_list_pending_incidents_for_professor_success():
    pid = uuid.uuid4()
    exercise_id = uuid.uuid4()
    student_id = uuid.uuid4()
    incident = _make_incident(uuid.uuid4(), exercise_id, student_id, uuid.uuid4())

    incident_repo = AsyncMock()
    incident_repo.list_pending_for_professor.return_value = [incident]

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_student(student_id)

    service = _make_service(incident_repo=incident_repo, user_repo=user_repo)
    result = await service.list_pending_incidents_for_professor(pid)

    assert len(result) == 1
    assert result[0].student_full_name == "Alice Dupont"
    assert result[0].exercise_title == "Exercice"
    incident_repo.list_pending_for_professor.assert_awaited_once_with(pid)