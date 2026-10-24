"""
Service gérant les arbitrages de correction et les incidents de soumission.

Règles métier appliquées :
1. Un professeur ne peut résoudre un arbitrage ou un incident que si l'exercice lui appartient
   (vérifié par le repository).
2. Pour éviter les doublons de rapports d'incidents, le système vérifie s'il y a déjà
   un incident PENDING pour le même exercice et étudiant (DuplicateIncidentError).
3. Le système regroupe (cluster) automatiquement les incidents techniques multiples 
   pour un même exercice.
4. Si un incident est résolu par RETRY_GRANTED, le service génère automatiquement
   une nouvelle tentative pour l'étudiant (rattrapage automatique, jamais d'Exercise séparé).
5. Un seuil de rejet (> 60%) déclenche une alerte d'intégrité automatique.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.core.exceptions import DuplicateIncidentError, IncidentNotFoundError
from app.domain.models.assessment.correction_arbitration import CorrectionArbitration
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.models.assessment.submission_incident import (
    IncidentCategory,
    IncidentResolution,
    SubmissionIncident,
)
from app.domain.repositories.correction_arbitration_repository import (
    CorrectionArbitrationRepositoryProtocol,
)
from app.domain.repositories.exercise_repository import ExerciseRepositoryProtocol
from app.domain.repositories.extraction_correction_repository import (
    ExtractionCorrectionRepositoryProtocol,
)
from app.domain.repositories.integrity_alert_repository import IntegrityAlertRepositoryProtocol
from app.domain.repositories.submission_incident_repository import (
    SubmissionIncidentRepositoryProtocol,
    UnauthorizedIncidentAccessError,
)
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.domain.schemas.arbitration_schemas import (
    CorrectionArbitrationRead,
    PendingCorrectionArbitrationRead,
    SubmissionIncidentRead,
)
from app.infra_services.storage_service import StorageContainer, StorageService
from app.tasks.arbitration_tasks import process_arbitration_resolved

INTEGRITY_REJECTION_THRESHOLD = Decimal("0.6")


class ArbitrationServiceProtocol(Protocol):
    async def resolve_correction(
        self,
        extraction_correction_id: uuid.UUID,
        teacher_professor_id: uuid.UUID,
        verdict: str,
        comment: str | None,
        claimed_correction: str | None,
    ) -> CorrectionArbitrationRead: ...

    async def report_incident(
        self,
        exercise_id: uuid.UUID,
        student_id: uuid.UUID,
        reported_by_user_id: uuid.UUID,
        category: IncidentCategory,
        reason: str,
        incident_occurred_at: datetime | None,
        attachment_path: str | None,
    ) -> SubmissionIncidentRead: ...

    async def detect_and_cluster(self, exercise_id: uuid.UUID) -> uuid.UUID | None: ...

    async def resolve_incident(
        self,
        incident_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolution: IncidentResolution,
        comment: str | None,
        extended_deadline: datetime | None = None,
    ) -> SubmissionIncidentRead: ...

    async def resolve_cluster(
        self,
        parent_incident_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolution: IncidentResolution,
        comment: str | None,
        extended_deadline: datetime | None = None,
    ) -> int: ...

    async def check_integrity(self, student_id: uuid.UUID) -> Decimal: ...

    async def list_pending_corrections_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[PendingCorrectionArbitrationRead]: ...

    async def list_all_corrections_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[PendingCorrectionArbitrationRead]: ...

    async def list_arbitrations_for_student(
        self, professor_id: uuid.UUID, student_id: uuid.UUID
    ) -> list[PendingCorrectionArbitrationRead]: ...

    async def list_pending_incidents_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[SubmissionIncidentRead]: ...


class ArbitrationService:
    def __init__(
        self,
        arbitration_repo: CorrectionArbitrationRepositoryProtocol,
        incident_repo: SubmissionIncidentRepositoryProtocol,
        submission_repo: SubmissionRepositoryProtocol,
        integrity_repo: IntegrityAlertRepositoryProtocol,
        user_repo: UserRepositoryProtocol,
        # Câblage teacher_arbitration_node (2026-08-18) — requis uniquement
        # par resolve_correction() pour retrouver le submission_id à partir
        # de extraction_correction_id (CorrectionArbitration ne le porte pas
        # directement), cf. son docstring.
        extraction_correction_repo: ExtractionCorrectionRepositoryProtocol,
        # Câblage file de découverte (audit arbitrage) — requis pour
        # list_pending_corrections_for_professor (titre de l'exercice).
        exercise_repo: ExerciseRepositoryProtocol,
        storage_service: StorageService | None = None,
    ) -> None:
        self._arbitration_repo = arbitration_repo
        self._incident_repo = incident_repo
        self._submission_repo = submission_repo
        self._integrity_repo = integrity_repo
        self._user_repo = user_repo
        self._extraction_correction_repo = extraction_correction_repo
        self._exercises = exercise_repo
        self._storage = storage_service or StorageService()

    async def resolve_correction(
        self,
        extraction_correction_id: uuid.UUID,
        teacher_professor_id: uuid.UUID,
        verdict: str,
        comment: str | None,
        claimed_correction: str | None,
    ) -> CorrectionArbitrationRead:
        arbitration = await self._arbitration_repo.create_and_apply_verdict(
            extraction_correction_id=extraction_correction_id,
            teacher_professor_id=teacher_professor_id,
            verdict=verdict,
            comment=comment,
            claimed_correction=claimed_correction,
        )
        teacher = await self._user_repo.get_by_id(teacher_professor_id)
        arbitration.teacher_full_name = (
            f"{teacher.first_name} {teacher.last_name}" if teacher else "Unknown"
        )

        # Câblage teacher_arbitration_node (2026-08-18) — jusqu'ici, rien ne
        # débloquait jamais la soumission après une résolution d'arbitrage
        # (trou d'architecture confirmé par test réel, cf. tests/integration/
        # test_arbitration_service_e2e.py). Une soumission peut porter
        # PLUSIEURS ExtractionCorrection AMBIGUËS simultanément — on ne
        # débloque QUE quand PLUS AUCUNE ne reste PENDING (has_pending_for_
        # submission, jamais dès la première résolue). extraction absent
        # (ne devrait pas arriver, l'id vient de create_and_apply_verdict
        # qui vient de le lire) -> silencieux, jamais une exception qui
        # ferait échouer une résolution par ailleurs réussie.
        extraction = await self._extraction_correction_repo.get_by_id(extraction_correction_id)
        if extraction is not None:
            still_pending = await self._arbitration_repo.has_pending_for_submission(
                extraction.submission_id
            )
            if not still_pending:
                await self._submission_repo.update_status(
                    extraction.submission_id, SubmissionStatus.PENDING_EVALUATION
                )
                # .delay() jamais awaité directement : reprendrait tout le
                # graph (comparative_evaluation_node -> ... -> feedback_node,
                # plusieurs appels LLM réels) DANS le cycle requête/réponse
                # HTTP de cet endpoint — même discipline que extraction_
                # service.contest_extraction (process_contestation_
                # verification.delay(...)), jamais un awaited direct ici.
                process_arbitration_resolved.delay(submission_id=str(extraction.submission_id))

        return CorrectionArbitrationRead.model_validate(arbitration)

    async def _to_incident_read(self, incident: SubmissionIncident) -> SubmissionIncidentRead:
        """
        Enrichit et sérialise UN incident — student_full_name/attachment_url
        (déjà en place) + exercise_title (ajouté pour l'UI de regroupement
        par exercice, cf. audit espace professeur). Pas de batching ici
        volontairement (mono-incident) — list_pending_incidents_for_
        professor batch séparément pour éviter le N+1 sur une vraie liste.
        """
        student = await self._user_repo.get_by_id(incident.student_id)
        incident.student_full_name = (
            f"{student.first_name} {student.last_name}" if student else "Unknown"
        )
        exercise = await self._exercises.get_by_id(incident.exercise_id)
        incident.exercise_title = exercise.title if exercise else "Unknown"
        incident.attachment_url = incident.attachment_path
        return SubmissionIncidentRead.model_validate(incident)

    async def report_incident(
        self,
        exercise_id: uuid.UUID,
        student_id: uuid.UUID,
        reported_by_user_id: uuid.UUID,
        category: IncidentCategory,
        reason: str,
        incident_occurred_at: datetime | None,
        attachment_path: str | None,
    ) -> SubmissionIncidentRead:
        has_pending = await self._incident_repo.has_pending_incident(student_id, exercise_id)
        if has_pending:
            raise DuplicateIncidentError(student_id, exercise_id)

        incident = await self._incident_repo.create(
            exercise_id=exercise_id,
            student_id=student_id,
            reported_by_user_id=reported_by_user_id,
            category=category,
            reason=reason,
            incident_occurred_at=incident_occurred_at,
            attachment_path=attachment_path,
        )
        return await self._to_incident_read(incident)

    async def detect_and_cluster(self, exercise_id: uuid.UUID) -> uuid.UUID | None:
        candidates = await self._incident_repo.detect_cluster_candidates(exercise_id)
        if not candidates:
            return None
        
        root_id = candidates[0]
        for incident_id in candidates[1:]:
            await self._incident_repo.set_parent(incident_id, root_id)

        return root_id

    async def resolve_incident(
        self,
        incident_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolution: IncidentResolution,
        comment: str | None,
        extended_deadline: datetime | None = None,
    ) -> SubmissionIncidentRead:
        incident = await self._incident_repo.get_by_id(incident_id)
        if not incident:
            raise IncidentNotFoundError(incident_id)

        new_submission_id = None
        if resolution == IncidentResolution.RETRY_GRANTED:
            attempt_number = await self._submission_repo.get_next_attempt_number(
                incident.exercise_id, incident.student_id
            )
            new_sub = await self._submission_repo.create(
                incident.exercise_id, incident.student_id, attempt_number
            )
            new_submission_id = new_sub.id

        resolved_incident = await self._incident_repo.resolve_single(
            incident_id=incident_id,
            resolution=resolution,
            resolution_comment=comment,
            resolved_by_professor_id=requesting_professor_id,
            requesting_professor_id=requesting_professor_id,
            extended_deadline=extended_deadline,
            new_submission_id=new_submission_id,
        )

        if not resolved_incident:
            raise IncidentNotFoundError(incident_id)

        # Bug corrigé (audit espace admin) : check_integrity() existait,
        # câblée correctement vers IntegrityAlertRepository, mais AUCUN
        # appelant ne l'invoquait nulle part — HIGH_REJECTION_RATE ne
        # pouvait jamais se déclencher malgré une implémentation complète.
        # Seul un rejet fait potentiellement monter le ratio (num/dénom
        # augmentent tous les deux sur toute autre résolution, jamais
        # seulement le numérateur) — jamais appelé pour rien sur les 3
        # autres résolutions.
        if resolution == IncidentResolution.REJECTED:
            await self.check_integrity(resolved_incident.student_id)

        return await self._to_incident_read(resolved_incident)

    async def resolve_cluster(
        self,
        parent_incident_id: uuid.UUID,
        requesting_professor_id: uuid.UUID,
        resolution: IncidentResolution,
        comment: str | None,
        extended_deadline: datetime | None = None,
    ) -> int:
        """
        Bug corrigé (audit espace professeur, en construisant l'UI de
        regroupement d'incidents) : cette méthode déléguait à un simple
        UPDATE en masse (incident_repo.resolve_cluster, retiré) qui ne
        posait QUE status/resolution/resolution_comment sur chaque ligne —
        jamais extended_deadline (silencieusement ignoré, alors que le
        schéma HTTP l'acceptait), et surtout jamais de nouvelle Submission
        pour RETRY_GRANTED (règle 4 du docstring module, déjà appliquée par
        resolve_incident() ci-dessus mais jamais répliquée ici). Un
        professeur résolvant un cluster entier en RETRY_GRANTED aurait vu
        chaque incident marqué "résolu" sans qu'AUCUN étudiant concerné ne
        reçoive réellement une nouvelle tentative.

        Corrigé en réutilisant exactement la même logique que resolve_
        incident(), une fois par membre du cluster (racine + enfants) —
        jamais un bulk UPDATE, jamais de logique dupliquée/divergente.
        Plafond MAX_CLUSTER_SIZE vérifié ICI (pas dans le repository
        désormais, cf. list_cluster_members) avant toute boucle.
        """
        from app.domain.repositories.submission_incident_repository import MAX_CLUSTER_SIZE

        members = await self._incident_repo.list_cluster_members(parent_incident_id)
        if not members:
            raise IncidentNotFoundError(parent_incident_id)
        if len(members) > MAX_CLUSTER_SIZE:
            raise ValueError(
                f"Cluster de {len(members)} incidents dépasse le plafond de sécurité "
                f"({MAX_CLUSTER_SIZE}) — vérification manuelle requise avant résolution en masse"
            )

        resolved_count = 0
        for member in members:
            new_submission_id = None
            if resolution == IncidentResolution.RETRY_GRANTED:
                attempt_number = await self._submission_repo.get_next_attempt_number(
                    member.exercise_id, member.student_id
                )
                new_sub = await self._submission_repo.create(
                    member.exercise_id, member.student_id, attempt_number
                )
                new_submission_id = new_sub.id

            resolved = await self._incident_repo.resolve_single(
                incident_id=member.id,
                resolution=resolution,
                resolution_comment=comment,
                resolved_by_professor_id=requesting_professor_id,
                requesting_professor_id=requesting_professor_id,
                extended_deadline=extended_deadline,
                new_submission_id=new_submission_id,
            )
            if resolved is not None:
                resolved_count += 1

        # Même correctif que resolve_incident() ci-dessus — un cluster peut
        # regrouper plusieurs étudiants distincts, chacun vérifié une fois.
        if resolution == IncidentResolution.REJECTED:
            unique_student_ids = {member.student_id for member in members}
            for student_id in unique_student_ids:
                await self.check_integrity(student_id)

        return resolved_count

    async def check_integrity(self, student_id: uuid.UUID) -> Decimal:
        ratio = await self._incident_repo.get_rejection_ratio(student_id)
        if ratio > INTEGRITY_REJECTION_THRESHOLD:
            from app.domain.models.system_infrastructure.integrity_alert import IntegrityTriggerType
            await self._integrity_repo.create(
                student_id=student_id,
                trigger_type=IntegrityTriggerType.HIGH_REJECTION_RATE,
                auto_generated=True,
                evidence={"rejection_ratio": float(ratio), "threshold": float(INTEGRITY_REJECTION_THRESHOLD)},
                reason=f"Taux de rejet d'incidents anormalement élevé ({ratio*100:.1f}%)",
            )
        return ratio

    async def _enrich_arbitrations(
        self, arbitrations: list[CorrectionArbitration]
    ) -> list[PendingCorrectionArbitrationRead]:
        """
        Dénormalise le contexte complet (OCR IA vs correction humaine
        contestée, image, statut/verdict) pour qu'un client puisse afficher
        et éventuellement trancher sans requête supplémentaire — partagé par
        list_pending_corrections_for_professor (uniquement PENDING) et
        list_arbitrations_for_student (historique complet, traçabilité
        réelle demandée 2026-09-06 : sans ça, un arbitrage résolu disparaît
        de la file PENDING et rien ne permet plus au professeur de retrouver
        ce qu'il a tranché après un rechargement de page).
        """
        items: list[PendingCorrectionArbitrationRead] = []
        for arbitration in arbitrations:
            extraction = await self._extraction_correction_repo.get_by_id(
                arbitration.extraction_correction_id
            )
            if extraction is None:
                continue

            submission = await self._submission_repo.get_by_id(extraction.submission_id)
            if submission is None:
                continue

            student = await self._user_repo.get_by_id(submission.student_id)
            exercise = await self._exercises.get_by_id(submission.exercise_id)
            teacher = (
                await self._user_repo.get_by_id(arbitration.teacher_professor_id)
                if arbitration.teacher_professor_id is not None
                else None
            )

            # Cas ATTACHMENT : extraction.claimed_question_id résolu en
            # numéro de question affichable — jamais l'UUID brut, inutile au
            # professeur (cf. docstring PendingCorrectionArbitrationRead).
            claimed_question_order = None
            if extraction.claimed_question_id is not None and exercise is not None:
                claimed_question_order = next(
                    (q.order for q in exercise.questions if q.id == extraction.claimed_question_id),
                    None,
                )

            items.append(
                PendingCorrectionArbitrationRead(
                    arbitration_id=arbitration.id,
                    extraction_correction_id=extraction.id,
                    submission_id=submission.id,
                    student_id=submission.student_id,
                    student_full_name=(
                        f"{student.first_name} {student.last_name}" if student else "Unknown"
                    ),
                    exercise_id=submission.exercise_id,
                    exercise_title=exercise.title if exercise else "Unknown",
                    question_id=extraction.question_id,
                    contestation_type=extraction.contestation_type,
                    claimed_question_order=claimed_question_order,
                    prediction_ocr=extraction.prediction_ocr,
                    human_correction=extraction.human_correction,
                    image_crop_url=(
                        self._storage.generate_read_url(
                            StorageContainer.SUBMISSIONS, extraction.image_crop_path
                        )
                        if extraction.image_crop_path
                        else None
                    ),
                    document_url=(
                        self._storage.generate_read_url(
                            StorageContainer.SUBMISSIONS, submission.document_path
                        )
                        if submission.document_path
                        else None
                    ),
                    created_at=arbitration.created_at,
                    status=arbitration.status,
                    verdict=arbitration.verdict,
                    teacher_full_name=(
                        f"{teacher.first_name} {teacher.last_name}" if teacher else None
                    ),
                )
            )
        return items

    async def list_pending_corrections_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[PendingCorrectionArbitrationRead]:
        """
        Gap trouvé lors de l'audit arbitrage : /arbitrations/corrections/
        {id}/resolve existait déjà mais aucun endpoint ne renvoyait les ID
        en attente — dénormalise ici le contexte complet (OCR IA vs
        correction humaine contestée, image) pour que le professeur puisse
        trancher sans requête supplémentaire.
        """
        arbitrations = await self._arbitration_repo.list_pending_for_professor(professor_id)
        return await self._enrich_arbitrations(arbitrations)

    async def list_all_corrections_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[PendingCorrectionArbitrationRead]:
        """
        Traçabilité réelle (2026-09-06) — sert la liste PRINCIPALE (groupée
        par étudiant côté frontend) : contrairement à list_pending_
        corrections_for_professor, inclut aussi les arbitrages déjà résolus,
        pour qu'un étudiant entièrement traité garde une ligne consultable
        (avec son historique) au lieu de disparaître purement et simplement.
        """
        arbitrations = await self._arbitration_repo.list_all_for_professor(professor_id)
        return await self._enrich_arbitrations(arbitrations)

    async def list_arbitrations_for_student(
        self, professor_id: uuid.UUID, student_id: uuid.UUID
    ) -> list[PendingCorrectionArbitrationRead]:
        """
        Historique COMPLET (PENDING + RESOLVED) des arbitrages d'un étudiant
        précis — traçabilité réelle (2026-09-06, cf. docstring repository) :
        contrairement à list_pending_corrections_for_professor, n'exclut
        jamais les arbitrages déjà tranchés, pour que le détail étudiant
        reste consultable après un rechargement de page.
        """
        arbitrations = await self._arbitration_repo.list_by_student_for_professor(
            professor_id, student_id
        )
        return await self._enrich_arbitrations(arbitrations)

    async def list_pending_incidents_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[SubmissionIncidentRead]:
        """
        Gap trouvé lors de l'audit arbitrage — même constat que ci-dessus
        pour les incidents. exercise_title ajouté (audit espace professeur,
        clustering) — batché par exercise_id DISTINCT, même principe que
        student_full_name juste en dessous (jamais un N+1 par incident).
        """
        incidents = await self._incident_repo.list_pending_for_professor(professor_id)

        # Une requête par étudiant DISTINCT — même pattern que AuditService.list_logs.
        unique_student_ids = {incident.student_id for incident in incidents}
        names_by_student_id: dict[uuid.UUID, str] = {}
        for student_id in unique_student_ids:
            student = await self._user_repo.get_by_id(student_id)
            names_by_student_id[student_id] = (
                f"{student.first_name} {student.last_name}" if student else "Unknown"
            )

        unique_exercise_ids = {incident.exercise_id for incident in incidents}
        titles_by_exercise_id: dict[uuid.UUID, str] = {}
        for exercise_id in unique_exercise_ids:
            exercise = await self._exercises.get_by_id(exercise_id)
            titles_by_exercise_id[exercise_id] = exercise.title if exercise else "Unknown"

        items: list[SubmissionIncidentRead] = []
        for incident in incidents:
            incident.student_full_name = names_by_student_id[incident.student_id]
            incident.exercise_title = titles_by_exercise_id[incident.exercise_id]
            incident.attachment_url = incident.attachment_path
            items.append(SubmissionIncidentRead.model_validate(incident))
        return items

