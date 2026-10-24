"""
Repository CorrectionArbitration.

EXCEPTION documentée à la règle DDD stricte (1 repository = 1 agrégat) :
create_and_apply_verdict() touche aussi ExtractionCorrection (qui
appartient à l'agrégat Submission), car le verdict et la mise à jour de
l'extraction doivent être ATOMIQUES — si le verdict est ACCEPTED, la
correction humaine doit être appliquée dans la MÊME transaction, sinon
un crash entre les deux laisserait un état incohérent (verdict enregistré
mais correction non appliquée, ou l'inverse). C'est un compromis assumé :
la pureté architecturale cède face à une exigence de cohérence réelle.

create_pending() / create_and_apply_verdict() forment le cycle complet
d'une ligne : create_pending crée la ligne PENDING dès que l'agent tranche
AMBIGU (teacher_arbitration_node) ; create_and_apply_verdict RÉSOUT cette
même ligne (jamais une nouvelle ligne en double) quand le professeur décide
— si aucune ligne PENDING n'existe déjà (cas défensif, ne devrait pas
arriver en usage normal), une est créée directement au moment de la
résolution plutôt que d'échouer.
"""
import uuid
from typing import Protocol

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.correction_arbitration import (
    ArbitrationStatus,
    ArbitrationVerdict,
    CorrectionArbitration,
)
from app.domain.models.assessment.exercise import Exercise
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
    ExtractionCorrection,
)
from app.domain.models.assessment.submission import Submission
from app.domain.models.shared.constants import CONTESTATION_RESOLVED_CONFIDENCE_SCORE


class CorrectionArbitrationRepositoryProtocol(Protocol):
    async def get_by_id(self, arbitration_id: uuid.UUID) -> CorrectionArbitration | None: ...
    async def get_by_extraction_correction(
        self, extraction_correction_id: uuid.UUID
    ) -> CorrectionArbitration | None: ...
    async def create_pending(
        self, extraction_correction_id: uuid.UUID
    ) -> CorrectionArbitration: ...
    async def create_and_apply_verdict(
        self,
        extraction_correction_id: uuid.UUID,
        teacher_professor_id: uuid.UUID,
        verdict: ArbitrationVerdict,
        comment: str | None,
        claimed_correction: str,
    ) -> CorrectionArbitration: ...
    async def has_pending_for_submission(self, submission_id: uuid.UUID) -> bool: ...
    async def list_pending_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[CorrectionArbitration]: ...
    async def list_all_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[CorrectionArbitration]: ...
    async def list_by_student_for_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID
    ) -> list[CorrectionArbitration]: ...


class SQLAlchemyCorrectionArbitrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, arbitration_id: uuid.UUID) -> CorrectionArbitration | None:
        return await self._session.get(CorrectionArbitration, arbitration_id)

    async def get_by_extraction_correction(
        self, extraction_correction_id: uuid.UUID
    ) -> CorrectionArbitration | None:
        result = await self._session.execute(
            select(CorrectionArbitration)
            .where(
                CorrectionArbitration.extraction_correction_id == extraction_correction_id
            )
            .order_by(CorrectionArbitration.created_at.desc())
        )
        return result.scalars().first()

    async def create_pending(
        self, extraction_correction_id: uuid.UUID
    ) -> CorrectionArbitration:
        """
        §2 étape 6 — créée dès qu'un verdict AMBIGU tombe. teacher_professor_id/
        verdict/comment restent NULL jusqu'à la résolution (create_and_apply_verdict).
        """
        arbitration = CorrectionArbitration(
            extraction_correction_id=extraction_correction_id,
            status=ArbitrationStatus.PENDING,
        )
        self._session.add(arbitration)
        await self._session.flush()
        return arbitration

    async def create_and_apply_verdict(
        self,
        extraction_correction_id: uuid.UUID,
        teacher_professor_id: uuid.UUID,
        verdict: ArbitrationVerdict,
        comment: str | None,
        claimed_correction: str,
    ) -> CorrectionArbitration:
        arbitration = await self.get_by_extraction_correction(extraction_correction_id)
        if arbitration is None:
            # Défensif : en usage normal, create_pending() a toujours déjà
            # créé cette ligne (§2 étape 6) — ne bloque pas une résolution
            # directe si, pour une raison quelconque, elle est absente.
            arbitration = CorrectionArbitration(extraction_correction_id=extraction_correction_id)
            self._session.add(arbitration)

        arbitration.teacher_professor_id = teacher_professor_id
        arbitration.verdict = verdict
        arbitration.comment = comment
        arbitration.status = ArbitrationStatus.RESOLVED

        extraction = await self._session.get(ExtractionCorrection, extraction_correction_id)
        if extraction is not None:
            if verdict == ArbitrationVerdict.ACCEPTED:
                if extraction.contestation_type == ContestationType.ATTACHMENT:
                    # Bug réel corrigé (2026-09-05, test réel FR/ES) : accepter
                    # une contestation ATTACHMENT ne posait jusqu'ici jamais
                    # question_id = claimed_question_id — le bloc restait
                    # orphelin indéfiniment quelle que soit la décision du
                    # professeur, malgré un verdict ACCEPTED enregistré.
                    # claimed_correction n'a pas de sens pour ce cas (rien à
                    # transcrire), jamais posé sur verified_content ici.
                    extraction.question_id = extraction.claimed_question_id
                else:
                    # human_correction reste la réclamation ORIGINALE de l'étudiant,
                    # jamais écrasée (§9bis) — la décision du professeur devient la
                    # nouvelle vérité dans verified_content, un champ distinct.
                    extraction.verified_content = claimed_correction
            # §7 — la décision humaine devient la nouvelle source de vérité,
            # qu'elle confirme (ACCEPTED) ou infirme (REJECTED) l'étudiant :
            # confidence_score relevé et contestation_status marqué RESOLVED
            # dans les deux cas.
            extraction.contestation_status = ContestationStatus.RESOLVED
            extraction.confidence_score = CONTESTATION_RESOLVED_CONFIDENCE_SCORE

        await self._session.flush()
        return arbitration

    async def has_pending_for_submission(self, submission_id: uuid.UUID) -> bool:
        """
        Câblage teacher_arbitration_node (2026-08-18) — ArbitrationService.
        resolve_correction() appelle ceci APRÈS create_and_apply_verdict()
        pour décider si la soumission peut reprendre : une soumission peut
        porter plusieurs ExtractionCorrection AMBIGUËS simultanément (chacune
        sa propre CorrectionArbitration), la reprise du thread LangGraph ne
        doit se déclencher que quand PLUS AUCUNE ne reste PENDING — jamais
        dès la première résolue. Jointure sur ExtractionCorrection.
        submission_id (CorrectionArbitration ne porte que extraction_
        correction_id, jamais le submission_id directement).
        """
        result = await self._session.execute(
            select(CorrectionArbitration.id)
            .join(
                ExtractionCorrection,
                CorrectionArbitration.extraction_correction_id == ExtractionCorrection.id,
            )
            .where(
                ExtractionCorrection.submission_id == submission_id,
                CorrectionArbitration.status == ArbitrationStatus.PENDING,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_pending_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[CorrectionArbitration]:
        """
        Gap trouvé lors de l'audit arbitrage : aucune file de découverte
        n'existait pour les corrections AMBIGUËS en attente d'un verdict
        professeur — /arbitrations/corrections/{id}/resolve exigeait déjà
        l'ID, jamais fourni par aucune liste. Jointure CorrectionArbitration
        -> ExtractionCorrection -> Submission -> Exercise pour scoper au
        professeur créateur de l'exercice concerné.
        """
        result = await self._session.execute(
            select(CorrectionArbitration)
            .join(
                ExtractionCorrection,
                CorrectionArbitration.extraction_correction_id == ExtractionCorrection.id,
            )
            .join(Submission, ExtractionCorrection.submission_id == Submission.id)
            .join(Exercise, Submission.exercise_id == Exercise.id)
            .where(
                Exercise.created_by_professor_id == professor_id,
                CorrectionArbitration.status == ArbitrationStatus.PENDING,
            )
            .order_by(CorrectionArbitration.created_at)
        )
        return list(result.scalars().all())

    async def list_all_for_professor(
        self, professor_id: uuid.UUID
    ) -> list[CorrectionArbitration]:
        """
        Traçabilité réelle (2026-09-06, gap signalé) : list_pending_for_
        professor ne renvoie QUE les PENDING — la ligne d'un étudiant
        disparaissait ENTIÈREMENT du tableau principal une fois toutes ses
        contestations tranchées, sans aucun moyen d'y revenir (même le
        détail par étudiant devenait inatteignable, plus aucune ligne pour
        y accéder). Même jointure/scoping, jamais filtré par statut — sert
        de base à la liste principale ET au détail par étudiant.
        """
        result = await self._session.execute(
            select(CorrectionArbitration)
            .join(
                ExtractionCorrection,
                CorrectionArbitration.extraction_correction_id == ExtractionCorrection.id,
            )
            .join(Submission, ExtractionCorrection.submission_id == Submission.id)
            .join(Exercise, Submission.exercise_id == Exercise.id)
            .where(Exercise.created_by_professor_id == professor_id)
            .order_by(CorrectionArbitration.created_at)
        )
        return list(result.scalars().all())

    async def list_by_student_for_professor(
        self, professor_id: uuid.UUID, student_id: uuid.UUID
    ) -> list[CorrectionArbitration]:
        """
        Historique COMPLET (PENDING + RESOLVED, jamais filtré par statut) des
        arbitrages d'un étudiant précis — traçabilité réelle demandée
        (2026-09-06) : la file de découverte (list_pending_for_professor)
        ne montre QUE les PENDING par construction ; une fois résolue, une
        contestation en disparaissait, sans aucune trace persistante
        consultable après rechargement de page (un suivi local côté
        frontend ne survit pas à un refresh). Même jointure/scoping que
        list_pending_for_professor, juste sans le filtre de statut.
        """
        result = await self._session.execute(
            select(CorrectionArbitration)
            .join(
                ExtractionCorrection,
                CorrectionArbitration.extraction_correction_id == ExtractionCorrection.id,
            )
            .join(Submission, ExtractionCorrection.submission_id == Submission.id)
            .join(Exercise, Submission.exercise_id == Exercise.id)
            .where(
                Exercise.created_by_professor_id == professor_id,
                Submission.student_id == student_id,
            )
            .order_by(CorrectionArbitration.created_at)
        )
        return list(result.scalars().all())