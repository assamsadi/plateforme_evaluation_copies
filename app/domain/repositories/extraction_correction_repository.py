"""
Repository ExtractionCorrection.

Opérations centrales :
- bulk_create_for_submission : persiste en une seule transaction tous les blocs
  OCR produits pour une soumission (appelé par extraction_service.record_extraction).
- get_by_submission_id : récupère tous les blocs d'une soumission, trié par
  question_id puis bounding_box pour un affichage cohérent.
- update_human_correction : HITL étudiant — trace la correction humaine après
  contestation validée par le VLM (vlm_verification_agent, §4 CHAABI).
- apply_contestation_verdict / apply_fusion_verdict : persistance des verdicts
  de Contestation_Verification_Agent (contestation_verification_service.py).
  Séparées en deux méthodes car le Cas D (fusion) touche potentiellement
  plusieurs lignes en une seule transaction (§6/§10 du doc de référence
  agent), contrairement aux Cas A/B/C qui restent toujours mono-ligne.
- file_contestation : intake d'une contestation étudiante (extraction_service.
  contest_extraction), pose contestation_status=PENDING_VERIFICATION — c'est
  cette écriture qui rend un bloc éligible à process_pending_contestations().
"""
import uuid
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
    ExtractionCorrection,
    ExtractionContentType,
    ExtractionEvidenceLevel,
)


class ExtractionCorrectionRepositoryProtocol(Protocol):
    async def bulk_create_for_submission(
        self,
        submission_id: uuid.UUID,
        blocks: list[dict],
    ) -> list[ExtractionCorrection]: ...

    async def get_by_submission_id(
        self, submission_id: uuid.UUID
    ) -> list[ExtractionCorrection]: ...

    async def get_by_id(
        self, correction_id: uuid.UUID
    ) -> ExtractionCorrection | None: ...

    async def bulk_update_attachments(
        self,
        submission_id: uuid.UUID,
        attachments: list[dict],
    ) -> list[ExtractionCorrection]: ...

    async def update_human_correction(
        self,
        correction_id: uuid.UUID,
        human_correction: str,
    ) -> ExtractionCorrection | None: ...

    async def apply_contestation_verdict(
        self,
        correction_id: uuid.UUID,
        contestation_status: ContestationStatus,
        verified_content: str | None,
        confidence_score: Decimal | None,
        resolved_question_id: uuid.UUID | None = None,
    ) -> ExtractionCorrection | None: ...

    async def apply_fusion_verdict(
        self,
        group_ids: list[uuid.UUID],
        defusion_applied: bool,
        contestation_status: ContestationStatus,
        confidence_score: Decimal | None,
    ) -> list[ExtractionCorrection]: ...

    async def file_contestation(
        self,
        correction_id: uuid.UUID,
        contestation_type: ContestationType,
        claimed_content: str | None,
        contested_element_id: str | None,
        claimed_question_id: uuid.UUID | None,
        claimed_section_id: uuid.UUID | None,
    ) -> ExtractionCorrection | None: ...


class SQLAlchemyExtractionCorrectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create_for_submission(
        self,
        submission_id: uuid.UUID,
        blocks: list[dict],
    ) -> list[ExtractionCorrection]:
        """
        Persiste tous les blocs OCR d'une soumission en une seule opération —
        upsert par (submission_id, image_crop_path), jamais un INSERT pur :
        image_crop_path est déjà la clé naturelle déterministe par bloc
        (utilisée pour corréler dans bulk_update_attachments) ; pas de
        colonne block_order_index sur ce modèle pour servir de clé
        alternative. Un redéclenchement de la pipeline OCR pour la même
        soumission (retry Celery hors reprise de graph, par ex.) met donc à
        jour les lignes existantes au lieu d'en dupliquer.

        Chaque bloc dict doit contenir :
          - image_crop_path (str)
          - page_number (int | None) — nécessaire à Contestation_Verification_Agent
            pour ré-imprimer la page en pleine résolution (Cas A/C)
          - content_type (ExtractionContentType | str)
          - prediction_ocr (str)
          - confidence_score (Decimal)
          - bounding_box (dict)
          - evidence_level (ExtractionEvidenceLevel | str)
          - question_id (uuid.UUID | None) — None si bloc ORPHELIN
          - structured_output (dict | None) — optionnel
        """
        existing_by_crop_path = {
            c.image_crop_path: c for c in await self.get_by_submission_id(submission_id)
        }

        corrections = []
        for block in blocks:
            existing = existing_by_crop_path.get(block["image_crop_path"])
            if existing is not None:
                existing.question_id = block.get("question_id")
                existing.page_number = block.get("page_number")
                existing.content_type = ExtractionContentType(block["content_type"])
                existing.prediction_ocr = block["prediction_ocr"]
                existing.structured_output = block.get("structured_output")
                existing.confidence_score = Decimal(str(block["confidence_score"]))
                existing.bounding_box = block["bounding_box"]
                existing.evidence_level = ExtractionEvidenceLevel(block["evidence_level"])
                corrections.append(existing)
                continue

            correction = ExtractionCorrection(
                submission_id=submission_id,
                question_id=block.get("question_id"),
                image_crop_path=block["image_crop_path"],
                page_number=block.get("page_number"),
                content_type=ExtractionContentType(block["content_type"]),
                prediction_ocr=block["prediction_ocr"],
                structured_output=block.get("structured_output"),
                confidence_score=Decimal(str(block["confidence_score"])),
                bounding_box=block["bounding_box"],
                evidence_level=ExtractionEvidenceLevel(block["evidence_level"]),
            )
            self._session.add(correction)
            corrections.append(correction)
        await self._session.flush()
        return corrections

    async def get_by_submission_id(
        self, submission_id: uuid.UUID
    ) -> list[ExtractionCorrection]:
        result = await self._session.execute(
            select(ExtractionCorrection)
            .where(ExtractionCorrection.submission_id == submission_id)
            .order_by(
                ExtractionCorrection.question_id.nulls_last(),
                ExtractionCorrection.created_at,
            )
        )
        return list(result.scalars().all())

    async def get_by_id(
        self, correction_id: uuid.UUID
    ) -> ExtractionCorrection | None:
        return await self._session.get(ExtractionCorrection, correction_id)

    async def bulk_update_attachments(
        self,
        submission_id: uuid.UUID,
        attachments: list[dict],
    ) -> list[ExtractionCorrection]:
        """
        `fused_crop_paths`, s'il est présent sur un item, référence les
        image_crop_path des blocs consommés par une fusion de continuité
        (Question_Attachment_Agent, étape -1). Sans ce câblage, ces lignes
        restaient orphelines pour toujours (question_id jamais posé) —
        corrigé ici : elles reçoivent le même rattachement que le bloc
        fusionné survivant, et celui-ci trace leurs ids dans
        fused_extraction_correction_ids (nécessaire à
        Contestation_Verification_Agent, Cas D, pour retrouver et
        défusionner un désaccord sur la fusion elle-même).
        """
        if not attachments:
            return []

        corrections = await self.get_by_submission_id(submission_id)
        by_crop_path = {c.image_crop_path: c for c in corrections}
        updated: list[ExtractionCorrection] = []

        for item in attachments:
            correction = by_crop_path.get(item["image_crop_path"])
            if correction is None:
                continue
            correction.question_id = item.get("question_id")
            correction.evidence_level = ExtractionEvidenceLevel(item["evidence_level"])
            updated.append(correction)

            fused_crop_paths = item.get("fused_crop_paths")
            if fused_crop_paths:
                fused_ids = []
                for consumed_crop_path in fused_crop_paths:
                    consumed = by_crop_path.get(consumed_crop_path)
                    if consumed is None:
                        continue
                    consumed.question_id = correction.question_id
                    consumed.evidence_level = correction.evidence_level
                    fused_ids.append(str(consumed.id))
                    if consumed not in updated:
                        updated.append(consumed)
                correction.fused_extraction_correction_ids = fused_ids or None

        await self._session.flush()
        return updated

    async def update_human_correction(
        self,
        correction_id: uuid.UUID,
        human_correction: str,
    ) -> ExtractionCorrection | None:
        correction = await self.get_by_id(correction_id)
        if correction is None:
            return None
        correction.human_correction = human_correction
        await self._session.flush()
        return correction

    async def apply_contestation_verdict(
        self,
        correction_id: uuid.UUID,
        contestation_status: ContestationStatus,
        verified_content: str | None,
        confidence_score: Decimal | None,
        resolved_question_id: uuid.UUID | None = None,
    ) -> ExtractionCorrection | None:
        """
        Cas A/B/C — une seule ligne. confidence_score=None (verdict AMBIGU,
        §7) laisse la colonne intacte, jamais remise à zéro/écrasée.

        Bug réel corrigé (2026-09-06, test réel — contestation ATTACHMENT sur
        un bloc orphelin) : un verdict PLAUSIBLE de Cas B (ATTACHMENT) ne
        touchait jamais question_id/evidence_level — le bloc restait orphelin
        pour toujours malgré un rattachement pourtant tranché par l'agent
        (resolved_question_id renseigné dans le verdict, jamais lu ici avant
        ce correctif). Seul le Cas AMBIGU était câblé (CorrectionArbitration,
        cf. contestation_verification_service.py::_persist_verdict) — un
        verdict PLAUSIBLE ne nécessite aucune décision professeur, donc
        aucune activation prévue ailleurs pour appliquer resolved_question_id.
        """
        correction = await self.get_by_id(correction_id)
        if correction is None:
            return None
        correction.contestation_status = contestation_status
        correction.verified_content = verified_content
        if confidence_score is not None:
            correction.confidence_score = confidence_score
        if resolved_question_id is not None:
            correction.question_id = resolved_question_id
            correction.evidence_level = ExtractionEvidenceLevel.CONTENU_VS_REFERENCE
        await self._session.flush()
        return correction

    async def apply_fusion_verdict(
        self,
        group_ids: list[uuid.UUID],
        defusion_applied: bool,
        contestation_status: ContestationStatus,
        confidence_score: Decimal | None,
    ) -> list[ExtractionCorrection]:
        """
        Cas D — transaction unique sur toutes les lignes du groupe (§6/§10) :
        soit toutes défusionnées, soit toutes confirmées/re-fusionnées, jamais
        une fusion partiellement défaite.

        defusion_applied=True  -> fused_extraction_correction_ids vidé sur
            chaque ligne du groupe (chacune redevient une unité indépendante).
        defusion_applied=False -> fused_extraction_correction_ids reposé sur
            le survivant (premier par page puis id, même convention que
            Question_Attachment_Agent), référençant le reste du groupe —
            couvre à la fois la fusion confirmée et la fusion rétroactive.
        """
        corrections = []
        for correction_id in group_ids:
            correction = await self.get_by_id(correction_id)
            if correction is not None:
                corrections.append(correction)

        if not corrections:
            return []

        if defusion_applied:
            for correction in corrections:
                correction.fused_extraction_correction_ids = None
        else:
            survivor = min(corrections, key=lambda c: (c.page_number or 0, str(c.id)))
            survivor.fused_extraction_correction_ids = [
                str(c.id) for c in corrections if c.id != survivor.id
            ] or None

        for correction in corrections:
            correction.contestation_status = contestation_status
            if confidence_score is not None:
                correction.confidence_score = confidence_score

        await self._session.flush()
        return corrections

    async def file_contestation(
        self,
        correction_id: uuid.UUID,
        contestation_type: ContestationType,
        claimed_content: str | None,
        contested_element_id: str | None,
        claimed_question_id: uuid.UUID | None,
        claimed_section_id: uuid.UUID | None,
    ) -> ExtractionCorrection | None:
        """
        Intake — pose contestation_status=PENDING_VERIFICATION, rendant le
        bloc éligible à process_pending_contestations(). claimed_content est
        écrit dans human_correction (Cas A/C — réutilisé tel quel par
        ContestationVerificationAgent comme claimed_content, §9bis : jamais
        écrasé après ce point par la suite du traitement).
        """
        correction = await self.get_by_id(correction_id)
        if correction is None:
            return None
        correction.contestation_type = contestation_type
        correction.contestation_status = ContestationStatus.PENDING_VERIFICATION
        correction.human_correction = claimed_content
        correction.contested_element_id = contested_element_id
        correction.claimed_question_id = claimed_question_id
        correction.claimed_section_id = claimed_section_id
        await self._session.flush()
        return correction
