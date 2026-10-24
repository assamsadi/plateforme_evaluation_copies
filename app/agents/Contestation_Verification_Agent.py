"""
Agent — Contestation_Verification_Agent (Version définitive)

Arbitre un désaccord entre l'extraction produite par OCR_Extraction_Agent /
Question_Attachment_Agent et la réclamation d'un étudiant, un bloc contesté à
la fois. Ne juge jamais la qualité pédagogique de la réponse.

4 cas distincts, jamais un champ texte libre unique (cf. ContestExtractionRequest,
app/domain/schemas/contestation_schemas.py) :
  A. CONTENT           — la transcription est en cause (OCR2 en pleine résolution).
  B. ATTACHMENT        — le rattachement question et/ou section est en cause.
  C. STRUCTURE_ELEMENT — un élément interne d'une STRUCTURE, ou la structure entière.
  D. FUSION            — la fusion de continuité elle-même (Question_Attachment_Agent
                          étape -1), pas son contenu ni son rattachement.

La relecture OCR2 (Cas A/C-élément) réutilise le schéma et les prompts
"à l'aveugle" d'OCR_Extraction_Agent — même opération exacte, aucune information
sur OCR1 ni sur la réclamation étudiante n'entre jamais dans ce prompt (§2 étape 5).

Hors du périmètre de ce fichier, porté par la couche service/nœud à venir :
  - §8 anti-abus : appelé AVANT l'invocation de l'agent (exceeds_abuse_threshold
    est exposé ici comme utilitaire, mais la décision de ne pas invoquer l'agent
    reste à l'appelant).
  - §9ter priorité de traitement : sort_cases_by_priority est exposé ici comme
    utilitaire de tri, l'orchestration réelle (plusieurs contestations sur le
    même bloc) reste à l'appelant.
  - §9quater équité rétroactive, §10 rappel/escalade professeur : nécessitent une
    visibilité inter-soumissions/inter-étudiants que cet agent, exécuté un bloc à
    la fois, n'a pas — portés par arbitration_service.py / un job de fond.
  - Persistance (ExtractionCorrection, CorrectionArbitration, AgentDecisionLog) :
    cet agent retourne un ContestationVerdict pur, jamais d'écriture en base
    lui-même (même principe que Question_Attachment_Agent). Il calcule et
    renvoie confidence_score (§7, valeur proposée pour la colonne du même nom)
    car c'est une décision qui découle directement de la logique de verdict
    déjà portée ici — mais ne l'écrit jamais lui-même.
"""
import base64
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.agents.context import AgentExecutionContext
from app.agents.contestation_verification_exceptions import (
    AlreadyResolvedContestationError,
    ContestationSchemaError,
    FusionGroupNotFoundError,
    StructureElementNotFoundError,
)
from app.agents.OCR_Extraction_Agent import PageExtractionResult
from app.agents.ocr_block_utils import structure_to_flat_text
from app.agents.ocr_image_utils import crop_region, prepare_document_pages
from app.agents.question_attachment_exceptions import MissingReferenceSolutionError
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
    ExtractionContentType,
    StructureType,
)
from app.domain.schemas.contestation_schemas import ContestationVerdict, ContestExtractionRequest
from app.infra_services.storage_paths import contestation_reread_crop_path
from app.infra_services.storage_service import StorageContainer, storage_service
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType
from app.observability.langfuse import AgentTraceSpan
from app.prompts.contestation_verification_prompt import (
    ATTACHMENT_ARBITRATION_SYSTEM_PROMPT,
    ATTACHMENT_ARBITRATION_USER_TEMPLATE,
    CONTENT_CONFIRMATION_SYSTEM_PROMPT,
    CONTENT_CONFIRMATION_USER_TEMPLATE,
    STRUCTURE_RECONSTRUCTION_COMPARISON_SYSTEM_PROMPT,
    STRUCTURE_RECONSTRUCTION_COMPARISON_USER_TEMPLATE,
)
from app.prompts.ocr_extraction_prompt import OCR_RE_READ_SYSTEM_PROMPT, OCR_RE_READ_USER_TEMPLATE

logger = logging.getLogger(__name__)

# Convention d'adressage §5 Cas C — "toute la structure" plutôt qu'un élément
# précis (aucun des deux ne peut se confondre avec un vrai id d'élément, qui
# ne commence jamais par "__").
WHOLE_STRUCTURE_ELEMENT_ID = "__STRUCTURE__"

# §8 — seuil par défaut du garde-fou anti-abus (proportion de blocs contestés).
CONTESTED_RATIO_ABUSE_THRESHOLD = 0.5

# §7 — confidence_score attribué à un verdict PLAUSIBLE/IMPLAUSIBLE tranché
# sans signal numérique naturel (heuristique déterministe Cas D, ou fallback
# si le LLM omet son propre "confidence" en Cas B).
CONTESTATION_RESOLVED_CONFIDENCE_SCORE = 0.95

# Marge de recadrage (Cas A/C, cf. crop_region) — trouvé nécessaire sur test
# réel le 2026-08-18 : un bounding_box rapporté par OCR_Extraction_Agent
# peut être trop serré (ex. hauteur sous-estimée pour un paragraphe
# manuscrit multi-lignes), coupant le contenu même que la relecture "à
# l'aveugle" doit vérifier — produisant un AMBIGU artificiel (rien vu)
# plutôt qu'un vrai verdict. 5% de chaque dimension de page, de chaque côté.
REREAD_CROP_PADDING_RATIO = 0.05


# ---------------------------------------------------------------------------
# Schémas de sortie structurée pour les 2 appels LLM texte-seul de cet agent
# (2026-08-18) — remplacent l'ancien response_schema=None + regex JSON
# (_parse_json_verdict, re.search(r"\{.*\}", ...) + json.loads), même bug
# déjà trouvé et corrigé cette session sur 4 autres agents (Document_
# Structuring_Agent, Extraction_Verification_Agent, Reasoning_Graph_Agent,
# Solution_Variant_Generation_Agent) : fragile face au LaTeX/JSON imbriqué,
# jamais testé en réel sur cet agent jusqu'ici.
# ---------------------------------------------------------------------------

class _AttachmentArbitrationSchema(BaseModel):
    """Cas B — arbitrage LLM de rattachement (ATTACHMENT_ARBITRATION_*)."""
    verdict: Literal["STUDENT_HYPOTHESIS_CONFIRMED", "ORIGINAL_CONFIRMED", "AMBIGU"]
    # Défaut = CONTESTATION_RESOLVED_CONFIDENCE_SCORE (0.95), pas 0.5 —
    # préserve exactement le comportement de repli d'avant ce fix
    # (`parsed.get("confidence", CONTESTATION_RESOLVED_CONFIDENCE_SCORE)`,
    # cf. §7) si le LLM omet le champ malgré le schéma structuré.
    confidence: float = Field(ge=0.0, le=1.0, default=CONTESTATION_RESOLVED_CONFIDENCE_SCORE)
    justification: str


class _StructureComparisonSchema(BaseModel):
    """Cas C (structure entière) — comparaison de reconstructions (STRUCTURE_RECONSTRUCTION_COMPARISON_*)."""
    verdict: Literal["CLAIMED_CONFIRMED", "ORIGINAL_CONFIRMED", "AMBIGU"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    justification: str


class _ContentConfirmationSchema(BaseModel):
    """
    Cas A / Cas C-élément — jugement LLM ciblé de la table de vérité §3
    (2026-08-18, CONTENT_CONFIRMATION_*) : remplace fuzz.ratio/partial_ratio,
    trouvés incapables de distinguer un désaccord ponctuel (une valeur/un mot)
    noyé dans un long paragraphe par ailleurs identique — aucun seuil de
    similarité globale ne peut faire cette distinction, peu importe la
    métrique. `confirms` est un jugement direct sur le point disputé, jamais
    un score.
    """
    confirms: Literal["ORIGINAL", "CLAIMED", "BOTH", "NEITHER"]
    justification: str


# ---------------------------------------------------------------------------
# Structures d'échange
# ---------------------------------------------------------------------------

@dataclass
class ExtractionCorrectionSnapshot:
    """Vue en lecture d'un ExtractionCorrection, suffisante pour l'arbitrage."""
    id: uuid.UUID
    submission_id: uuid.UUID
    image_crop_path: str
    content_type: ExtractionContentType
    prediction_ocr: str
    bounding_box: dict
    evidence_level: str
    question_id: uuid.UUID | None = None
    page_number: int | None = None
    structure_type: StructureType | None = None
    structured_output: dict | None = None
    human_correction: str | None = None
    contestation_status: ContestationStatus | None = None
    # Renseigné uniquement sur le bloc survivant d'une fusion de continuité
    # (Question_Attachment_Agent, étape -1) — cf. Cas D.
    fused_extraction_correction_ids: list[uuid.UUID] | None = None


@dataclass
class QuestionCandidate:
    """Question candidate pour le Cas B, avec sa SolutionVariant de référence."""
    question_id: uuid.UUID
    exercise_id: uuid.UUID
    order: int                  # Question.order — GLOBAL à l'exercice, JAMAIS ce que
                                 # l'étudiant voit dès qu'il y a ≥2 sections (même bug
                                 # que Question_Attachment_Agent.QuestionRef, corrigé
                                 # ici de la même façon — cf. position_in_section).
    reference_content: str
    section_id: uuid.UUID | None = None
    section_order: int | None = None
    section_title: str | None = None
    reference_summary: str | None = None
    # rang 1-based parmi les questions de la même section (trié par order) —
    # c'est CE numéro que l'étudiant écrit ("Question 1" de la section 2 ≠
    # Question globale n°1). None si pas de section (alors `order` fait
    # référence) ou si l'appelant ne le renseigne pas.
    position_in_section: int | None = None


@dataclass
class ContestationCaseInput:
    """
    Entrée complète pour une contestation. `fusion_group` (Cas D
    'wrongly_merged') doit contenir le bloc survivant ET tous les blocs
    référencés par fused_extraction_correction_ids. `submission_blocks`
    (Cas D 'should_have_merged') doit contenir tous les autres blocs de la
    soumission, candidats à une fusion rétroactive.
    """
    contested: ExtractionCorrectionSnapshot
    request: ContestExtractionRequest
    document_bytes: bytes | None = None
    document_mime_type: str | None = None
    candidate_questions: list[QuestionCandidate] = field(default_factory=list)
    fusion_group: list[ExtractionCorrectionSnapshot] = field(default_factory=list)
    submission_blocks: list[ExtractionCorrectionSnapshot] = field(default_factory=list)
    # Distingue plusieurs relectures pleine résolution d'un même bloc dans le
    # chemin de stockage (§9) — jamais un écrasement silencieux de la trace.
    reverification_attempt: int = 1


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ContestationVerificationAgent:
    """Arbitre les 4 types de contestation étudiante, un bloc à la fois."""

    AGENT_NAME = "Contestation_Verification_Agent"

    # États déjà tranchés après lesquels un second passage automatique par
    # l'agent est interdit (§2 étape 8 et étape 9) — l'appelant doit escalader
    # directement vers teacher_arbitration_node, jamais réinvoquer l'agent.
    _BLOCKED_STATUSES = (
        ContestationStatus.IMPLAUSIBLE,
        ContestationStatus.AMBIGU,
        ContestationStatus.RESOLVED,
    )

    _LEADING_LABEL_PATTERN = re.compile(
        r"^\s*(exercice\s*\d+\s*[.,-]?\s*)?"
        r"(question\s*\d+|q\s*\d+|ex\s*\d+\s*[.)]?\s*q?\s*\d*|\d+\s*[.)]\s*\d*)",
        re.IGNORECASE,
    )
    _SYNTAX_INCOMPLETE_TAIL = re.compile(r"(?:[,;+=\-]|\bet\b|\bdonc\b|\bcar\b|\bavec\b)\s*$", re.IGNORECASE)
    _EXPLICIT_REFERRAL = re.compile(r"suite\s*(?:en|page|question|q)\s*\d+", re.IGNORECASE)

    def __init__(
        self,
        low_confidence_threshold: float = 0.6,   # §3 ligne 5 — confiance OCR2 minimale
        label_fuzzy_threshold: int = 80,          # score rapidfuzz minimal (0-100)
        near_identical_ratio: int = 97,           # tolérance de comparaison textuelle (§3)
        fusion_marker_confirm_threshold: int = 2, # nombre de marqueurs solides requis (Cas D)
    ) -> None:
        self._low_confidence_threshold = low_confidence_threshold
        self._label_fuzzy_threshold = label_fuzzy_threshold
        self._near_identical_ratio = near_identical_ratio
        self._fusion_marker_confirm_threshold = fusion_marker_confirm_threshold

    # ------------------------------------------------------------------
    # Point d'entrée
    # ------------------------------------------------------------------

    async def execute(
        self,
        case: ContestationCaseInput,
        context: AgentExecutionContext,
    ) -> ContestationVerdict:
        contested = case.contested
        request = case.request

        if contested.contestation_status in self._BLOCKED_STATUSES:
            raise AlreadyResolvedContestationError(
                contested.id, contested.contestation_status.value
            )

        span_metadata = {
            "flow_type": context.flow_type,
            "submission_id": str(context.submission_id) if context.submission_id else None,
            "extraction_correction_id": str(contested.id),
            "contestation_type": request.contestation_type.value,
        }

        with AgentTraceSpan(self.AGENT_NAME, trace_id=context.trace_id, metadata=span_metadata) as span:
            t_start = time.perf_counter()

            if request.contestation_type == ContestationType.CONTENT:
                verdict = await self._verify_content(case, context)
            elif request.contestation_type == ContestationType.STRUCTURE_ELEMENT:
                verdict = await self._verify_structure_element(case, context)
            elif request.contestation_type == ContestationType.ATTACHMENT:
                verdict = await self._verify_attachment(case, context)
            elif request.contestation_type == ContestationType.FUSION:
                verdict = await self._verify_fusion(case)
            else:
                raise ValueError(f"Type de contestation non supporté : {request.contestation_type}")

            span.record_metrics(
                contestation_type=request.contestation_type.value,
                verdict=verdict.verdict,
                anomaly_flag=verdict.anomaly_flag,
                total_duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
            )
            return verdict

    # ------------------------------------------------------------------
    # Utilitaires exposés pour l'orchestration amont (§8, §9ter)
    # ------------------------------------------------------------------

    @staticmethod
    def exceeds_abuse_threshold(
        contested_block_count: int,
        total_block_count: int,
        threshold: float = CONTESTED_RATIO_ABUSE_THRESHOLD,
    ) -> bool:
        """
        §8 — garde-fou anti-abus. Un signal d'alerte, jamais un refus : à
        l'appelant de basculer en signalement manuel professeur plutôt que
        d'invoquer l'agent bloc par bloc si ce seuil est dépassé.
        """
        if total_block_count <= 0:
            return False
        return (contested_block_count / total_block_count) > threshold

    @staticmethod
    def sort_cases_by_priority(cases: list[ContestationCaseInput]) -> list[ContestationCaseInput]:
        """
        §9ter — un bloc contesté à la fois sur le fond (Cas A) et sur la fusion
        qui l'a créé (Cas D) doit voir le Cas D traité EN PREMIER : évaluer le
        contenu d'un bloc dont l'existence même en tant qu'unité est contestée
        n'a pas de sens tant que ce point n'est pas tranché. Tri stable.
        """
        return sorted(
            cases,
            key=lambda c: 0 if c.request.contestation_type == ContestationType.FUSION else 1,
        )

    # ------------------------------------------------------------------
    # Cas A — Contestation de contenu (§3, table de vérité)
    # ------------------------------------------------------------------

    async def _verify_content(
        self, case: ContestationCaseInput, context: AgentExecutionContext,
    ) -> ContestationVerdict:
        contested = case.contested
        request = case.request

        ocr1 = contested.prediction_ocr
        etu = request.claimed_content or ""

        ocr2_text, ocr2_confidence, model_version, crop_path, _fallback = await self._run_blind_ocr2_reread(
            document_bytes=case.document_bytes,
            document_mime_type=case.document_mime_type,
            page_number=contested.page_number,
            bounding_box=contested.bounding_box,
            extraction_correction_id=contested.id,
            attempt=case.reverification_attempt,
            context=context,
        )

        verdict_str, verified_content, justification, anomaly_flag = await self._apply_content_truth_table(
            ocr1=ocr1, etu=etu, ocr2=ocr2_text, ocr2_confidence=ocr2_confidence, context=context,
        )

        return ContestationVerdict(
            extraction_correction_id=contested.id,
            contestation_type=request.contestation_type,
            verdict=verdict_str,
            verified_content=verified_content,
            justification=justification,
            ocr2_result=ocr2_text,
            ocr2_confidence=ocr2_confidence,
            full_resolution_crop_path=crop_path,
            model_version=model_version,
            anomaly_flag=anomaly_flag,
            confidence_score=(ocr2_confidence if verdict_str != "AMBIGU" else None),
        )

    async def _apply_content_truth_table(
        self, ocr1: str, etu: str, ocr2: str, ocr2_confidence: float, context: AgentExecutionContext,
    ) -> tuple[str, str | None, str, bool]:
        """
        Table de vérité §3 — l'ordre des vérifications est impératif (confiance
        d'abord). Le jugement ORIGINAL/CLAIMED/BOTH/NEITHER (2026-08-18) vient
        d'un appel LLM ciblé (_judge_content_confirmation), jamais d'un score
        de similarité floue — trouvé sur test réel qu'aucun seuil fuzz.ratio/
        partial_ratio ne peut distinguer un désaccord ponctuel (ex. "28" vs
        "29") noyé dans un long paragraphe : ocr1 et etu eux-mêmes mesurent
        déjà 99,5% de similarité globale l'un à l'autre dans ce cas réel,
        avant même de comparer à ocr2 — le problème n'est pas le padding du
        recadrage (cf. fix précédent), c'est que la similarité de texte
        globale est structurellement le mauvais outil pour ce jugement.
        """
        # Ligne 5 — prime sur tout le reste, vérifiée en premier.
        if ocr2_confidence < self._low_confidence_threshold:
            return (
                "AMBIGU", None,
                f"Confiance de la relecture indépendante ({ocr2_confidence:.2f}) sous le seuil "
                f"({self._low_confidence_threshold}) — vérifiée avant toute comparaison, prime sur le reste.",
                False,
            )

        confirms, llm_justification = await self._judge_content_confirmation(ocr1, etu, ocr2, context)

        # Ligne 1
        if confirms == "ORIGINAL":
            return ("IMPLAUSIBLE", ocr1, llm_justification, False)
        # Ligne 2
        if confirms == "CLAIMED":
            return ("PLAUSIBLE", etu, llm_justification, False)
        # Ligne 3 — cas dégénéré, ne devrait jamais survenir si le filtrage en
        # amont (contest_extraction, §2 étape 3) fonctionne.
        if confirms == "BOTH":
            return (
                "PLAUSIBLE", etu,
                f"Cas dégénéré (signalé pour audit) : {llm_justification}",
                True,
            )
        # NEITHER (lignes 4 et 6) — un troisième contenu émerge, ou écriture
        # réellement ambiguë : les deux résolvent en AMBIGU, aucun besoin de
        # les distinguer.
        return ("AMBIGU", None, llm_justification, False)

    async def _judge_content_confirmation(
        self, ocr1: str, etu: str, ocr2: str, context: AgentExecutionContext,
    ) -> tuple[Literal["ORIGINAL", "CLAIMED", "BOTH", "NEITHER"], str]:
        """
        Jugement LLM ciblé (2026-08-18) — remplace fuzz.ratio/partial_ratio
        dans la table de vérité. Voit les 3 textes complets et répond
        directement à la question qui compte : parmi l'extraction d'origine
        et la réclamation de l'étudiant, laquelle la relecture indépendante
        confirme-t-elle RÉELLEMENT sur le point précis en désaccord — jamais
        un score de similarité globale (ocr2 peut légitimement contenir plus
        de texte que les deux autres, cf. marge de recadrage §9, sans que ça
        change ce qu'il faut en conclure).

        Repli déterministe (fuzz, JAMAIS le mécanisme principal) — uniquement
        si l'appel LLM échoue techniquement : ne perd jamais un verdict pour
        une panne d'outil, mais n'invente jamais un jugement de contenu à
        partir d'un score dont on a confirmé qu'il n'est pas fiable pour ce
        cas d'usage précis.
        """
        messages = [
            {"role": "system", "content": CONTENT_CONFIRMATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": CONTENT_CONFIRMATION_USER_TEMPLATE.format(ocr1=ocr1, etu=etu, ocr2=ocr2),
            },
        ]
        try:
            result, _spec, _fallback, _tok = await invoke_llm_with_fallback(
                task_type=TaskType.CONTESTATION_VERIFICATION,
                messages=messages,
                response_schema=_ContentConfirmationSchema,
                context=context,
            )
            parsed = (
                result if isinstance(result, _ContentConfirmationSchema)
                else _ContentConfirmationSchema.model_validate(result)
            )
            return parsed.confirms, parsed.justification
        except Exception as exc:
            logger.warning(
                "Échec technique du jugement LLM de confirmation de contenu (%s) — repli sur "
                "comparaison floue déterministe, jamais le mécanisme principal.", exc,
            )
            return self._fallback_fuzzy_confirmation(ocr1, etu, ocr2)

    def _fallback_fuzzy_confirmation(
        self, ocr1: str, etu: str, ocr2: str,
    ) -> tuple[Literal["ORIGINAL", "CLAIMED", "BOTH", "NEITHER"], str]:
        """
        Repli déterministe UNIQUEMENT en cas d'échec technique de l'appel LLM
        (cf. _judge_content_confirmation) — sait déjà être peu fiable sur un
        désaccord ponctuel noyé dans un long paragraphe (cf. docstring
        _apply_content_truth_table), mais reste préférable à perdre le
        verdict entièrement pour une panne d'outil.
        """
        ocr2_eq_ocr1 = self._near_identical(ocr2, ocr1)
        ocr2_eq_etu = self._near_identical(ocr2, etu)
        if ocr2_eq_ocr1 and not ocr2_eq_etu:
            return "ORIGINAL", (
                "Repli déterministe (échec technique du jugement LLM) : la relecture indépendante "
                "confirme l'extraction d'origine par comparaison floue."
            )
        if ocr2_eq_etu and not ocr2_eq_ocr1:
            return "CLAIMED", (
                "Repli déterministe (échec technique du jugement LLM) : la relecture indépendante "
                "confirme la réclamation de l'étudiant par comparaison floue."
            )
        if ocr2_eq_ocr1 and ocr2_eq_etu:
            return "BOTH", (
                "Repli déterministe (échec technique du jugement LLM) : réclamation étudiante "
                "identique au contenu déjà extrait par comparaison floue."
            )
        return "NEITHER", (
            "Repli déterministe (échec technique du jugement LLM) : ni l'extraction d'origine ni "
            "la réclamation de l'étudiant ne sont confirmées par comparaison floue — désaccord non "
            "tranché sans arbitrage humain."
        )

    def _near_identical(self, a: str, b: str) -> bool:
        """Utilisé UNIQUEMENT par _fallback_fuzzy_confirmation — jamais le mécanisme principal."""
        norm_a = " ".join((a or "").strip().lower().split())
        norm_b = " ".join((b or "").strip().lower().split())
        if not norm_a and not norm_b:
            return True
        return fuzz.ratio(norm_a, norm_b) >= self._near_identical_ratio

    # ------------------------------------------------------------------
    # Relecture OCR2 partagée (Cas A et Cas C-élément) — §2 étape 5, §9
    # ------------------------------------------------------------------

    async def _crop_full_resolution(
        self,
        document_bytes: bytes | None,
        document_mime_type: str | None,
        page_number: int | None,
        bounding_box: dict,
        extraction_correction_id: uuid.UUID,
        attempt: int,
    ) -> tuple[bytes, str]:
        """
        Recadre la zone contestée depuis le document source en pleine résolution
        — jamais depuis image_crop_path, potentiellement compressé pour le
        stockage (§2 étape 5). Upload le résultat et retourne son chemin exact
        (§9 — traçabilité, jamais une référence vague à "l'image source").
        """
        if not document_bytes or not document_mime_type or not page_number:
            raise ValueError(
                "Document source (bytes/mime_type/page_number) requis pour une relecture "
                "en pleine résolution (Cas A/C)."
            )

        pages = prepare_document_pages(document_bytes, document_mime_type)
        page_idx = page_number - 1
        if page_idx < 0 or page_idx >= len(pages):
            raise ValueError(f"page_number={page_number} hors bornes du document ({len(pages)} pages).")

        crop_bytes = crop_region(pages[page_idx], bounding_box, padding_ratio=REREAD_CROP_PADDING_RATIO)
        if not crop_bytes:
            raise ValueError("Échec du recadrage de la zone contestée en pleine résolution.")

        full_res_crop_path = await storage_service.upload(
            StorageContainer.SUBMISSIONS,
            contestation_reread_crop_path(extraction_correction_id, attempt),
            crop_bytes,
            content_type="image/png",
        )
        return crop_bytes, full_res_crop_path

    async def _run_blind_ocr2_reread(
        self,
        document_bytes: bytes | None,
        document_mime_type: str | None,
        page_number: int | None,
        bounding_box: dict,
        extraction_correction_id: uuid.UUID,
        attempt: int,
        context: AgentExecutionContext,
    ) -> tuple[str, float, str, str, bool]:
        """
        OCR2 — relecture indépendante "à l'aveugle" : réutilise exactement le
        schéma et les prompts de relecture ciblée d'OCR_Extraction_Agent. Ni
        OCR1 ni la réclamation de l'étudiant n'entrent jamais dans ce prompt.
        """
        crop_bytes, full_res_crop_path = await self._crop_full_resolution(
            document_bytes, document_mime_type, page_number, bounding_box,
            extraction_correction_id, attempt,
        )

        messages = [
            {"role": "system", "content": OCR_RE_READ_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_RE_READ_USER_TEMPLATE.format(page_number=page_number)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64.b64encode(crop_bytes).decode('utf-8')}"},
                    },
                ],
            },
        ]

        result, spec, fallback, _token_usage = await invoke_llm_with_fallback(
            task_type=TaskType.CONTESTATION_VERIFICATION,
            messages=messages,
            response_schema=PageExtractionResult,
            context=context,
        )
        model_version = f"{spec.provider}:{spec.model_name}"

        if not result.blocks:
            return "", 0.0, model_version, full_res_crop_path, fallback

        block = result.blocks[0]
        return block.raw_text, float(block.model_self_confidence), model_version, full_res_crop_path, fallback

    # ------------------------------------------------------------------
    # Cas C — Contestation d'un élément interne de STRUCTURE (§5)
    # ------------------------------------------------------------------

    async def _verify_structure_element(
        self, case: ContestationCaseInput, context: AgentExecutionContext,
    ) -> ContestationVerdict:
        if case.request.contested_element_id == WHOLE_STRUCTURE_ELEMENT_ID:
            return await self._verify_whole_structure(case, context)
        return await self._verify_single_structure_element(case, context)

    async def _verify_single_structure_element(
        self, case: ContestationCaseInput, context: AgentExecutionContext,
    ) -> ContestationVerdict:
        contested = case.contested
        request = case.request

        element_content = self._locate_structure_element(
            contested.structured_output, request.contested_element_id or ""
        )
        if element_content is None:
            raise StructureElementNotFoundError(contested.id, request.contested_element_id or "")

        etu = request.claimed_content or ""

        # La relecture porte sur toute la zone du bloc (aucune bounding_box par
        # élément n'est persistée), mais la comparaison de la table de vérité
        # se limite strictement à l'élément contesté, jamais au bloc entier.
        ocr2_text, ocr2_confidence, model_version, crop_path, _fallback = await self._run_blind_ocr2_reread(
            document_bytes=case.document_bytes,
            document_mime_type=case.document_mime_type,
            page_number=contested.page_number,
            bounding_box=contested.bounding_box,
            extraction_correction_id=contested.id,
            attempt=case.reverification_attempt,
            context=context,
        )

        verdict_str, verified_content, justification, anomaly_flag = await self._apply_content_truth_table(
            ocr1=element_content, etu=etu, ocr2=ocr2_text, ocr2_confidence=ocr2_confidence, context=context,
        )
        justification += (
            f" [Élément '{request.contested_element_id}' isolé au sein d'une STRUCTURE — comparaison "
            "limitée à cet élément, jamais une réécriture de toute la structure.]"
        )

        return ContestationVerdict(
            extraction_correction_id=contested.id,
            contestation_type=request.contestation_type,
            verdict=verdict_str,
            verified_content=verified_content,
            justification=justification,
            ocr2_result=ocr2_text,
            ocr2_confidence=ocr2_confidence,
            full_resolution_crop_path=crop_path,
            model_version=model_version,
            anomaly_flag=anomaly_flag,
            confidence_score=(ocr2_confidence if verdict_str != "AMBIGU" else None),
        )

    @staticmethod
    def _locate_structure_element(structured_output: dict | None, element_id: str) -> str | None:
        """
        Adressage d'un élément interne d'une STRUCTURE. Aucun schéma de
        structured_content n'expose un id générique universel pour TABLE/FORM/
        MULTI_COLUMN_LIST (cf. app/domain/schemas/ocr_schemas.py — seul
        AnnotatedDiagramElement porte un id natif) : convention adoptée ici,
        à utiliser par le formulaire de contestation (contested_element_id) :
          - "element:<id>"        -> ANNOTATED_DIAGRAM, id natif de l'élément
          - "row:<r>:cell:<c>"    -> TABLE, index ligne/colonne (0-based)
          - "field:<i>"           -> FORM, index du champ (0-based)
          - "column:<c>:item:<i>" -> MULTI_COLUMN_LIST, index colonne/item (0-based)
        """
        if not isinstance(structured_output, dict) or not element_id:
            return None

        try:
            if element_id.startswith("element:"):
                target = element_id.split(":", 1)[1]
                for el in structured_output.get("elements", []):
                    if el.get("id") == target:
                        return el.get("content")
                return None

            if element_id.startswith("row:"):
                _, r, _, c = element_id.split(":")
                cells = structured_output["rows"][int(r)].get("cells", [])
                return cells[int(c)].get("content")

            if element_id.startswith("field:"):
                idx = int(element_id.split(":", 1)[1])
                return structured_output["fields"][idx].get("value")

            if element_id.startswith("column:"):
                _, c, _, i = element_id.split(":")
                return structured_output["columns"][int(c)][int(i)].get("content")
        except (ValueError, IndexError, KeyError, AttributeError):
            return None

        return None

    async def _verify_whole_structure(
        self, case: ContestationCaseInput, context: AgentExecutionContext,
    ) -> ContestationVerdict:
        """
        §5, second cas — désaccord sur la reconstruction elle-même (ex. nombre
        de colonnes d'un tableau), pas sur un contenu précis. Reconstruction
        indépendante "à l'aveugle", puis comparaison explicite (AMBIGU par
        défaut si la reconstruction alternative n'est pas nettement meilleure).
        """
        contested = case.contested
        request = case.request

        if not contested.structure_type:
            raise ValueError("Contestation de structure entière sur un bloc sans structure_type.")

        crop_bytes, full_res_crop_path = await self._crop_full_resolution(
            case.document_bytes, case.document_mime_type, contested.page_number,
            contested.bounding_box, contested.id, case.reverification_attempt,
        )

        messages = [
            {"role": "system", "content": OCR_RE_READ_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_RE_READ_USER_TEMPLATE.format(page_number=contested.page_number)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64.b64encode(crop_bytes).decode('utf-8')}"},
                    },
                ],
            },
        ]
        result, spec, _fallback, _tok = await invoke_llm_with_fallback(
            task_type=TaskType.CONTESTATION_VERIFICATION,
            messages=messages,
            response_schema=PageExtractionResult,
            context=context,
        )
        reread_model_version = f"{spec.provider}:{spec.model_name}"

        if not result.blocks:
            return ContestationVerdict(
                extraction_correction_id=contested.id,
                contestation_type=request.contestation_type,
                verdict="AMBIGU",
                justification="La reconstruction indépendante de la structure a échoué — AMBIGU par défaut.",
                full_resolution_crop_path=full_res_crop_path,
                model_version=reread_model_version,
            )

        blind_block = result.blocks[0]
        blind_reconstruction = json.dumps(blind_block.structured_content, ensure_ascii=False)
        original_reconstruction = json.dumps(contested.structured_output, ensure_ascii=False)

        comparison_messages = [
            {"role": "system", "content": STRUCTURE_RECONSTRUCTION_COMPARISON_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": STRUCTURE_RECONSTRUCTION_COMPARISON_USER_TEMPLATE.format(
                    blind_reconstruction=blind_reconstruction,
                    original_reconstruction=original_reconstruction,
                    claimed_reconstruction=request.claimed_content or "",
                ),
            },
        ]
        try:
            comparison_result, comparison_spec, _fb2, _tok2 = await invoke_llm_with_fallback(
                task_type=TaskType.CONTESTATION_VERIFICATION,
                messages=comparison_messages,
                response_schema=_StructureComparisonSchema,
                context=context,
            )
            parsed = (
                comparison_result if isinstance(comparison_result, _StructureComparisonSchema)
                else _StructureComparisonSchema.model_validate(comparison_result)
            )
        except Exception as exc:
            raise ContestationSchemaError(contested.id, str(exc)) from exc

        verdict_map = {
            "CLAIMED_CONFIRMED": "PLAUSIBLE",
            "ORIGINAL_CONFIRMED": "IMPLAUSIBLE",
            "AMBIGU": "AMBIGU",
        }
        final_verdict = verdict_map[parsed.verdict]
        verified_content = (
            request.claimed_content if final_verdict == "PLAUSIBLE"
            else (contested.prediction_ocr if final_verdict == "IMPLAUSIBLE" else None)
        )

        comparison_confidence = parsed.confidence
        return ContestationVerdict(
            extraction_correction_id=contested.id,
            contestation_type=request.contestation_type,
            verdict=final_verdict,
            verified_content=verified_content,
            justification=parsed.justification,
            ocr2_result=blind_reconstruction,
            ocr2_confidence=comparison_confidence,
            full_resolution_crop_path=full_res_crop_path,
            model_version=f"{reread_model_version}+{comparison_spec.provider}:{comparison_spec.model_name}",
            anomaly_flag=False,
            confidence_score=(comparison_confidence if final_verdict != "AMBIGU" else None),
        )

    # ------------------------------------------------------------------
    # Cas B — Contestation de rattachement (§4, avec ExerciseSection)
    # ------------------------------------------------------------------

    async def _verify_attachment(
        self, case: ContestationCaseInput, context: AgentExecutionContext,
    ) -> ContestationVerdict:
        contested = case.contested
        request = case.request
        candidates = case.candidate_questions

        # §12 — défense en profondeur : la solution de référence comparée doit
        # bien appartenir à l'exercice de la soumission.
        if context.exercise_id is not None:
            alien = [q for q in candidates if q.exercise_id != context.exercise_id]
            if alien:
                raise ValueError(
                    f"IDOR détecté : {len(alien)} question(s) étrangère(s) à l'exercice {context.exercise_id}"
                )

        missing = [q for q in candidates if not q.reference_content.strip()]
        if missing:
            raise MissingReferenceSolutionError(
                exercise_id=missing[0].exercise_id, missing_question_ids=[q.question_id for q in missing],
            )

        original = next((q for q in candidates if q.question_id == contested.question_id), None)

        if request.claimed_question_id is not None:
            claimed_pool = [q for q in candidates if q.question_id == request.claimed_question_id]
        elif request.claimed_section_id is not None:
            # §4, contestation au niveau section — comparaison élargie à TOUTES
            # les questions de la section réclamée, pas seulement l'originale.
            claimed_pool = [q for q in candidates if q.section_id == request.claimed_section_id]
        else:
            claimed_pool = []

        if not claimed_pool:
            return ContestationVerdict(
                extraction_correction_id=contested.id,
                contestation_type=request.contestation_type,
                verdict="AMBIGU",
                justification="Hypothèse de l'étudiant introuvable parmi les questions/sections de l'exercice.",
                model_version="n/a",
            )

        # Niveau 1 — label explicite lu directement dans le texte transcrit du
        # bloc (aucun champ student_label n'est persisté sur ExtractionCorrection ;
        # quand un label existe, il est déjà repris en tête de prediction_ocr).
        leading_label = self._extract_leading_label(contested.prediction_ocr)
        if leading_label:
            label_verdict = self._try_label_hierarchy(leading_label, claimed_pool, original)
            if label_verdict is not None:
                verdict_str, resolved_q, justification, label_confidence = label_verdict
                return self._build_attachment_verdict(
                    contested, request, verdict_str, resolved_q, justification,
                    model_version="label_heuristic:rapidfuzz",
                    confidence_score=label_confidence,
                )

        # Niveau 2 — arbitrage LLM, hypothèse de l'étudiant testée en premier,
        # jamais tranchée automatiquement en sa faveur.
        return await self._llm_attachment_arbitration(contested, request, claimed_pool, original, context)

    @staticmethod
    def _extract_leading_label(text: str) -> str | None:
        if not text:
            return None
        match = ContestationVerificationAgent._LEADING_LABEL_PATTERN.match(text.strip())
        if not match or not match.group().strip():
            return None
        return match.group().strip()

    @staticmethod
    def _normalize_label(raw: str) -> str:
        return raw.strip().lower().replace("exercice", "ex").replace("question", "q").replace(" ", "")

    @staticmethod
    def _build_label_variants(q: QuestionCandidate) -> list[str]:
        """
        q_num utilise position_in_section (numéro réellement visible par
        l'étudiant dans sa section) quand la question appartient à une
        section ; sinon retombe sur order (global) — même correction que
        Question_Attachment_Agent._build_question_label_variants (bug de
        fond identique : deux "Question 1" dans deux sections différentes
        ont le même position_in_section mais des order globaux distincts,
        utiliser order directement rattacherait à tort la mauvaise section).
        """
        labels = []
        q_num = str(q.position_in_section if q.position_in_section is not None else q.order)
        labels.extend([q_num, f"q{q_num}", f"question{q_num}", f"{q_num}."])
        if q.section_order is not None:
            sec = str(q.section_order)
            labels.extend([
                f"ex{sec}q{q_num}", f"ex{sec}.{q_num}", f"{sec}.{q_num}",
                f"exercice{sec}question{q_num}", f"{sec}q{q_num}",
            ])
        return [ContestationVerificationAgent._normalize_label(lbl) for lbl in labels]

    @classmethod
    def _best_label_match(
        cls, normalized_label: str, pool: list[QuestionCandidate],
    ) -> tuple[int, QuestionCandidate | None]:
        best_score, best_q = 0, None
        for q in pool:
            for variant in cls._build_label_variants(q):
                score = fuzz.ratio(normalized_label, variant)
                if score > best_score:
                    best_score, best_q = score, q
        return best_score, best_q

    def _try_label_hierarchy(
        self,
        leading_label: str,
        claimed_pool: list[QuestionCandidate],
        original: QuestionCandidate | None,
    ) -> tuple[str, QuestionCandidate | None, str, float] | None:
        """Hypothèse de l'étudiant testée EN PREMIER, jamais confirmée par défaut."""
        normalized = self._normalize_label(leading_label)

        best_claimed_score, best_claimed_q = self._best_label_match(normalized, claimed_pool)
        if best_claimed_score >= self._label_fuzzy_threshold:
            return (
                "PLAUSIBLE", best_claimed_q,
                f"Label lu dans le texte transcrit ('{leading_label}') correspond à l'hypothèse de "
                f"l'étudiant (score rapidfuzz={best_claimed_score}/100).",
                best_claimed_score / 100.0,
            )

        if original is not None:
            best_original_score, _ = self._best_label_match(normalized, [original])
            if best_original_score >= self._label_fuzzy_threshold:
                return (
                    "IMPLAUSIBLE", original,
                    f"Label lu dans le texte transcrit ('{leading_label}') confirme le rattachement "
                    f"d'origine (score rapidfuzz={best_original_score}/100), pas l'hypothèse de l'étudiant.",
                    best_original_score / 100.0,
                )

        return None

    @staticmethod
    def _build_attachment_verdict(
        contested: ExtractionCorrectionSnapshot,
        request: ContestExtractionRequest,
        verdict_str: str,
        resolved_q: QuestionCandidate | None,
        justification: str,
        model_version: str,
        confidence_score: float,
    ) -> ContestationVerdict:
        return ContestationVerdict(
            extraction_correction_id=contested.id,
            contestation_type=request.contestation_type,
            verdict=verdict_str,
            justification=justification,
            resolved_question_id=resolved_q.question_id if resolved_q else None,
            resolved_section_id=resolved_q.section_id if resolved_q else None,
            model_version=model_version,
            confidence_score=confidence_score,
        )

    async def _llm_attachment_arbitration(
        self,
        contested: ExtractionCorrectionSnapshot,
        request: ContestExtractionRequest,
        claimed_pool: list[QuestionCandidate],
        original: QuestionCandidate | None,
        context: AgentExecutionContext,
    ) -> ContestationVerdict:
        block_text = contested.prediction_ocr
        if contested.content_type == ExtractionContentType.STRUCTURE:
            block_text = structure_to_flat_text(contested.structured_output) or block_text

        claimed_label = ", ".join(f"Q{q.order} (section {q.section_order or 'N/A'})" for q in claimed_pool)
        claimed_summary = " | ".join(q.reference_summary or "non disponible" for q in claimed_pool)
        original_label = (
            f"Q{original.order} (section {original.section_order or 'N/A'})" if original else "aucun (bloc orphelin)"
        )
        original_summary = (original.reference_summary or "non disponible") if original else "n/a"

        messages = [
            {"role": "system", "content": ATTACHMENT_ARBITRATION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": ATTACHMENT_ARBITRATION_USER_TEMPLATE.format(
                    content_type=contested.content_type,
                    block_text=block_text[:800],
                    original_label=original_label,
                    original_summary=original_summary,
                    claimed_label=claimed_label,
                    claimed_summary=claimed_summary,
                ),
            },
        ]

        try:
            result, spec, _fallback, _tok = await invoke_llm_with_fallback(
                task_type=TaskType.CONTESTATION_VERIFICATION, messages=messages,
                response_schema=_AttachmentArbitrationSchema, context=context,
            )
            parsed = (
                result if isinstance(result, _AttachmentArbitrationSchema)
                else _AttachmentArbitrationSchema.model_validate(result)
            )
        except Exception as exc:
            raise ContestationSchemaError(contested.id, str(exc)) from exc

        model_version = f"{spec.provider}:{spec.model_name}"
        justification = parsed.justification
        raw_verdict = parsed.verdict
        llm_confidence = parsed.confidence

        if raw_verdict == "STUDENT_HYPOTHESIS_CONFIRMED":
            resolved_q = claimed_pool[0]
            return self._build_attachment_verdict(
                contested, request, "PLAUSIBLE", resolved_q, justification, model_version,
                confidence_score=llm_confidence,
            )
        if raw_verdict == "ORIGINAL_CONFIRMED" and original is not None:
            return self._build_attachment_verdict(
                contested, request, "IMPLAUSIBLE", original, justification, model_version,
                confidence_score=llm_confidence,
            )
        return ContestationVerdict(
            extraction_correction_id=contested.id,
            contestation_type=request.contestation_type,
            verdict="AMBIGU",
            justification=justification,
            model_version=model_version,
        )

    # ------------------------------------------------------------------
    # Cas D — Contestation d'une fusion de continuité (§6)
    # ------------------------------------------------------------------

    async def _verify_fusion(self, case: ContestationCaseInput) -> ContestationVerdict:
        if case.request.fusion_claim == "wrongly_merged":
            return self._verify_wrongly_merged(case)
        return self._verify_should_have_merged(case)

    @classmethod
    def _continuity_markers(cls, group: list[ExtractionCorrectionSnapshot]) -> dict[str, bool]:
        """
        Revérifie les marqueurs de continuité — PAS une relecture d'image,
        une revérification de la preuve elle-même (§6). L'absence d'un nouveau
        student_label ne peut pas être revérifiée : ce champ n'est pas persisté
        séparément sur ExtractionCorrection une fois la fusion appliquée
        (bulk_update_attachments propage evidence_level du survivant à tous les
        blocs consommés). Les 3 signaux ci-dessous restent authentiques.
        """
        ordered = sorted(group, key=lambda b: ((b.page_number or 0), str(b.id)))
        page_adjacent = any(
            (b.page_number or 0) - (a.page_number or 0) in (0, 1)
            for a, b in zip(ordered, ordered[1:])
        )
        syntax_incomplete = any(
            cls._SYNTAX_INCOMPLETE_TAIL.search(b.prediction_ocr.strip())
            or len(b.prediction_ocr.split()) < 5
            for b in ordered[:-1]
        )
        explicit_referral = any(cls._EXPLICIT_REFERRAL.search(b.prediction_ocr) for b in ordered)
        return {
            "page_adjacency": page_adjacent,
            "syntax_incomplete_tail": syntax_incomplete,
            "explicit_referral_marker": explicit_referral,
        }

    def _verify_wrongly_merged(self, case: ContestationCaseInput) -> ContestationVerdict:
        contested = case.contested
        request = case.request
        group = case.fusion_group

        if len(group) < 2:
            raise FusionGroupNotFoundError(contested.id)

        markers = self._continuity_markers(group)
        strong_markers = sum(markers.values())
        group_ids = [b.id for b in group]

        if strong_markers < self._fusion_marker_confirm_threshold:
            return ContestationVerdict(
                extraction_correction_id=contested.id,
                contestation_type=request.contestation_type,
                verdict="PLAUSIBLE",
                justification=(
                    "Revérification des marqueurs de continuité invoqués pour la fusion : "
                    f"{markers} — trop faibles à ce second examen, la fusion est infirmée (défusion)."
                ),
                fused_correction_ids=group_ids,
                defusion_applied=True,
                model_version="fusion_marker_reverification:deterministic",
                confidence_score=CONTESTATION_RESOLVED_CONFIDENCE_SCORE,
            )

        return ContestationVerdict(
            extraction_correction_id=contested.id,
            contestation_type=request.contestation_type,
            verdict="IMPLAUSIBLE",
            justification=(
                "Revérification des marqueurs de continuité invoqués pour la fusion : "
                f"{markers} — suffisamment solides, la fusion est confirmée."
            ),
            fused_correction_ids=group_ids,
            defusion_applied=False,
            model_version="fusion_marker_reverification:deterministic",
            confidence_score=CONTESTATION_RESOLVED_CONFIDENCE_SCORE,
        )

    def _verify_should_have_merged(self, case: ContestationCaseInput) -> ContestationVerdict:
        contested = case.contested
        request = case.request

        already_fused_ids = {contested.id} | {b.id for b in case.fusion_group}
        candidates = [b for b in case.submission_blocks if b.id not in already_fused_ids]
        candidates.sort(key=lambda b: abs((b.page_number or 0) - (contested.page_number or 0)))

        for candidate in candidates:
            markers = self._continuity_markers([contested, candidate])
            if sum(markers.values()) >= self._fusion_marker_confirm_threshold:
                return ContestationVerdict(
                    extraction_correction_id=contested.id,
                    contestation_type=request.contestation_type,
                    verdict="PLAUSIBLE",
                    justification=(
                        f"Marqueur de continuité trouvé avec le bloc {candidate.id}, qui aurait dû "
                        f"déclencher une fusion à l'étape -1 de Question_Attachment_Agent : {markers}."
                    ),
                    fused_correction_ids=[contested.id, candidate.id],
                    defusion_applied=False,
                    model_version="fusion_marker_reverification:deterministic",
                    confidence_score=CONTESTATION_RESOLVED_CONFIDENCE_SCORE,
                )

        return ContestationVerdict(
            extraction_correction_id=contested.id,
            contestation_type=request.contestation_type,
            verdict="IMPLAUSIBLE",
            justification="Aucun marqueur de continuité trouvé parmi les autres blocs de la soumission.",
            model_version="fusion_marker_reverification:deterministic",
            confidence_score=CONTESTATION_RESOLVED_CONFIDENCE_SCORE,
        )
