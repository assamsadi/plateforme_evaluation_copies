import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_arbitration_service,
    get_current_professor,
    get_current_user,
)
from app.domain.models.identity.user import User, Professor
from app.domain.schemas.arbitration_schemas import (
    CorrectionArbitrationCreate,
    CorrectionArbitrationRead,
    PendingCorrectionArbitrationRead,
    SubmissionIncidentCreate,
    SubmissionIncidentRead,
    SubmissionIncidentResolutionRequest,
)
from app.services.arbitration_service import ArbitrationService

router = APIRouter(tags=["arbitration & incidents"])


@router.get("/arbitrations/corrections/pending", response_model=list[PendingCorrectionArbitrationRead])
async def list_pending_correction_arbitrations(
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Gap trouvé lors de l'audit arbitrage : /resolve exigeait déjà l'ID
    d'une correction AMBIGUË mais rien ne renvoyait ces ID en liste — le
    « Centre d'Arbitrage Professeur » n'avait aucune file de découverte.
    """
    return await arbitration_service.list_pending_corrections_for_professor(current_prof.id)


@router.get("/arbitrations/corrections/all", response_model=list[PendingCorrectionArbitrationRead])
async def list_all_correction_arbitrations(
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Traçabilité réelle (2026-09-06) : list_pending_correction_arbitrations
    ci-dessus n'expose QUE les PENDING — un étudiant entièrement traité
    disparaissait purement et simplement du tableau principal, sans plus
    aucun moyen d'accéder à son historique. Sert la liste principale
    (groupée par étudiant côté frontend, compteur "en attente" recalculé
    depuis status côté client).
    """
    return await arbitration_service.list_all_corrections_for_professor(current_prof.id)


@router.get(
    "/arbitrations/corrections/students/{student_id}",
    response_model=list[PendingCorrectionArbitrationRead],
)
async def list_correction_arbitrations_for_student(
    student_id: uuid.UUID,
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Historique COMPLET (PENDING + RESOLVED) des arbitrages d'un étudiant —
    traçabilité réelle (2026-09-06) : list_pending_correction_arbitrations
    ci-dessus n'expose QUE les PENDING par construction ; une fois résolue,
    une contestation y disparaît sans laisser de trace consultable. Utilisé
    par le détail étudiant du "Centre d'Arbitrage" pour garder visible ce
    qui a déjà été tranché (verdict, professeur), même après un rechargement.
    """
    return await arbitration_service.list_arbitrations_for_student(current_prof.id, student_id)


@router.post("/arbitrations/corrections/{extraction_correction_id}/resolve", response_model=CorrectionArbitrationRead)
async def resolve_extraction_correction(
    extraction_correction_id: uuid.UUID,
    schema: CorrectionArbitrationCreate,
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    return await arbitration_service.resolve_correction(
        extraction_correction_id=extraction_correction_id,
        teacher_professor_id=current_prof.id,
        verdict=schema.verdict.value if hasattr(schema.verdict, "value") else schema.verdict,
        comment=schema.comment,
        claimed_correction=None,
    )


@router.get("/incidents/pending", response_model=list[SubmissionIncidentRead])
async def list_pending_incidents(
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    """
    Gap trouvé lors de l'audit arbitrage — même constat que /arbitrations/
    corrections/pending : /incidents/{id}/resolve existait déjà, aucune
    file de découverte.
    """
    return await arbitration_service.list_pending_incidents_for_professor(current_prof.id)


@router.post("/incidents", response_model=SubmissionIncidentRead, status_code=status.HTTP_201_CREATED)
async def report_submission_incident(
    schema: SubmissionIncidentCreate,
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_user: Annotated[User, Depends(get_current_user)],
):
    return await arbitration_service.report_incident(
        exercise_id=schema.exercise_id,
        student_id=schema.student_id,
        reported_by_user_id=current_user.id,
        category=schema.category,
        reason=schema.reason,
        incident_occurred_at=schema.incident_occurred_at,
        attachment_path=schema.attachment_path,
    )


@router.post("/incidents/{incident_id}/resolve", response_model=SubmissionIncidentRead)
async def resolve_submission_incident(
    incident_id: uuid.UUID,
    schema: SubmissionIncidentResolutionRequest,
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    return await arbitration_service.resolve_incident(
        incident_id=incident_id,
        requesting_professor_id=current_prof.id,
        resolution=schema.resolution,
        comment=schema.resolution_comment,
        extended_deadline=schema.extended_deadline,
    )


@router.post("/exercises/{exercise_id}/incidents/cluster")
async def cluster_exercise_incidents(
    exercise_id: uuid.UUID,
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    root_id = await arbitration_service.detect_and_cluster(exercise_id)
    return {"root_incident_id": root_id}


@router.post("/incidents/clusters/{parent_incident_id}/resolve")
async def resolve_incident_cluster(
    parent_incident_id: uuid.UUID,
    schema: SubmissionIncidentResolutionRequest,
    arbitration_service: Annotated[ArbitrationService, Depends(get_arbitration_service)],
    current_prof: Annotated[Professor, Depends(get_current_professor)],
):
    count = await arbitration_service.resolve_cluster(
        parent_incident_id=parent_incident_id,
        requesting_professor_id=current_prof.id,
        resolution=schema.resolution,
        comment=schema.resolution_comment,
        extended_deadline=schema.extended_deadline,
    )
    return {"resolved_count": count}
