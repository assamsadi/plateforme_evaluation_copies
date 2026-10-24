import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import RequestNotFoundError
from app.domain.models.system_infrastructure.data_privacy_request import (
    DataPrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    PrivacyResolutionDetail,
)
from app.domain.repositories.pagination import CursorPage
from app.infra_services.storage_service import StorageContainer
from app.services.data_privacy_service import DataPrivacyService


def _make_request(
    request_id: uuid.UUID,
    user_id: uuid.UUID,
    request_type: PrivacyRequestType = PrivacyRequestType.ACCESS_EXPORT,
) -> DataPrivacyRequest:
    now = datetime.now(timezone.utc)
    return DataPrivacyRequest(
        id=request_id,
        user_id=user_id,
        request_type=request_type,
        status=PrivacyRequestStatus.PENDING,
        legal_deadline=now + timedelta(days=30),
        identity_verified=False,
        verification_method=None,
        processed_by_user_id=None,
        processed_at=None,
        resolution_detail=None,
        retention_or_rejection_reason=None,
        export_file_path=None,
        export_file_expires_at=None,
        created_at=now,
        updated_at=now,
    )


def _make_service(privacy_repo=None, storage=None, user_repo=None) -> DataPrivacyService:
    if user_repo is None:
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = None
    return DataPrivacyService(
        privacy_repo or AsyncMock(),
        storage or AsyncMock(),
        user_repo,
    )


@pytest.mark.anyio
async def test_submit_request_success():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    request = _make_request(rid, uid, request_type=PrivacyRequestType.ERASURE)

    privacy_repo = AsyncMock()
    privacy_repo.create.return_value = request

    service = _make_service(privacy_repo=privacy_repo)
    result = await service.submit_request(uid, PrivacyRequestType.ERASURE)

    assert result.id == rid
    assert result.request_type == PrivacyRequestType.ERASURE
    assert result.status == PrivacyRequestStatus.PENDING
    privacy_repo.create.assert_awaited_once_with(user_id=uid, request_type=PrivacyRequestType.ERASURE)


@pytest.mark.anyio
async def test_verify_identity_success():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    request = _make_request(rid, uid)
    request.identity_verified = True
    request.verification_method = "email"

    privacy_repo = AsyncMock()
    privacy_repo.verify_identity.return_value = request

    service = _make_service(privacy_repo=privacy_repo)
    result = await service.verify_identity(rid, "email")

    assert result.identity_verified is True
    # DataPrivacyRequestRead n'expose pas verification_method (champ interne)
    privacy_repo.verify_identity.assert_awaited_once_with(
        request_id=rid, verification_method="email"
    )


@pytest.mark.anyio
async def test_verify_identity_not_found():
    rid = uuid.uuid4()
    privacy_repo = AsyncMock()
    privacy_repo.verify_identity.return_value = None

    service = _make_service(privacy_repo=privacy_repo)
    with pytest.raises(RequestNotFoundError):
        await service.verify_identity(rid, "email")


@pytest.mark.anyio
async def test_start_processing_success():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    processor = uuid.uuid4()
    request = _make_request(rid, uid)
    request.status = PrivacyRequestStatus.IN_PROGRESS
    request.processed_by_user_id = processor

    privacy_repo = AsyncMock()
    privacy_repo.start_processing.return_value = request

    service = _make_service(privacy_repo=privacy_repo)
    result = await service.start_processing(rid, processor)

    assert result.status == PrivacyRequestStatus.IN_PROGRESS
    assert result.processed_by_user_id == processor
    privacy_repo.start_processing.assert_awaited_once_with(
        request_id=rid, processor_id=processor
    )


@pytest.mark.anyio
async def test_start_processing_not_found():
    rid = uuid.uuid4()
    privacy_repo = AsyncMock()
    privacy_repo.start_processing.return_value = None

    service = _make_service(privacy_repo=privacy_repo)
    with pytest.raises(RequestNotFoundError):
        await service.start_processing(rid, uuid.uuid4())


@pytest.mark.anyio
class TestCompleteErasure:
    """
    Bug corrigé (audit espace admin) : complete_erasure ne modifiait
    jamais aucune donnée réelle de l'utilisateur, quel que soit
    resolution_detail — cf. docstring service. FULL_DELETION et
    PSEUDONYMIZED doivent désormais tous deux anonymiser réellement le
    compte (jamais le supprimer, cf. politique actée cette session).
    """

    async def test_pseudonymized_anonymizes_and_deactivates_user(self):
        rid = uuid.uuid4()
        uid = uuid.uuid4()
        request = _make_request(rid, uid, request_type=PrivacyRequestType.ERASURE)
        request.status = PrivacyRequestStatus.COMPLETED
        request.resolution_detail = PrivacyResolutionDetail.PSEUDONYMIZED
        request.retention_or_rejection_reason = "Obligation légale de rétention"

        privacy_repo = AsyncMock()
        privacy_repo.complete.return_value = request

        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = None

        service = _make_service(privacy_repo=privacy_repo, user_repo=user_repo)
        result = await service.complete_erasure(
            rid, PrivacyResolutionDetail.PSEUDONYMIZED, "Obligation légale de rétention"
        )

        assert result.status == PrivacyRequestStatus.COMPLETED
        assert result.resolution_detail == PrivacyResolutionDetail.PSEUDONYMIZED
        privacy_repo.complete.assert_awaited_once_with(
            request_id=rid,
            resolution_detail=PrivacyResolutionDetail.PSEUDONYMIZED,
            reason="Obligation légale de rétention",
        )
        user_repo.update.assert_awaited_once_with(
            uid,
            first_name="Utilisateur",
            last_name="anonymisé",
            email=f"anonymise-{rid}@rgpd.local",
            is_active=False,
        )

    async def test_full_deletion_gets_identical_real_treatment(self):
        """FULL_DELETION != suppression physique — même anonymisation réelle que PSEUDONYMIZED, jamais une ligne User supprimée."""
        rid = uuid.uuid4()
        uid = uuid.uuid4()
        request = _make_request(rid, uid, request_type=PrivacyRequestType.ERASURE)
        request.status = PrivacyRequestStatus.COMPLETED
        request.resolution_detail = PrivacyResolutionDetail.FULL_DELETION

        privacy_repo = AsyncMock()
        privacy_repo.complete.return_value = request

        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = None

        service = _make_service(privacy_repo=privacy_repo, user_repo=user_repo)
        await service.complete_erasure(rid, PrivacyResolutionDetail.FULL_DELETION, None)

        user_repo.update.assert_awaited_once_with(
            uid,
            first_name="Utilisateur",
            last_name="anonymisé",
            email=f"anonymise-{rid}@rgpd.local",
            is_active=False,
        )

    async def test_partial_retention_legal_does_not_touch_user(self):
        """Sémantique non écrite ailleurs dans le code — aucun comportement inventé, jamais d'anonymisation arbitraire."""
        rid = uuid.uuid4()
        uid = uuid.uuid4()
        request = _make_request(rid, uid, request_type=PrivacyRequestType.ERASURE)
        request.status = PrivacyRequestStatus.COMPLETED
        request.resolution_detail = PrivacyResolutionDetail.PARTIAL_RETENTION_LEGAL

        privacy_repo = AsyncMock()
        privacy_repo.complete.return_value = request
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = None

        service = _make_service(privacy_repo=privacy_repo, user_repo=user_repo)
        await service.complete_erasure(rid, PrivacyResolutionDetail.PARTIAL_RETENTION_LEGAL, "Partiel")

        user_repo.update.assert_not_awaited()

    @pytest.mark.parametrize(
        "resolution_detail",
        [PrivacyResolutionDetail.PROCESSING_RESTRICTED, PrivacyResolutionDetail.OBJECTION_UPHELD],
    )
    async def test_restriction_and_objection_do_not_touch_user(self, resolution_detail):
        """
        Bug corrigé (audit espace admin, migration c0d1e2f3a4b5) : RESTRICTION
        et OBJECTION n'avaient aucune résolution correspondante avant —
        purs enregistrements documentaires, aucune infrastructure de gel
        du traitement n'existe ailleurs à déclencher.
        """
        rid = uuid.uuid4()
        uid = uuid.uuid4()
        request = _make_request(rid, uid)
        request.status = PrivacyRequestStatus.COMPLETED
        request.resolution_detail = resolution_detail

        privacy_repo = AsyncMock()
        privacy_repo.complete.return_value = request
        user_repo = AsyncMock()
        user_repo.get_by_id.return_value = None

        service = _make_service(privacy_repo=privacy_repo, user_repo=user_repo)
        await service.complete_erasure(rid, resolution_detail, "Détail documenté")

        user_repo.update.assert_not_awaited()

    async def test_not_found_raises(self):
        rid = uuid.uuid4()
        privacy_repo = AsyncMock()
        privacy_repo.complete.return_value = None

        service = _make_service(privacy_repo=privacy_repo)
        with pytest.raises(RequestNotFoundError):
            await service.complete_erasure(rid, PrivacyResolutionDetail.FULL_DELETION, None)


@pytest.mark.anyio
async def test_complete_export_sets_expiry_and_url():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    request = _make_request(rid, uid)
    request.status = PrivacyRequestStatus.COMPLETED
    request.resolution_detail = PrivacyResolutionDetail.EXPORTED
    request.export_file_path = "exports/data.zip"
    request.export_file_expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    privacy_repo = AsyncMock()
    privacy_repo.complete.return_value = request

    storage = MagicMock()
    storage.generate_read_url.return_value = "https://blob.example.com/exports/data.zip"

    service = _make_service(privacy_repo=privacy_repo, storage=storage)
    result = await service.complete_export(rid, "exports/data.zip")

    assert result.export_file_url == "https://blob.example.com/exports/data.zip"
    assert result.resolution_detail == PrivacyResolutionDetail.EXPORTED
    # L'expiration doit être fixée à J+7 (EXPORT_LINK_VALIDITY_DAYS)
    call_kwargs = privacy_repo.complete.await_args.kwargs
    assert call_kwargs["resolution_detail"] == PrivacyResolutionDetail.EXPORTED
    assert call_kwargs["export_file_path"] == "exports/data.zip"
    assert call_kwargs["export_file_expires_at"] is not None
    storage.generate_read_url.assert_called_once_with(StorageContainer.SUBMISSIONS, "exports/data.zip")


@pytest.mark.anyio
async def test_complete_export_no_url_when_no_path():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    request = _make_request(rid, uid)
    request.status = PrivacyRequestStatus.COMPLETED
    request.resolution_detail = PrivacyResolutionDetail.EXPORTED
    request.export_file_path = None

    privacy_repo = AsyncMock()
    privacy_repo.complete.return_value = request

    service = _make_service(privacy_repo=privacy_repo)
    result = await service.complete_export(rid, "exports/data.zip")

    assert result.export_file_url is None


@pytest.mark.anyio
async def test_reject_request_success():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    processor = uuid.uuid4()
    request = _make_request(rid, uid)
    request.status = PrivacyRequestStatus.REJECTED
    request.resolution_detail = PrivacyResolutionDetail.REJECTED
    request.retention_or_rejection_reason = "Demande incomplète"

    privacy_repo = AsyncMock()
    privacy_repo.reject.return_value = request

    service = _make_service(privacy_repo=privacy_repo)
    result = await service.reject_request(rid, processor, "Demande incomplète")

    assert result.status == PrivacyRequestStatus.REJECTED
    privacy_repo.reject.assert_awaited_once_with(
        request_id=rid, processor_id=processor, reason="Demande incomplète"
    )


@pytest.mark.anyio
async def test_reject_request_not_found():
    rid = uuid.uuid4()
    privacy_repo = AsyncMock()
    privacy_repo.reject.return_value = None

    service = _make_service(privacy_repo=privacy_repo)
    with pytest.raises(RequestNotFoundError):
        await service.reject_request(rid, uuid.uuid4(), "Raison")


@pytest.mark.anyio
async def test_list_pending_for_dpo_success():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    request = _make_request(rid, uid)
    page = CursorPage(items=[request], next_cursor=None, has_more=False)

    privacy_repo = AsyncMock()
    privacy_repo.list_pending.return_value = page

    service = _make_service(privacy_repo=privacy_repo)
    result = await service.list_pending_for_dpo()

    assert len(result) == 1
    assert result[0].id == rid
    privacy_repo.list_pending.assert_awaited_once_with(limit=500)


@pytest.mark.anyio
async def test_list_approaching_deadline_success():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    request = _make_request(rid, uid)

    privacy_repo = AsyncMock()
    privacy_repo.list_approaching_deadline.return_value = [request]

    service = _make_service(privacy_repo=privacy_repo)
    result = await service.list_approaching_deadline(threshold_days=5)

    assert len(result) == 1
    privacy_repo.list_approaching_deadline.assert_awaited_once_with(threshold_days=5)


@pytest.mark.anyio
async def test_list_by_user_success():
    rid = uuid.uuid4()
    uid = uuid.uuid4()
    request = _make_request(rid, uid)
    page = CursorPage(items=[request], next_cursor=None, has_more=False)

    privacy_repo = AsyncMock()
    privacy_repo.list_by_user.return_value = page

    service = _make_service(privacy_repo=privacy_repo)
    result = await service.list_by_user(uid)

    assert len(result) == 1
    privacy_repo.list_by_user.assert_awaited_once_with(user_id=uid, limit=500)