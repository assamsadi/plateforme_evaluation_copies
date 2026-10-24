"""
Service RGPD — orchestration des demandes de droits des personnes.

Règles métier appliquées :
1. Une demande ne peut être traitée que si l'identité du demandeur a été
   vérifiée au préalable (verify_identity). Toute tentative de start_processing
   sans vérification lève IdentityNotVerifiedError (garde-fou au niveau repo).
2. Le traitement d'une ERASURE ne mène pas nécessairement à une suppression
   physique — si des obligations légales de rétention s'appliquent (ex: notes),
   le résultat est PSEUDONYMIZED ou PARTIAL_RETENTION_LEGAL. Le processeur
   humain (DPO) doit choisir la résolution correcte.
3. Pour ACCESS_EXPORT, le service construit le chemin du fichier exporté
   (Azure Blob) et fixe une date d'expiration (7 jours par défaut).
4. La legal_deadline est calculée automatiquement à J+30 à la création
   (conforme au délai légal RGPD). Une tâche Celery (non implémentée ici)
   doit alerter le DPO à l'approche de la deadline via list_approaching_deadline.
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.core.exceptions import RequestNotFoundError
from app.domain.models.system_infrastructure.data_privacy_request import (
    DataPrivacyRequest,
    PrivacyRequestType,
    PrivacyResolutionDetail,
)
from app.domain.repositories.data_privacy_repository import (
    DataPrivacyRepositoryProtocol,
    IdentityNotVerifiedError,
    InvalidStatusTransitionError,
)
from app.domain.repositories.user_repository import UserRepositoryProtocol
from app.infra_services.storage_service import StorageContainer, StorageService
from app.domain.schemas.system_schemas import DataPrivacyRequestRead

# Durée de validité d'un lien d'export (sécurité : jamais indéfini)
EXPORT_LINK_VALIDITY_DAYS = 7


class DataPrivacyServiceProtocol(Protocol):
    async def get_request(self, request_id: uuid.UUID) -> DataPrivacyRequestRead: ...

    async def submit_request(
        self, user_id: uuid.UUID, request_type: PrivacyRequestType
    ) -> DataPrivacyRequestRead: ...

    async def verify_identity(
        self, request_id: uuid.UUID, verification_method: str
    ) -> DataPrivacyRequestRead: ...

    async def start_processing(
        self, request_id: uuid.UUID, processor_id: uuid.UUID
    ) -> DataPrivacyRequestRead: ...

    async def complete_erasure(
        self,
        request_id: uuid.UUID,
        resolution_detail: PrivacyResolutionDetail,
        reason: str | None,
    ) -> DataPrivacyRequestRead: ...

    async def complete_export(
        self,
        request_id: uuid.UUID,
        export_blob_path: str,
    ) -> DataPrivacyRequestRead: ...

    async def reject_request(
        self,
        request_id: uuid.UUID,
        processor_id: uuid.UUID,
        reason: str,
    ) -> DataPrivacyRequestRead: ...

    async def list_pending_for_dpo(self) -> list[DataPrivacyRequestRead]: ...

    async def list_approaching_deadline(
        self, threshold_days: int = 7
    ) -> list[DataPrivacyRequestRead]: ...

    async def list_by_user(self, user_id: uuid.UUID) -> list[DataPrivacyRequestRead]: ...


class DataPrivacyService:
    def __init__(
        self,
        privacy_repo: DataPrivacyRepositoryProtocol,
        storage_service: StorageService,
        user_repo: UserRepositoryProtocol,
    ) -> None:
        self._repo = privacy_repo
        self._storage = storage_service
        self._user_repo = user_repo

    async def _to_request_read(self, request: DataPrivacyRequest) -> DataPrivacyRequestRead:
        if request.export_file_path:
            request.export_file_url = self._storage.generate_read_url(
                StorageContainer.SUBMISSIONS, request.export_file_path
            )
        else:
            request.export_file_url = None
        user = await self._user_repo.get_by_id(request.user_id)
        request.user_full_name = f"{user.first_name} {user.last_name}" if user else "Unknown"
        return DataPrivacyRequestRead.model_validate(request)

    async def _to_request_read_batch(
        self, requests: list[DataPrivacyRequest]
    ) -> list[DataPrivacyRequestRead]:
        # Une requête par utilisateur DISTINCT présent sur la page, pas par
        # ligne — même pattern que AuditService.list_logs.
        unique_user_ids = {request.user_id for request in requests}
        names_by_user_id: dict[uuid.UUID, str] = {}
        for user_id in unique_user_ids:
            user = await self._user_repo.get_by_id(user_id)
            names_by_user_id[user_id] = f"{user.first_name} {user.last_name}" if user else "Unknown"

        items: list[DataPrivacyRequestRead] = []
        for request in requests:
            if request.export_file_path:
                request.export_file_url = self._storage.generate_read_url(
                    StorageContainer.SUBMISSIONS, request.export_file_path
                )
            else:
                request.export_file_url = None
            request.user_full_name = names_by_user_id[request.user_id]
            items.append(DataPrivacyRequestRead.model_validate(request))
        return items

    async def get_request(self, request_id: uuid.UUID) -> DataPrivacyRequestRead:
        request = await self._repo.get_by_id(request_id)
        if not request:
            raise RequestNotFoundError(request_id)
        return await self._to_request_read(request)

    async def submit_request(
        self, user_id: uuid.UUID, request_type: PrivacyRequestType
    ) -> DataPrivacyRequestRead:
        request = await self._repo.create(user_id=user_id, request_type=request_type)
        return await self._to_request_read(request)

    async def verify_identity(
        self, request_id: uuid.UUID, verification_method: str
    ) -> DataPrivacyRequestRead:
        request = await self._repo.verify_identity(
            request_id=request_id, verification_method=verification_method
        )
        if not request:
            raise RequestNotFoundError(request_id)
        return await self._to_request_read(request)

    async def start_processing(
        self, request_id: uuid.UUID, processor_id: uuid.UUID
    ) -> DataPrivacyRequestRead:
        request = await self._repo.start_processing(
            request_id=request_id, processor_id=processor_id
        )
        if not request:
            raise RequestNotFoundError(request_id)
        return await self._to_request_read(request)

    async def complete_erasure(
        self,
        request_id: uuid.UUID,
        resolution_detail: PrivacyResolutionDetail,
        reason: str | None,
    ) -> DataPrivacyRequestRead:
        """
        Bug corrigé (audit espace admin) : cette méthode ne faisait que
        déplacer un statut (repo.complete()) — jamais aucune modification
        réelle des données de l'utilisateur, quel que soit resolution_
        detail. Un DPO "complétant" une ERASURE en FULL_DELETION ou
        PSEUDONYMIZED produisait un enregistrement d'audit affirmant un
        effacement, sans qu'aucune donnée ne change réellement.

        FULL_DELETION et PSEUDONYMIZED reçoivent désormais EXACTEMENT le
        même traitement réel : anonymisation de l'identité (nom/prénom/
        email) + désactivation du compte (jamais de suppression physique
        de la ligne User, cf. politique actée cette session — audit_log.
        user_id est non-nullable, un compte ayant journalisé une action ne
        peut jamais être supprimé sans corrompre la piste d'audit). Les
        notes/soumissions/évaluations restent intactes (obligation légale
        de rétention, cf. docstring modèle DataPrivacyRequest) — elles ne
        référencent jamais le nom en dur nulle part dans ce codebase,
        toujours résolu dynamiquement depuis User à la lecture (student_
        full_name aplati), donc l'anonymisation du compte suffit à
        anonymiser son nom PARTOUT où il est affiché, sans toucher aucune
        autre table.

        PARTIAL_RETENTION_LEGAL volontairement PAS traité ici : sa
        sémantique exacte (quelle partie est retenue, quelle partie ne
        l'est pas) n'est écrite nulle part ailleurs dans le code — le DPO
        documente le détail réel dans `reason`, aucun comportement inventé
        ici plutôt qu'une action arbitraire et potentiellement fausse.

        PROCESSING_RESTRICTED/OBJECTION_UPHELD (migration c0d1e2f3a4b5,
        audit espace admin) : même principe — RESTRICTION et OBJECTION
        n'ont ici aucun effet automatique sur le compte ou le traitement
        (aucune infrastructure de "gel du traitement" n'existe ailleurs
        dans ce codebase à faire déclencher). Purs enregistrements
        documentaires, comme PARTIAL_RETENTION_LEGAL ci-dessus.
        """
        request = await self._repo.complete(
            request_id=request_id,
            resolution_detail=resolution_detail,
            reason=reason,
        )
        if not request:
            raise RequestNotFoundError(request_id)

        if resolution_detail in (
            PrivacyResolutionDetail.FULL_DELETION,
            PrivacyResolutionDetail.PSEUDONYMIZED,
        ):
            await self._user_repo.update(
                request.user_id,
                first_name="Utilisateur",
                last_name="anonymisé",
                email=f"anonymise-{request.id}@rgpd.local",
                is_active=False,
            )

        return await self._to_request_read(request)

    async def complete_export(
        self,
        request_id: uuid.UUID,
        export_blob_path: str,
    ) -> DataPrivacyRequestRead:
        expires_at = datetime.now(timezone.utc) + timedelta(days=EXPORT_LINK_VALIDITY_DAYS)
        request = await self._repo.complete(
            request_id=request_id,
            resolution_detail=PrivacyResolutionDetail.EXPORTED,
            reason=None,
            export_file_path=export_blob_path,
            export_file_expires_at=expires_at,
        )
        if not request:
            raise RequestNotFoundError(request_id)
        return await self._to_request_read(request)

    async def reject_request(
        self,
        request_id: uuid.UUID,
        processor_id: uuid.UUID,
        reason: str,
    ) -> DataPrivacyRequestRead:
        request = await self._repo.reject(
            request_id=request_id, processor_id=processor_id, reason=reason
        )
        if not request:
            raise RequestNotFoundError(request_id)
        return await self._to_request_read(request)

    async def list_pending_for_dpo(self) -> list[DataPrivacyRequestRead]:
        page = await self._repo.list_pending(limit=500)
        return await self._to_request_read_batch(page.items)

    async def list_approaching_deadline(
        self, threshold_days: int = 7
    ) -> list[DataPrivacyRequestRead]:
        requests = await self._repo.list_approaching_deadline(threshold_days=threshold_days)
        return await self._to_request_read_batch(requests)

    async def list_by_user(self, user_id: uuid.UUID) -> list[DataPrivacyRequestRead]:
        page = await self._repo.list_by_user(user_id=user_id, limit=500)
        return await self._to_request_read_batch(page.items)

