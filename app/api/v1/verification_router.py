import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_current_admin,
    get_current_user,
    get_data_privacy_service,
    get_integrity_service,
)
from app.core.exceptions import ForbiddenError
from app.domain.models.identity.user import User, UserRole
from app.domain.schemas.system_schemas import (
    DataPrivacyCompleteErasureRequest,
    DataPrivacyRejectRequest,
    DataPrivacyRequestCreate,
    DataPrivacyRequestRead,
    DataPrivacyVerifyIdentityRequest,
    IntegrityAlertRead,
    IntegrityAlertReviewRequest,
    IntegrityManualFlagCreate,
)
from app.services.data_privacy_service import DataPrivacyService
from app.services.integrity_service import IntegrityService

router = APIRouter(tags=["verification, integrity & privacy"])


@router.get("/integrity/alerts/unresolved", response_model=list[IntegrityAlertRead])
async def list_unresolved_integrity_alerts(
    integrity_service: Annotated[IntegrityService, Depends(get_integrity_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await integrity_service.list_pending()


@router.post("/integrity/alerts", response_model=IntegrityAlertRead, status_code=status.HTTP_201_CREATED)
async def flag_student_manually(
    schema: IntegrityManualFlagCreate,
    integrity_service: Annotated[IntegrityService, Depends(get_integrity_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    """
    Gap fermé (audit espace admin) : IntegrityService.flag_student()
    existait déjà, complète, mais restait totalement inatteignable —
    aucun endpoint ne l'exposait. Réservé professeur/admin (cf. docstring
    module integrity_service.py, "levée par un professeur ou admin"),
    jamais un étudiant.
    """
    if current_user.role not in (UserRole.PROFESSOR, UserRole.ADMIN):
        raise ForbiddenError("Le signalement d'intégrité est réservé aux professeurs et administrateurs.")

    return await integrity_service.flag_student(
        student_id=schema.student_id,
        trigger_type=schema.trigger_type,
        reason=schema.reason,
        evidence=schema.evidence,
        auto_generated=False,
    )


@router.post("/integrity/alerts/{alert_id}/resolve", response_model=IntegrityAlertRead)
async def resolve_integrity_alert(
    alert_id: uuid.UUID,
    schema: IntegrityAlertReviewRequest,
    integrity_service: Annotated[IntegrityService, Depends(get_integrity_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await integrity_service.review_alert(
        alert_id=alert_id,
        reviewed_by_user_id=current_admin.id,
        status=schema.status,
        action_taken=schema.action_taken,
        review_notes=schema.review_notes,
    )


@router.post("/privacy/requests", response_model=DataPrivacyRequestRead, status_code=status.HTTP_201_CREATED)
async def create_privacy_request(
    schema: DataPrivacyRequestCreate,
    data_privacy_service: Annotated[DataPrivacyService, Depends(get_data_privacy_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await data_privacy_service.submit_request(
        user_id=current_user.id,
        request_type=schema.request_type,
    )


@router.get("/privacy/requests/pending", response_model=list[DataPrivacyRequestRead])
async def list_pending_privacy_requests(
    data_privacy_service: Annotated[DataPrivacyService, Depends(get_data_privacy_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await data_privacy_service.list_pending_for_dpo()


@router.get("/privacy/requests/{request_id}", response_model=DataPrivacyRequestRead)
async def get_privacy_request(
    request_id: uuid.UUID,
    data_privacy_service: Annotated[DataPrivacyService, Depends(get_data_privacy_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await data_privacy_service.get_request(request_id)


@router.post("/privacy/requests/{request_id}/verify-identity", response_model=DataPrivacyRequestRead)
async def verify_privacy_request_identity(
    request_id: uuid.UUID,
    schema: DataPrivacyVerifyIdentityRequest,
    data_privacy_service: Annotated[DataPrivacyService, Depends(get_data_privacy_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await data_privacy_service.verify_identity(
        request_id=request_id,
        verification_method=schema.verification_method,
    )


@router.post("/privacy/requests/{request_id}/start-processing", response_model=DataPrivacyRequestRead)
async def start_processing_privacy_request(
    request_id: uuid.UUID,
    data_privacy_service: Annotated[DataPrivacyService, Depends(get_data_privacy_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await data_privacy_service.start_processing(
        request_id=request_id,
        processor_id=current_admin.id,
    )


@router.post("/privacy/requests/{request_id}/complete-erasure", response_model=DataPrivacyRequestRead)
async def complete_erasure_privacy_request(
    request_id: uuid.UUID,
    schema: DataPrivacyCompleteErasureRequest,
    data_privacy_service: Annotated[DataPrivacyService, Depends(get_data_privacy_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await data_privacy_service.complete_erasure(
        request_id=request_id,
        resolution_detail=schema.resolution_detail,
        reason=schema.reason,
    )


@router.post("/privacy/requests/{request_id}/reject", response_model=DataPrivacyRequestRead)
async def reject_privacy_request(
    request_id: uuid.UUID,
    schema: DataPrivacyRejectRequest,
    data_privacy_service: Annotated[DataPrivacyService, Depends(get_data_privacy_service)],
    current_admin: Annotated[User, Depends(get_current_admin)],
):
    return await data_privacy_service.reject_request(
        request_id=request_id,
        processor_id=current_admin.id,
        reason=schema.reason,
    )


