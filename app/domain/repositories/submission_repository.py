"""
Repository Submission — racine d'agrégat couvrant Submission +
ExtractionCorrection.

get_next_attempt_number() utilise SELECT ... FOR UPDATE (verrou
pessimiste) : sans lui, deux requêtes HTTP simultanées du même étudiant
(ex. double-clic, ou retry réseau qui arrive quand même) pourraient
toutes les deux lire "1 tentative existante" et créer deux fois la
"tentative n°2", violant silencieusement la contrainte unique
(exercise_id, student_id, attempt_number) — ou pire, provoquant une
erreur de contrainte confuse côté utilisateur plutôt qu'un comportement
prévisible. Le verrou force la deuxième requête à ATTENDRE que la
première ait committé avant de lire le compte à jour.

Coût : FOR UPDATE bloque les lectures concurrentes sur les lignes visées
le temps de la transaction — acceptable ici car la fenêtre est courte
(un COUNT + un INSERT) et la contention réelle est faible (un même
étudiant ne soumet pas deux fois à la milliseconde près en usage normal).
"""
import uuid
from typing import Protocol

from sqlalchemy import func, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.extraction_correction import ExtractionCorrection
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.repositories.pagination import (
    DEFAULT_PAGE_SIZE,
    CursorPage,
    build_cursor_page,
    decode_cursor,
)


class SubmissionRepositoryProtocol(Protocol):
    async def get_by_id(self, submission_id: uuid.UUID) -> Submission | None: ...
    async def get_next_attempt_number(
        self, exercise_id: uuid.UUID, student_id: uuid.UUID
    ) -> int: ...
    async def count_attempts(self, exercise_id: uuid.UUID, student_id: uuid.UUID) -> int: ...
    async def count_by_student(self, student_id: uuid.UUID) -> int: ...
    async def count_by_student_and_exercise_ids(
        self, student_id: uuid.UUID, exercise_ids: list[uuid.UUID],
    ) -> int: ...
    async def list_by_exercise(
        self, exercise_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Submission]: ...
    async def list_by_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Submission]: ...
    async def list_evaluated_by_student_and_exercise_ids(
        self, student_id: uuid.UUID, exercise_ids: list[uuid.UUID],
    ) -> list[Submission]: ...
    async def create(
        self, exercise_id: uuid.UUID, student_id: uuid.UUID, attempt_number: int
    ) -> Submission: ...
    async def create_absent(
        self, exercise_id: uuid.UUID, student_id: uuid.UUID
    ) -> Submission: ...
    async def update_status(
        self, submission_id: uuid.UUID, status: SubmissionStatus
    ) -> Submission | None: ...
    async def update_document(
        self,
        submission_id: uuid.UUID,
        document_path: str,
        document_mime_type: str,
    ) -> Submission | None: ...
    async def get_extraction_corrections(
        self, submission_id: uuid.UUID
    ) -> list[ExtractionCorrection]: ...
    async def count_by_status(self) -> dict[str, int]: ...
    async def acquire_advisory_lock(self, submission_id: uuid.UUID) -> None: ...


class SQLAlchemySubmissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, submission_id: uuid.UUID) -> Submission | None:
        return await self._session.get(Submission, submission_id)

    async def acquire_advisory_lock(self, submission_id: uuid.UUID) -> None:
        """
        Verrou consultatif Postgres transactionnel (pg_advisory_xact_lock,
        auto-libéré au commit/rollback de LA transaction courante — jamais
        d'unlock manuel nécessaire) — même principe que get_next_attempt_
        number() ci-dessus (SELECT ... FOR UPDATE), mais ici sur une clé
        logique (submission_id) plutôt qu'un ensemble de lignes, car les
        deux côtés de la course ne lisent pas forcément les mêmes lignes.

        Bug réel corrigé (2026-09-06, test réel FR/ES) : ExtractionService.
        confirm_submission() (resume="confirmed") et process_contestation_
        verification (resume="contestation_pending") peuvent tourner en
        CONCURRENCE sur le MÊME thread LangGraph (même submission_id) —
        l'étudiant confirme sa copie pendant que sa contestation vient
        juste d'être décidée AMBIGU. Sans coordination, une vérification
        "y a-t-il une contestation non résolue ?" côté confirm_submission
        peut lire un état encore PENDING_VERIFICATION (pas bloquant) une
        fraction de seconde avant que process_contestation_verification ne
        le pose à AMBIGU + crée l'arbitrage — confirm_submission gagne la
        course de resume() sur await_student_verification_node, le thread
        fonce jusqu'à comparative_evaluation_node/fin, et l'arbitrage créé
        juste après reste orphelin pour toujours (plus aucun thread en
        pause à teacher_arbitration_node pour le recevoir). Verrouiller
        cette clé AVANT toute lecture d'état côté des deux appelants (cf.
        extraction_service.confirm_submission et contestation_tasks.
        process_contestation_verification) sérialise les deux chemins :
        celui qui commence en premier voit son travail (décision + resume)
        entièrement terminé et commité avant que l'autre ne commence à lire.
        hashtext() (retour int4) plutôt qu'un cast UUID->bigint : suffisant
        ici, une collision de hash entre deux submissions différentes ne
        casse rien (sérialise juste, à tort, deux soumissions sans rapport
        de façon négligeable rare) — jamais un risque de correction.
        """
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": str(submission_id)},
        )

    async def get_next_attempt_number(
        self, exercise_id: uuid.UUID, student_id: uuid.UUID
    ) -> int:
        """
        Verrou pessimiste : verrouille les soumissions existantes de l'étudiant pour cet exercice
        afin d'empêcher les créations concourantes de tentatives sous le même numéro.
        """
        stmt = (
            select(Submission.attempt_number)
            .where(Submission.exercise_id == exercise_id, Submission.student_id == student_id)
            .with_for_update()
        )
        result = await self._session.execute(stmt)
        attempts = list(result.scalars().all())
        return max(attempts, default=0) + 1

    async def count_attempts(self, exercise_id: uuid.UUID, student_id: uuid.UUID) -> int:
        """Lecture seule, sans verrou — pour affichage (ex. "3e tentative"), pas pour création."""
        stmt = (
            select(func.count())
            .select_from(Submission)
            .where(Submission.exercise_id == exercise_id, Submission.student_id == student_id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_by_student(self, student_id: uuid.UUID) -> int:
        """
        Bug corrigé (câblage GET /students/me/stats) : StatisticsService.
        get_student_stats utilisait len(list_by_student(student_id).items)
        pour total_submissions — list_by_student est PAGINÉE (DEFAULT_PAGE_
        SIZE=50, jamais overridé par l'appelant), donc silencieusement
        plafonnée à 50 pour tout étudiant en ayant davantage, jamais un vrai
        total. Même principe que count_attempts ci-dessus : un COUNT natif,
        jamais des lignes chargées seulement pour être comptées.
        """
        stmt = select(func.count()).select_from(Submission).where(Submission.student_id == student_id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def count_by_student_and_exercise_ids(
        self, student_id: uuid.UUID, exercise_ids: list[uuid.UUID],
    ) -> int:
        """
        Câblage écran "Profil de compétence" (bloc infos étudiant, vue
        professeur) — total de copies déposées par l'étudiant pour UN
        module (exercise_ids = tous les exercices de ce module), même
        discipline COUNT natif que count_by_student. No-op sur liste vide
        (jamais un WHERE ... IN () dégénéré, même garde que
        list_evaluated_by_student_and_exercise_ids).
        """
        if not exercise_ids:
            return 0
        stmt = select(func.count()).select_from(Submission).where(
            Submission.student_id == student_id, Submission.exercise_id.in_(exercise_ids),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def list_by_exercise(
        self, exercise_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Submission]:
        query = select(Submission).where(Submission.exercise_id == exercise_id)
        return await self._paginated_query(query, cursor, limit)

    async def list_by_student(
        self, student_id: uuid.UUID, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
    ) -> CursorPage[Submission]:
        query = select(Submission).where(Submission.student_id == student_id)
        return await self._paginated_query(query, cursor, limit)

    async def list_evaluated_by_student_and_exercise_ids(
        self, student_id: uuid.UUID, exercise_ids: list[uuid.UUID],
    ) -> list[Submission]:
        """
        Câblage Recommendation_Agent (clôture) — bornée par exercise_ids
        (candidats de la Library pour UNE compétence, ensemble modeste),
        jamais une pagination ici : sert uniquement à détecter les
        exercices déjà réussis à 100% par l'étudiant, pas un affichage.
        No-op sur liste vide (jamais un WHERE ... IN () dégénéré).
        """
        if not exercise_ids:
            return []
        query = select(Submission).where(
            Submission.student_id == student_id,
            Submission.exercise_id.in_(exercise_ids),
            Submission.status == SubmissionStatus.EVALUATED,
        )
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def _paginated_query(self, query, cursor: str | None, limit: int) -> CursorPage[Submission]:
        query = query.order_by(Submission.created_at, Submission.id)
        if cursor:
            after_created_at, after_id = decode_cursor(cursor)
            query = query.where(
                tuple_(Submission.created_at, Submission.id) > (after_created_at, after_id)
            )
        query = query.limit(limit + 1)
        result = await self._session.execute(query)
        rows = list(result.scalars().all())
        return build_cursor_page(rows, limit, lambda s: (s.created_at, s.id))

    async def create(
        self, exercise_id: uuid.UUID, student_id: uuid.UUID, attempt_number: int
    ) -> Submission:
        submission = Submission(
            exercise_id=exercise_id,
            student_id=student_id,
            attempt_number=attempt_number,
            status=SubmissionStatus.PENDING_OCR,
        )
        self._session.add(submission)
        await self._session.flush()
        return submission

    async def create_absent(
        self, exercise_id: uuid.UUID, student_id: uuid.UUID
    ) -> Submission:
        submission = Submission(
            exercise_id=exercise_id,
            student_id=student_id,
            attempt_number=0,
            status=SubmissionStatus.ABSENT,
        )
        self._session.add(submission)
        await self._session.flush()
        return submission

    async def update_status(
        self, submission_id: uuid.UUID, status: SubmissionStatus
    ) -> Submission | None:
        submission = await self.get_by_id(submission_id)
        if submission is None:
            return None
        submission.status = status
        await self._session.flush()
        return submission

    async def update_document(
        self,
        submission_id: uuid.UUID,
        document_path: str,
        document_mime_type: str,
    ) -> Submission | None:
        submission = await self.get_by_id(submission_id)
        if submission is None:
            return None
        submission.document_path = document_path
        submission.document_mime_type = document_mime_type
        await self._session.flush()
        return submission

    async def get_extraction_corrections(
        self, submission_id: uuid.UUID
    ) -> list[ExtractionCorrection]:
        result = await self._session.execute(
            select(ExtractionCorrection).where(
                ExtractionCorrection.submission_id == submission_id
            )
        )
        return list(result.scalars().all())

    async def count_by_status(self) -> dict[str, int]:
        """Câblage StatisticsService.get_platform_stats — cf. UserRepository.count_by_role (même contrat, statuts absents complétés côté service)."""
        stmt = select(Submission.status, func.count()).group_by(Submission.status)
        result = await self._session.execute(stmt)
        return {status.value: count for status, count in result.all()}