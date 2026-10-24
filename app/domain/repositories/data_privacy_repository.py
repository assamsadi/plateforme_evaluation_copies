"""
Repository DataPrivacyRequest (RGPD).

Règles de sécurité implémentées ici-même (défense en profondeur) :
- start_processing() vérifie que identity_verified == True AVANT de passer
  la demande en IN_PROGRESS. Si ce n'est pas le cas, lève
  IdentityNotVerifiedError — un service qui oublierait cette vérification
  ne pourra pas déclencher de traitement sur une identité non confirmée.
- complete() et reject() vérifient que le statut courant est IN_PROGRESS
  (transition d'état stricte).

Méthodes :
- create               : crée la demande (identity_verified=False, status=PENDING)
- get_by_id            : accès par PK
- list_by_user         : historique RGPD paginé d'un utilisateur
- list_pending         : file d'attente DPO (demandes PENDING ou IN_PROGRESS —
                         actives, pas encore COMPLETED/REJECTED ; sinon une
                         demande disparaîtrait de toute liste dès
                         start_processing, avant même d'avoir pu être
                         complétée ou rejetée)
- list_approaching_deadline : demandes dont legal_deadline arrive dans N jours
- verify_identity      : valide l'identité du demandeur (prérequis au traitement)
- start_processing     : passe en IN_PROGRESS (bloqué si non vérifié)
- complete             : finalise avec le détail de résolution
- reject               : rejette avec motif
"""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.core.exceptions import ForbiddenError, ValidationError
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.system_infrastructure.data_privacy_request import (
    DataPrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    PrivacyResolutionDetail,
)
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)

# Délai légal RGPD standard : 30 jours calendaires
LEGAL_DEADLINE_DAYS = 30


class IdentityNotVerifiedError(ForbiddenError):
    def __init__(self, request_id: uuid.UUID) -> None:
        super().__init__(
            f"Impossible de traiter la demande {request_id} : "
            f"l'identité du demandeur n'a pas encore été vérifiée."
        )


class InvalidStatusTransitionError(ValidationError):
    def __init__(self, request_id: uuid.UUID, current: str, expected: str) -> None:
        super().__init__(
            f"Demande {request_id} : transition invalide depuis '{current}' "
            f"(attendu : '{expected}')."
        )


class DataPrivacyRepositoryProtocol(Protocol):
    async def create(
        self,
        user_id: uuid.UUID,
        request_type: PrivacyRequestType,
        legal_deadline: datetime | None = None,
    ) -> DataPrivacyRequest: ...

    async def get_by_id(self, request_id: uuid.UUID) -> DataPrivacyRequest | None: ...

    async def list_by_user(
        self, user_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[DataPrivacyRequest]: ...

    async def list_pending(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[DataPrivacyRequest]: ...

    async def list_approaching_deadline(
        self, threshold_days: int = 7
    ) -> list[DataPrivacyRequest]: ...

    async def verify_identity(
        self, request_id: uuid.UUID, verification_method: str
    ) -> DataPrivacyRequest | None: ...

    async def start_processing(
        self, request_id: uuid.UUID, processor_id: uuid.UUID
    ) -> DataPrivacyRequest | None: ...

    async def complete(
        self,
        request_id: uuid.UUID,
        resolution_detail: PrivacyResolutionDetail,
        reason: str | None,
        export_file_path: str | None = None,
        export_file_expires_at: datetime | None = None,
    ) -> DataPrivacyRequest | None: ...

    async def reject(
        self,
        request_id: uuid.UUID,
        processor_id: uuid.UUID,
        reason: str,
    ) -> DataPrivacyRequest | None: ...


class SQLAlchemyDataPrivacyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: uuid.UUID,
        request_type: PrivacyRequestType,
        legal_deadline: datetime | None = None,
    ) -> DataPrivacyRequest:
        if legal_deadline is None:
            legal_deadline = datetime.now(timezone.utc) + timedelta(days=LEGAL_DEADLINE_DAYS)

        request = DataPrivacyRequest(
            user_id=user_id,
            request_type=request_type,
            status=PrivacyRequestStatus.PENDING,
            legal_deadline=legal_deadline,
            identity_verified=False,
        )
        self._session.add(request)
        await self._session.flush()
        return request

    async def get_by_id(self, request_id: uuid.UUID) -> DataPrivacyRequest | None:
        return await self._session.get(DataPrivacyRequest, request_id)

    async def list_by_user(
        self, user_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[DataPrivacyRequest]:
        query = select(DataPrivacyRequest).where(DataPrivacyRequest.user_id == user_id)
        return await self._paginated_query(query, cursor, limit)

    async def list_pending(
        self, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[DataPrivacyRequest]:
        query = select(DataPrivacyRequest).where(
            DataPrivacyRequest.status.in_(
                [PrivacyRequestStatus.PENDING, PrivacyRequestStatus.IN_PROGRESS]
            )
        )
        return await self._paginated_query(query, cursor, limit)

    async def list_approaching_deadline(
        self, threshold_days: int = 7
    ) -> list[DataPrivacyRequest]:
        """
        Demandes PENDING ou IN_PROGRESS dont la legal_deadline arrive dans
        threshold_days jours — utilisées par un job Celery d'alerte DPO.
        """
        now = datetime.now(timezone.utc)
        horizon = now + timedelta(days=threshold_days)
        stmt = select(DataPrivacyRequest).where(
            DataPrivacyRequest.status.in_(
                [PrivacyRequestStatus.PENDING, PrivacyRequestStatus.IN_PROGRESS]
            ),
            DataPrivacyRequest.legal_deadline <= horizon,
            DataPrivacyRequest.legal_deadline >= now,
        ).order_by(DataPrivacyRequest.legal_deadline)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _paginated_query(
        self, query, cursor: str | None, limit: int
    ) -> CursorPage[DataPrivacyRequest]:
        query = query.order_by(DataPrivacyRequest.created_at, DataPrivacyRequest.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(DataPrivacyRequest.created_at, DataPrivacyRequest.id)
                > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda r: (r.created_at, r.id))

    async def verify_identity(
        self, request_id: uuid.UUID, verification_method: str
    ) -> DataPrivacyRequest | None:
        request = await self.get_by_id(request_id)
        if request is None:
            return None
        request.identity_verified = True
        request.verification_method = verification_method
        await self._session.flush()
        return request

    async def start_processing(
        self, request_id: uuid.UUID, processor_id: uuid.UUID
    ) -> DataPrivacyRequest | None:
        """
        Garde-fou : bloque tout traitement si l'identité n'est pas vérifiée.
        """
        request = await self.get_by_id(request_id)
        if request is None:
            return None
        if not request.identity_verified:
            raise IdentityNotVerifiedError(request_id)
        if request.status != PrivacyRequestStatus.PENDING:
            raise InvalidStatusTransitionError(
                request_id, current=request.status, expected=PrivacyRequestStatus.PENDING
            )
        request.status = PrivacyRequestStatus.IN_PROGRESS
        request.processed_by_user_id = processor_id
        await self._session.flush()
        return request

    async def complete(
        self,
        request_id: uuid.UUID,
        resolution_detail: PrivacyResolutionDetail,
        reason: str | None,
        export_file_path: str | None = None,
        export_file_expires_at: datetime | None = None,
    ) -> DataPrivacyRequest | None:
        request = await self.get_by_id(request_id)
        if request is None:
            return None
        if request.status != PrivacyRequestStatus.IN_PROGRESS:
            raise InvalidStatusTransitionError(
                request_id, current=request.status, expected=PrivacyRequestStatus.IN_PROGRESS
            )
        request.status = PrivacyRequestStatus.COMPLETED
        request.resolution_detail = resolution_detail
        request.retention_or_rejection_reason = reason
        request.processed_at = datetime.now(timezone.utc)
        if export_file_path is not None:
            request.export_file_path = export_file_path
        if export_file_expires_at is not None:
            request.export_file_expires_at = export_file_expires_at
        await self._session.flush()
        return request

    async def reject(
        self,
        request_id: uuid.UUID,
        processor_id: uuid.UUID,
        reason: str,
    ) -> DataPrivacyRequest | None:
        request = await self.get_by_id(request_id)
        if request is None:
            return None
        if request.status not in (
            PrivacyRequestStatus.PENDING, PrivacyRequestStatus.IN_PROGRESS
        ):
            raise InvalidStatusTransitionError(
                request_id,
                current=request.status,
                expected=f"{PrivacyRequestStatus.PENDING} ou {PrivacyRequestStatus.IN_PROGRESS}",
            )
        request.status = PrivacyRequestStatus.REJECTED
        request.resolution_detail = PrivacyResolutionDetail.REJECTED
        request.retention_or_rejection_reason = reason
        request.processed_by_user_id = processor_id
        request.processed_at = datetime.now(timezone.utc)
        await self._session.flush()
        return request
