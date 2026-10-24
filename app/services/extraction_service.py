"""
Service ExtractionCorrection — règles métier :

1. record_extraction() : persiste en lot tous les blocs OCR d'une soumission.
   Appelé par l'OCR Pipeline après traitement — n'est jamais appelé par
   l'API HTTP directement (pas de router associé, c'est un service interne).
   Valide que la soumission existe avant de persister.

2. contest_extraction() : HITL étudiant — l'étudiant conteste UNE extraction
   précise, un des 4 cas distincts de Contestation_Verification_Agent
   (docs/agent-contestation-verification-workflow-exhaustif.md §2).
   Règles :
   - La correction doit appartenir à la soumission de l'étudiant (IDOR).
   - §2 étape 3 : rejette une réclamation vide ou identique au contenu déjà
     extrait, avant même d'atteindre l'agent.
   - Le statut de contestation actuel du bloc détermine le chemin :
     jamais contesté -> dépôt normal (déclenche l'agent via Celery) ;
     déjà IMPLAUSIBLE/PLAUSIBLE -> §2 étape 8, escalade directe au
     professeur, jamais un second passage automatique par l'agent ;
     déjà PENDING_VERIFICATION/AMBIGU -> une contestation est déjà en
     cours, conflit ; déjà RESOLVED -> §2 étape 9, plus aucune contestation
     possible sur ce bloc.
"""
import logging
import uuid
from typing import Protocol

from app.agents.Contestation_Verification_Agent import (
    WHOLE_STRUCTURE_ELEMENT_ID,
    ContestationVerificationAgent,
)
from kombu.exceptions import OperationalError as BrokerOperationalError

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    SubmissionNotFoundError,
    SubmissionNotPendingVerificationError,
    SubmissionResumeDispatchError,
    ValidationError,
)
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
)
from app.domain.models.assessment.submission import SubmissionStatus
from app.domain.repositories.correction_arbitration_repository import (
    CorrectionArbitrationRepositoryProtocol,
)
from app.domain.repositories.extraction_correction_repository import (
    ExtractionCorrectionRepositoryProtocol,
)
from app.domain.repositories.submission_repository import SubmissionRepositoryProtocol
from app.domain.schemas.contestation_schemas import ContestExtractionRequest
from app.domain.schemas.submission_schemas import (
    ExtractionCorrectionRead,
    SubmissionConfirmationRead,
)
from app.infra_services.storage_service import StorageContainer, StorageService
from app.tasks.contestation_tasks import process_contestation_verification
from app.tasks.job_tasks import process_job_resumed

logger = logging.getLogger(__name__)


class ExtractionNotFoundError(NotFoundError):
    def __init__(self, correction_id: uuid.UUID) -> None:
        super().__init__(f"ExtractionCorrection introuvable (ID: {correction_id})")


class ExtractionNotOwnedByStudentError(ForbiddenError):
    def __init__(self, correction_id: uuid.UUID, student_id: uuid.UUID) -> None:
        super().__init__(
            f"L'extraction {correction_id} n'appartient pas à l'étudiant {student_id}"
        )


class TrivialContestationError(ValidationError):
    """§2 étape 3 — réclamation vide ou identique au contenu déjà extrait."""
    def __init__(self, correction_id: uuid.UUID) -> None:
        super().__init__(
            f"La réclamation pour l'extraction {correction_id} est vide ou identique au "
            "contenu déjà extrait — rejetée avant d'atteindre l'agent"
        )


class ContestationAlreadyInProgressError(ConflictError):
    """
    Ne correspond à aucune étape numérotée du doc de référence agent — ajoutée
    par nécessité technique, pas par lecture du texte. Conséquence directe du
    même trou de modélisation que le vrai §9ter (une seule ExtractionCorrection
    ne peut porter qu'une seule contestation en cours à la fois : une colonne
    contestation_type/contestation_status par ligne, jamais deux simultanément).
    Sans cette garde, une seconde contestation déposée pendant que la première
    est encore PENDING_VERIFICATION/AMBIGU écraserait silencieusement son état
    avant qu'elle n'ait jamais atteint un verdict.
    """
    def __init__(self, correction_id: uuid.UUID) -> None:
        super().__init__(
            f"Une contestation est déjà en cours de traitement pour l'extraction {correction_id}"
        )


class ContestationOnResolvedBlockError(ForbiddenError):
    """§2 étape 9 — décision du professeur définitive pour la phase d'extraction."""
    def __init__(self, correction_id: uuid.UUID) -> None:
        super().__init__(
            f"L'extraction {correction_id} a déjà une décision définitive du professeur — "
            "plus aucune nouvelle contestation possible sur ce bloc"
        )


class ExtractionServiceProtocol(Protocol):
    async def record_extraction(
        self,
        submission_id: uuid.UUID,
        blocks: list[dict],
    ) -> list[ExtractionCorrectionRead]: ...

    async def contest_extraction(
        self,
        submission_id: uuid.UUID,
        correction_id: uuid.UUID,
        student_id: uuid.UUID,
        request: ContestExtractionRequest,
    ) -> ExtractionCorrectionRead: ...

    async def list_corrections_for_submission(
        self, submission_id: uuid.UUID, student_id: uuid.UUID,
    ) -> list[ExtractionCorrectionRead]: ...

    async def confirm_submission(
        self, submission_id: uuid.UUID, student_id: uuid.UUID,
    ) -> SubmissionConfirmationRead: ...


class ExtractionService:
    def __init__(
        self,
        extraction_repository: ExtractionCorrectionRepositoryProtocol,
        submission_repository: SubmissionRepositoryProtocol,
        correction_arbitration_repository: CorrectionArbitrationRepositoryProtocol,
        storage_service: StorageService | None = None,
    ) -> None:
        self._extractions = extraction_repository
        self._submissions = submission_repository
        self._arbitrations = correction_arbitration_repository
        self._storage = storage_service or StorageService()

    async def _to_read(self, correction) -> ExtractionCorrectionRead:
        """
        Convertit un ExtractionCorrection ORM en schema de lecture.

        Bug corrigé (gap "vérification étudiante", trouvé en construisant
        GET .../corrections) : contrairement à ce que documente le module
        submission_schemas.py ("URL SAS déjà résolue par le service avant
        la réponse"), image_url renvoyait jusqu'ici image_crop_path BRUT
        (chemin blob Azure, inutilisable tel quel par un <img src=...>) —
        contest_extraction() est le seul appelant existant de _to_read()
        et n'a jamais résolu l'URL en amont. Corrigé ici, une fois pour
        les deux appelants (contest_extraction et le nouveau list_
        corrections_for_submission ci-dessous).

        async (2026-09-06) : arbitration_verdict nécessite une requête
        supplémentaire (CorrectionArbitration vit sur son propre agrégat,
        jamais une colonne d'ExtractionCorrection) — uniquement quand
        RESOLVED, seul statut où le verdict réel (accepted/rejected)
        distingue un cas de l'autre pour l'étudiant (cf. docstring schema).
        """
        arbitration_verdict = None
        if correction.contestation_status == ContestationStatus.RESOLVED:
            arbitration = await self._arbitrations.get_by_extraction_correction(correction.id)
            if arbitration is not None:
                arbitration_verdict = arbitration.verdict
        return ExtractionCorrectionRead(
            id=correction.id,
            submission_id=correction.submission_id,
            question_id=correction.question_id,
            question_order=None,   # dénormalisé côté frontend (a déjà la liste des questions)
            image_url=self._storage.generate_read_url(
                StorageContainer.SUBMISSIONS, correction.image_crop_path
            ),
            content_type=correction.content_type,
            prediction_ocr=correction.prediction_ocr,
            structured_output=correction.structured_output,
            human_correction=correction.human_correction,
            confidence_score=correction.confidence_score,
            bounding_box=correction.bounding_box,
            evidence_level=correction.evidence_level,
            contestation_status=correction.contestation_status,
            verified_content=correction.verified_content,
            arbitration_verdict=arbitration_verdict,
        )

    async def list_corrections_for_submission(
        self, submission_id: uuid.UUID, student_id: uuid.UUID,
    ) -> list[ExtractionCorrectionRead]:
        """
        Gap fermé (espace étudiant) : l'étudiant n'avait aucun moyen de voir
        CE QUI a été extrait de sa copie avant de confirmer ou contester —
        record_extraction() persiste déjà tout, mais n'était jamais exposé
        en lecture. Self-only, même garde IDOR que contest_extraction.
        """
        submission = await self._submissions.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)
        if submission.student_id != student_id:
            raise ForbiddenError("Un étudiant ne peut consulter que ses propres extractions.")

        corrections = await self._extractions.get_by_submission_id(submission_id)
        # Séquentiel, jamais asyncio.gather : plusieurs requêtes concurrentes
        # sur la MÊME AsyncSession causent des erreurs réelles déjà
        # constatées ailleurs dans ce projet ("Session is already flushing").
        return [await self._to_read(c) for c in corrections]

    async def confirm_submission(
        self, submission_id: uuid.UUID, student_id: uuid.UUID,
    ) -> SubmissionConfirmationRead:
        """
        Gap fermé (pipeline student_evaluation, cf. job_tasks.py — "futur
        endpoint 'je confirme ma copie'", jamais construit jusqu'ici) :
        await_student_verification_node() met le thread LangGraph en pause
        réelle (interrupt()) après l'OCR, en attendant soit une contestation
        (déjà câblée, cf. contest_extraction), soit une confirmation simple
        — mais AUCUN appelant n'a jamais déclenché ce second cas. Sans cet
        endpoint, toute soumission sans erreur d'extraction restait bloquée
        indéfiniment à PENDING_STUDENT_VERIFICATION.

        process_job_resumed.delay(...) (pas resume_thread() directement) :
        ce service tourne dans le contexte sync/async de l'API, jamais dans
        une tâche Celery déjà lancée — même raison que contest_extraction()
        appelle process_contestation_verification.delay(...) plutôt que
        d'attendre le résultat en ligne (la reprise du graph peut prendre du
        temps, jamais dans le cycle requête/réponse HTTP).

        Garde course détectée en écrivant ce module : déposer une
        contestation normale (chemin non-escaladé) ne change PAS
        submission.status — seule l'escalade §2 étape 8 le fait (PENDING_
        ARBITRATION). Sans cette vérification, un étudiant pourrait
        confirmer sa copie pendant qu'une contestation qu'il vient de
        déposer est encore en traitement Celery, résolvant l'interrupt AVANT
        que process_contestation_verification n'ait eu la chance de
        rattraper le même thread (deux resume concurrents sur le même
        thread_id — comportement non spécifié côté LangGraph, jamais risqué
        ici).
        """
        # Verrou consultatif AVANT toute lecture d'état (cf. docstring
        # SubmissionRepositoryProtocol.acquire_advisory_lock — élimine la
        # course avec process_contestation_verification sur le même
        # thread LangGraph) : garantit que si une contestation vient tout
        # juste d'être tranchée AMBIGU par l'autre chemin, cette lecture la
        # voit forcément (l'autre transaction a déjà commité avant que
        # celle-ci n'obtienne le verrou), jamais un état à moitié écrit.
        await self._submissions.acquire_advisory_lock(submission_id)

        submission = await self._submissions.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)
        if submission.student_id != student_id:
            raise ForbiddenError("Un étudiant ne peut confirmer que ses propres soumissions.")
        # Bug réel corrigé (2026-09-06) : PENDING_ARBITRATION/PENDING_EVALUATION
        # acceptés en plus de PENDING_STUDENT_VERIFICATION — quand une
        # contestation est déposée AVANT que l'étudiant ait confirmé (chemin
        # HTTP direct de contest_extraction, jamais rattaché au graph
        # aujourd'hui, cf. docstring contestation_verification_node.py),
        # ArbitrationService.resolve_correction() fait déjà avancer
        # Submission.status jusqu'à PENDING_EVALUATION dès que l'arbitrage
        # est tranché — AVANT que le thread LangGraph n'ait jamais reçu le
        # moindre resume("confirmed"). Sans cet assouplissement, l'étudiant
        # se retrouvait dans une impasse totale : plus aucun état de
        # soumission ne permettait jamais de confirmer, la notation ne
        # démarrant jamais. Le garde-fou réel reste ci-dessous (aucune
        # contestation encore PENDING_VERIFICATION/AMBIGU) — un double
        # resume("confirmed") sur un thread déjà repris est un no-op sans
        # risque (même principe déjà documenté pour la course symétrique).
        if submission.status not in (
            SubmissionStatus.PENDING_STUDENT_VERIFICATION,
            SubmissionStatus.PENDING_ARBITRATION,
            SubmissionStatus.PENDING_EVALUATION,
        ):
            raise SubmissionNotPendingVerificationError(submission_id, submission.status.value)

        corrections = await self._extractions.get_by_submission_id(submission_id)
        if any(
            c.contestation_status in (ContestationStatus.PENDING_VERIFICATION, ContestationStatus.AMBIGU)
            for c in corrections
        ):
            raise ConflictError(
                f"La soumission {submission_id} a au moins une contestation en cours de "
                "traitement — confirmation impossible avant sa résolution"
            )

        try:
            process_job_resumed.delay(thread_id=str(submission_id), resume_value="confirmed")
        except BrokerOperationalError as exc:
            logger.error(
                "Échec de dispatch process_job_resumed (broker Celery injoignable) pour "
                "submission_id=%s : %s", submission_id, exc, exc_info=True,
            )
            raise SubmissionResumeDispatchError(submission_id) from exc

        return SubmissionConfirmationRead(submission_id=submission_id, status=submission.status)

    async def record_extraction(
        self,
        submission_id: uuid.UUID,
        blocks: list[dict],
    ) -> list[ExtractionCorrectionRead]:
        """
        Persiste tous les blocs OCR pour une soumission.
        Valide l'existence de la soumission — lève SubmissionNotFoundError sinon.
        """
        submission = await self._submissions.get_by_id(submission_id)
        if submission is None:
            raise SubmissionNotFoundError(submission_id)

        corrections = await self._extractions.bulk_create_for_submission(
            submission_id=submission_id,
            blocks=blocks,
        )
        return [await self._to_read(c) for c in corrections]

    async def contest_extraction(
        self,
        submission_id: uuid.UUID,
        correction_id: uuid.UUID,
        student_id: uuid.UUID,
        request: ContestExtractionRequest,
    ) -> ExtractionCorrectionRead:
        """Enregistre la contestation d'une extraction par un étudiant — cf. docstring du module."""
        correction = await self._extractions.get_by_id(correction_id)
        if correction is None:
            raise ExtractionNotFoundError(correction_id)

        # IDOR : la correction doit appartenir à une soumission de cet étudiant.
        submission = await self._submissions.get_by_id(correction.submission_id)
        if submission is None or submission.student_id != student_id:
            raise ExtractionNotOwnedByStudentError(correction_id, student_id)
        # Cohérence de l'URL imbriquée (pas un contrôle de sécurité en soi —
        # l'IDOR est déjà couvert ci-dessus — mais une correction_id valide
        # pour un submission_id différent dans l'URL indique une requête
        # incohérente, rejetée plutôt que silencieusement acceptée).
        if correction.submission_id != submission_id:
            raise ExtractionNotOwnedByStudentError(correction_id, student_id)

        # §2 étape 3 — réclamation vide ou identique au contenu déjà extrait.
        if request.contestation_type == ContestationType.CONTENT:
            if self._is_trivial_or_identical(request.claimed_content, correction.prediction_ocr):
                raise TrivialContestationError(correction_id)
        elif (
            request.contestation_type == ContestationType.STRUCTURE_ELEMENT
            and request.contested_element_id != WHOLE_STRUCTURE_ELEMENT_ID
        ):
            existing_element = ContestationVerificationAgent._locate_structure_element(
                correction.structured_output, request.contested_element_id or ""
            )
            if existing_element is not None and self._is_trivial_or_identical(
                request.claimed_content, existing_element
            ):
                raise TrivialContestationError(correction_id)

        status = correction.contestation_status
        if status == ContestationStatus.RESOLVED:
            raise ContestationOnResolvedBlockError(correction_id)
        if status in (ContestationStatus.PENDING_VERIFICATION, ContestationStatus.AMBIGU):
            raise ContestationAlreadyInProgressError(correction_id)
        if status in (ContestationStatus.IMPLAUSIBLE, ContestationStatus.PLAUSIBLE):
            # §2 étape 8 — jamais un second passage automatique par l'agent,
            # quelle que soit la nouvelle justification apportée : escalade
            # directe au professeur.
            await self._extractions.apply_contestation_verdict(
                correction_id=correction_id,
                contestation_status=ContestationStatus.AMBIGU,
                verified_content=correction.verified_content,
                confidence_score=None,
            )
            await self._arbitrations.create_pending(correction_id)
            await self._submissions.update_status(submission_id, SubmissionStatus.PENDING_ARBITRATION)
            updated = await self._extractions.get_by_id(correction_id)
            return await self._to_read(updated)

        # Dépôt normal (jamais contesté jusqu'ici). fusion_claim (Cas D)
        # n'est volontairement pas persisté séparément — entièrement
        # déterminé par l'état de fusion du bloc, re-dérivé au traitement
        # (cf. ContestationVerificationService._infer_fusion_claim).
        updated = await self._extractions.file_contestation(
            correction_id=correction_id,
            contestation_type=request.contestation_type,
            claimed_content=request.claimed_content,
            contested_element_id=request.contested_element_id,
            claimed_question_id=request.claimed_question_id,
            claimed_section_id=request.claimed_section_id,
        )
        try:
            process_contestation_verification.delay(submission_id=str(submission_id))
        except BrokerOperationalError as exc:
            logger.error(
                "Échec de dispatch process_contestation_verification (broker Celery "
                "injoignable) pour submission_id=%s : %s", submission_id, exc, exc_info=True,
            )
            raise SubmissionResumeDispatchError(submission_id) from exc
        return await self._to_read(updated)

    @staticmethod
    def _is_trivial_or_identical(claimed: str | None, existing: str) -> bool:
        if not claimed or not claimed.strip():
            return True
        normalize = lambda s: " ".join(s.strip().lower().split())
        return normalize(claimed) == normalize(existing)
