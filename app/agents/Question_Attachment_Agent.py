"""
Agent 2 — Question_Attachment_Agent (Version Définitive v3, embeddings réels v3.1)

v3.1 (2026-08-18) — _embed_text n'était jamais branché sur un vrai modèle
depuis sa création ("dummy déterministe, override en prod par API
embedding" — jamais fait) : chaque appel produisait un hash de 128 flottants
sans aucun sens sémantique, rendant le Niveau 2 (similarité cosinus) inerte
en production (testé isolément le 2026-08-16 avec de vrais embeddings
Gemini, jamais appliqué). Branché maintenant sur app.core.embeddings
(sentence-transformers/all-MiniLM-L6-v2, déjà utilisé par le RAG ailleurs
dans le projet, local, aucun coût API) via asyncio.to_thread (inférence
CPU bloquante, jamais dans la boucle d'événements). embed_text() peut
retourner None (texte vide, modèle indisponible) — géré explicitement :
un bloc sans embedding défère directement au Niveau 3 (LLM), jamais un
ORPHELIN ni un rattachement fabriqués ; une référence de question sans
embedding est simplement exclue des candidats du Niveau 2 pour CE bloc
(les autres questions restent comparables). QUESTION_ATTACHMENT_COSINE_
THRESHOLD recalibré 0.15 -> 0.05 (settings, cf. commentaire local) —
point de départ basé sur le test du 2026-08-16, à revalider sur données
réelles.

Rattache chaque RawExtractedBlock produit par OCR_Extraction_Agent à
la Question réelle à laquelle l'étudiant répondait.

Ne transcrit rien, ne juge aucune réponse. Uniquement correspondance structurée.
S'exécute sur l'ensemble des blocs de toutes les pages reçus d'un coup.

Pipeline en 8 étapes :
  -1. Détection et fusion de continuité (frontière de page, renvoi longue distance, marge, pool d'indices ratures)
   0. Filtrage par content_type (TEXT/EQUATION/DIAGRAM barrés/imprimés exclus, STRUCTURE filtré par élément)
   1. Précondition : toutes les Questions ont une SolutionVariant de référence
   2. Niveau 1 — Label explicite à deux niveaux (rapidfuzz, Section + Question)
   3. Niveau 2 — Similarité de contenu par embeddings cosinus
   4. Niveau 3 — Arbitrage LLM ciblé pour cas ambigus
   5. Niveau 4 — Orphelin (si aucune question candidate plausible)
   6. Contrôle qualité étendu (conflits de labels + cohérence bornée des renvois)
   7. Persistance atomique en une seule transaction

Sortie : list[AttachedExtractedBlock] + AgentDecisionLog par bloc non filtré.
"""
import asyncio
import re
import logging
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.agents.context import AgentExecutionContext
from app.agents.ocr_block_utils import filter_consumer_block, structure_to_flat_text
from app.agents.question_attachment_exceptions import (
    AttachmentTimeoutError,
    MissingReferenceSolutionError,
)
from app.core.config import settings
from app.core.exceptions import VisionProviderError
from app.domain.models.assessment.extraction_correction import (
    ExtractionContentType,
    ExtractionEvidenceLevel,
    StructureType,
)
from app.domain.schemas.submission_schemas import AttachedExtractedBlock, RawExtractedBlock
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType
from app.observability.langfuse import AgentTraceSpan
from app.prompts.question_attachment_prompt import (
    QUESTION_ATTACHMENT_SYSTEM_PROMPT,
    QUESTION_ATTACHMENT_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QuestionRef:
    """Représentation interne d'une Question avec sa SolutionVariant de référence."""
    question_id: uuid.UUID
    exercise_id: uuid.UUID
    order: int                  # Question.order — GLOBAL à l'exercice (UniqueConstraint
                                 # exercise_id+order), JAMAIS ce que l'étudiant voit dès
                                 # qu'il y a ≥2 sections. Ne jamais l'utiliser pour construire
                                 # un label attendu — cf. position_in_section ci-dessous.
    statement: str
    section_order: int | None   # ExerciseSection.order, None si pas de section
    reference_content: str      # SolutionVariant.content
    reference_summary: str | None  # SolutionVariant.reasoning_summary
    # rang 1-based parmi les questions de la même section (trié par order) —
    # c'est CE numéro que l'étudiant écrit ("Question 1" de la section 2 ≠
    # Question globale n°1). None si pas de section (alors `order` fait
    # référence) OU si l'appelant ne le renseigne pas (tests existants) —
    # défaut à la fin du dataclass pour ne casser aucun appel par mot-clé.
    position_in_section: int | None = None


@dataclass
class BlockVerdict:
    """Verdict de rattachement pour un seul bloc."""
    block_index: int
    question_id: uuid.UUID | None
    evidence_level: ExtractionEvidenceLevel
    confidence_score: float
    justification: str
    model_used: str | None = None
    fallback_occurred: bool = False
    tokens_used: int = 0
    level_used: int = 1  # 1=label, 2=embeddings, 3=LLM, 4=orphelin


# Niveau -> étiquette lisible pour model_version quand aucun LLM n'a été appelé
# (Niveaux 1/2/4 déterministes, ou Niveau 3 dont l'appel LLM a échoué après retry
# — cf. _llm_arbitration, cas où model_used reste None malgré level_used=3).
_DETERMINISTIC_LEVEL_LABELS = {
    1: "label_match",
    2: "cosine_embedding",
    3: "llm_arbitration_failed",
    4: "orphan_threshold",
}


@dataclass
class AttachmentDecision:
    """
    Trace de décision par bloc rattaché — alimente AgentDecisionLog (cf.
    docstring du module, "Sortie : ... + AgentDecisionLog par bloc non
    filtré"). Miroir de StructuringReport.block_classifications (agent 3,
    document_structuring_service.py), mais avec image_crop_path comme clé
    de corrélation (au lieu d'un exercise_id global) : contrairement à
    l'agent 3, les ExtractionCorrection existent déjà en base au moment où
    ces décisions sont produites (bulk_create_for_submission tourne avant
    Question_Attachment_Agent.execute(), cf. submission_ocr_pipeline_service.
    py) — l'appelant peut donc résoudre un vrai UUID de bloc, jamais
    disponible côté agent 3 à ce stade.
    """
    image_crop_path: str
    question_id: uuid.UUID | None
    evidence_level: ExtractionEvidenceLevel
    justification: str
    model_version: str
    confidence_score: float
    level_used: int
    fallback_occurred: bool = False
    tokens_used: int = 0


@dataclass
class AttachmentResult:
    """
    Sortie de QuestionAttachmentAgent.execute() : données de persistance
    (attached_blocks, inchangé pour les appelants existants) + traçabilité
    de décision (decisions, nouveau canal — cf. AttachmentDecision).
    """
    attached_blocks: list["AttachedExtractedBlock"]
    decisions: list[AttachmentDecision] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Schéma de sortie structurée — Niveau 3 (arbitrage LLM)
# ---------------------------------------------------------------------------
# Bug réel corrigé (2026-09-03, cas zainabsebhi) : ce Niveau 3 utilisait
# encore l'ancien pattern response_schema=None + re.search(r"\{.*\}", ...) +
# json.loads (même bug JSON fragile déjà trouvé et corrigé cette session sur
# 5 autres agents — Document_Structuring_Agent, Extraction_Verification_
# Agent, Reasoning_Graph_Agent, Solution_Variant_Generation_Agent,
# Contestation_Verification_Agent) sans même la normalisation défensive
# .content-liste-vers-texte ajoutée ailleurs (cf. Feedback_Agent._call_llm) —
# jamais remarqué jusqu'ici car le seuil cosinus (Niveau 2) trop permissif
# court-circuitait presque toujours ce Niveau 3 en pratique. En le rendant
# réellement accessible (cf. QUESTION_ATTACHMENT_MIN_CONFIDENT_SIMILARITY),
# ce test réel a immédiatement fait planter tous les appels Niveau 3
# ("expected string or bytes-like object, got 'list'"). Migré vers structured
# output, même idiome que _AttachmentArbitrationSchema (Contestation_
# Verification_Agent) — plus de parsing regex/JSON fragile du tout.
class _QuestionArbitrationSchema(BaseModel):
    verdict: Literal["ATTACHED", "ORPHELIN", "AMBIGU"]
    # Index dans top_indices (PAS l'index réel dans `questions`) — seulement
    # pertinent si verdict == "ATTACHED", cf. docstring _llm_arbitration.
    question_index: int | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    # Bug réel corrigé (2026-09-03, test réel zainabsebhi) : justification
    # sans défaut faisait échouer la validation structurée dès que le LLM
    # omettait ce champ ("Field required"), déclenchant un retry + bascule de
    # fournisseur (invoke_llm_with_fallback) à CHAQUE occurrence — sur une
    # copie avec beaucoup de blocs déférés au Niveau 3, ce surcoût cumulé a
    # fait dépasser le timeout global de 120s pour toute la soumission.
    # L'ancien parsing JSON ad hoc tolérait déjà l'absence de ce champ
    # (valeur de repli "Décision LLM sans justification.") — même tolérance
    # ici, jamais une erreur bloquante pour un simple texte manquant.
    justification: str = "Décision LLM sans justification."


# ---------------------------------------------------------------------------
# Label normalization helpers
# ---------------------------------------------------------------------------

def _normalize_label(raw: str) -> str:
    """Normalise un label étudiant ('Ex 2 Q1', '2.a', 'question 3') → forme canonique."""
    return raw.strip().lower().replace("exercice", "ex").replace("question", "q").replace(" ", "")


def _extract_trailing_number(normalized_label: str) -> str | None:
    """Numéro de question en fin de label normalisé ('ex1q3' -> '3', 'q3' -> '3')."""
    match = re.search(r"(\d+)$", normalized_label)
    return match.group(1) if match else None


def _build_question_label_variants(q: QuestionRef) -> list[str]:
    """
    Génère toutes les formes de label attendues pour une Question (Niveau 1).
    Couvre les notations à un niveau (numéro seul) et deux niveaux (section + numéro).

    q_num utilise position_in_section (numéro réellement visible par
    l'étudiant dans sa section — "Question 1" de la section 2 n'est PAS la
    Question globale n°1) quand la question appartient à une section ; sinon
    retombe sur order (global), qui est alors le seul système de numérotation
    que l'étudiant a pu voir. Utiliser order directement ici était le bug :
    deux "Question 1" dans deux sections différentes ont le même
    position_in_section (1) mais des order globaux distincts.
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
    return [_normalize_label(lbl) for lbl in labels]


# ---------------------------------------------------------------------------
# Embedding utility
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Calcule la similarité cosinus entre deux vecteurs denses."""
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


async def _embed_text(text: str) -> list[float] | None:
    """
    Embedding sémantique réel — branché sur app.core.embeddings (v2,
    2026-08-18), le module RAG déjà utilisé ailleurs dans le projet
    (reasoning_graph_service.py, rag_repository.py), jamais câblé ici
    jusqu'à ce fix : cette fonction retournait un hash déterministe sans
    aucun sens sémantique ("override en prod par API embedding" jamais
    fait, cf. mémoire de session — testé isolément le 2026-08-16 avec de
    vrais embeddings Gemini, jamais appliqué en production).
    sentence-transformers/all-MiniLM-L6-v2, 384 dim, local (aucun coût
    API, aucune dépendance réseau). embed_text() est synchrone et bloquant
    (inférence CPU du modèle) — exécuté dans un thread (asyncio.to_thread)
    pour ne jamais geler la boucle d'événements asyncio de cet agent.
    Retourne None si le texte est vide OU si sentence-transformers est
    indisponible (jamais une exception) — l'appelant doit alors dégrader
    vers le Niveau 3 (arbitrage LLM), jamais fabriquer une similarité.
    """
    from app.core.embeddings import embed_text as _real_embed_text
    return await asyncio.to_thread(_real_embed_text, text)


# ---------------------------------------------------------------------------
# Main Agent Class
# ---------------------------------------------------------------------------

class QuestionAttachmentAgent:
    """
    Agent 2 v3 : Rattachement des blocs OCR aux Questions d'un exercice étudiant.
    """

    AGENT_NAME = "Question_Attachment_Agent"

    def __init__(
        self,
        cosine_threshold: float | None = None,   # delta minimal pour ne pas déclencher le LLM (Niveau 3)
        min_confident_similarity: float | None = None,  # plancher absolu sur best_sim, cf. commentaire Settings
        label_fuzzy_threshold: int | None = None,  # score rapidfuzz minimal (0-100) pour label match
        max_timeout_seconds: int | None = None,  # garde-fou global par soumission
        orphan_similarity_threshold: float | None = None,  # Niveau 4 : sous ce seuil, ORPHELIN direct
    ) -> None:
        # Résolu depuis Settings à la CONSTRUCTION (pas comme défaut de
        # signature figé à l'import du module) : un override explicite au
        # constructeur (tests) prime toujours ; sans override, la valeur
        # Settings courante s'applique — ajustable sans redéploiement, même
        # principe que OCR_MIN_LAPLACIAN_VARIANCE/OCR_CONFIDENCE_THRESHOLD
        # côté OCR_Extraction_Agent.
        self._cosine_threshold = (
            cosine_threshold if cosine_threshold is not None
            else settings.QUESTION_ATTACHMENT_COSINE_THRESHOLD
        )
        self._min_confident_similarity = (
            min_confident_similarity if min_confident_similarity is not None
            else settings.QUESTION_ATTACHMENT_MIN_CONFIDENT_SIMILARITY
        )
        self._label_fuzzy_threshold = (
            label_fuzzy_threshold if label_fuzzy_threshold is not None
            else settings.QUESTION_ATTACHMENT_LABEL_FUZZY_THRESHOLD
        )
        self._max_timeout_seconds = (
            max_timeout_seconds if max_timeout_seconds is not None
            else settings.QUESTION_ATTACHMENT_MAX_TIMEOUT_SECONDS
        )
        self._orphan_similarity_threshold = (
            orphan_similarity_threshold if orphan_similarity_threshold is not None
            else settings.QUESTION_ATTACHMENT_ORPHAN_SIMILARITY_THRESHOLD
        )

    async def execute(
        self,
        raw_blocks: list[RawExtractedBlock],
        questions: list[QuestionRef],
        context: AgentExecutionContext,
    ) -> AttachmentResult:
        """
        Point d'entrée principal.
        """
        span_metadata = {
            "flow_type": context.flow_type,
            "submission_id": str(context.submission_id),
            "exercise_id": str(context.exercise_id),
        }

        with AgentTraceSpan(self.AGENT_NAME, trace_id=context.trace_id, metadata=span_metadata) as span:
            t_global_start = time.perf_counter()

            # ----------------------------------------------------------------
            # Précondition : vérifier que toutes les questions ont une variante de référence
            # ----------------------------------------------------------------
            missing = [q for q in questions if not q.reference_content.strip()]
            if missing:
                raise MissingReferenceSolutionError(
                    exercise_id=context.exercise_id or uuid.UUID(int=0),
                    missing_question_ids=[q.question_id for q in missing],
                )

            # Vérification sécurité : toutes les questions appartiennent bien à l'exercise_id
            if context.exercise_id:
                alien = [q for q in questions if q.exercise_id != context.exercise_id]
                if alien:
                    raise ValueError(
                        f"IDOR détecté : {len(alien)} questions étrangères à l'exercice {context.exercise_id}"
                    )

            # ----------------------------------------------------------------
            # Étape -1 — Détection et fusion de continuité + Pool d'indices
            # ----------------------------------------------------------------
            (
                fused_blocks,
                inter_page_fusions,
                long_distance_fusions,
                margin_annotation_fusions,
                struck_index_pool,
            ) = self._detect_and_fuse_continuity(raw_blocks)
            total_continuity_fusions = (
                inter_page_fusions + long_distance_fusions + margin_annotation_fusions
            )

            # ----------------------------------------------------------------
            # Étape 0 — Filtrage v3 (barrés/imprimés, granularité STRUCTURE)
            # ----------------------------------------------------------------
            active_blocks: list[RawExtractedBlock] = []
            for b in fused_blocks:
                filtered = filter_consumer_block(b)
                if filtered is not None:
                    active_blocks.append(filtered)
            filtered_count = len(raw_blocks) - len(active_blocks)

            logger.info(
                f"{self.AGENT_NAME}: {len(raw_blocks)} blocs reçus, "
                f"{total_continuity_fusions} fusions de continuité, "
                f"{filtered_count} filtrés, {len(active_blocks)} blocs actifs à traiter."
            )

            if not active_blocks:
                span.record_metrics(
                    filtered_block_count=filtered_count,
                    active_block_count=0,
                    continuity_fusion_count=total_continuity_fusions,
                    inter_page_fusion_count=inter_page_fusions,
                    long_distance_fusion_count=long_distance_fusions,
                    margin_annotation_fusion_count=margin_annotation_fusions,
                    evidence_level_1_count=0,
                    evidence_level_2_count=0,
                    evidence_level_3_count=0,
                    orphan_count=0,
                    ambiguous_count=0,
                )
                return AttachmentResult(attached_blocks=[], decisions=[])

            # ----------------------------------------------------------------
            # Pré-calcul des labels attendus et embeddings de référence
            # ----------------------------------------------------------------
            question_labels: dict[int, list[str]] = {
                idx: _build_question_label_variants(q)
                for idx, q in enumerate(questions)
            }

            ref_embeddings = await asyncio.gather(*[
                _embed_text(q.reference_content) for q in questions
            ])

            # ----------------------------------------------------------------
            # Traitement de chaque bloc actif
            # ----------------------------------------------------------------
            verdicts: list[BlockVerdict] = []
            t_llm_calls = 0
            order_by_question_id = {q.question_id: q.order for q in questions}
            # cf. docstring _attach_single_block (paramètre inherited_label) —
            # mis à jour UNIQUEMENT par un verdict LABEL_EXPLICITE (direct ou
            # déjà hérité), jamais réinitialisé par un verdict Niveau 2/3/4
            # intercalé : la chaîne reste "sous le dernier label explicite vu"
            # jusqu'à ce qu'un NOUVEAU label direct la remplace.
            inherited_label: tuple[uuid.UUID, int] | None = None

            for block_idx, block in enumerate(active_blocks):
                elapsed = time.perf_counter() - t_global_start
                if elapsed > self._max_timeout_seconds:
                    raise AttachmentTimeoutError(
                        submission_id=context.submission_id or uuid.UUID(int=0),
                        timeout_seconds=self._max_timeout_seconds,
                    )

                verdict = await self._attach_single_block(
                    block=block,
                    block_idx=block_idx,
                    questions=questions,
                    question_labels=question_labels,
                    ref_embeddings=ref_embeddings,
                    struck_index_pool=struck_index_pool,
                    context=context,
                    inherited_label=inherited_label,
                )
                if verdict.model_used:
                    t_llm_calls += 1
                if (
                    verdict.evidence_level == ExtractionEvidenceLevel.LABEL_EXPLICITE
                    and verdict.question_id is not None
                ):
                    inherited_label = (
                        verdict.question_id, order_by_question_id.get(verdict.question_id, 0),
                    )
                verdicts.append(verdict)

            # ----------------------------------------------------------------
            # Contrôle qualité post-traitement (conflits de labels + cohérence renvois)
            # ----------------------------------------------------------------
            verdicts = self._resolve_label_conflicts(verdicts, active_blocks)
            verdicts = self._check_referral_consistency(verdicts, active_blocks, questions)

            # ----------------------------------------------------------------
            # Construction des AttachedExtractedBlock
            # ----------------------------------------------------------------
            attached_blocks: list[AttachedExtractedBlock] = []
            decisions: list[AttachmentDecision] = []
            level_counts = {1: 0, 2: 0, 3: 0, 4: 0}
            orphan_count = 0
            ambiguous_count = 0

            for verdict, block in zip(verdicts, active_blocks):
                attached = AttachedExtractedBlock(
                    **block.model_dump(exclude={"confidence_score", "evidence_level"}),
                    confidence_score=Decimal(str(round(verdict.confidence_score, 3))),
                    evidence_level=verdict.evidence_level,
                    submission_id=context.submission_id,
                    question_id=verdict.question_id,
                )
                attached_blocks.append(attached)
                model_version = verdict.model_used or (
                    f"deterministic:level{verdict.level_used}_"
                    f"{_DETERMINISTIC_LEVEL_LABELS.get(verdict.level_used, 'unknown')}"
                )
                decision_justification = verdict.justification
                if block.fused_crop_paths:
                    # §3.1/3.2/3.3 : bloc composite — le rattachement porte
                    # sur le résultat de la fusion, jamais implicite via
                    # fused_crop_paths seul (audit doc restauré, point 4).
                    decision_justification += (
                        f" [Fusion de continuité : bloc composite incluant "
                        f"{len(block.fused_crop_paths)} bloc(s) additionnel(s).]"
                    )
                decisions.append(
                    AttachmentDecision(
                        image_crop_path=block.image_crop_path,
                        question_id=verdict.question_id,
                        evidence_level=verdict.evidence_level,
                        justification=decision_justification,
                        model_version=model_version,
                        confidence_score=verdict.confidence_score,
                        level_used=verdict.level_used,
                        fallback_occurred=verdict.fallback_occurred,
                        tokens_used=verdict.tokens_used,
                    )
                )
                level_counts[verdict.level_used] = level_counts.get(verdict.level_used, 0) + 1
                if verdict.evidence_level == ExtractionEvidenceLevel.ORPHELIN:
                    orphan_count += 1
                elif verdict.evidence_level == ExtractionEvidenceLevel.AMBIGU:
                    ambiguous_count += 1

            total_duration_ms = round((time.perf_counter() - t_global_start) * 1000, 2)
            span.record_metrics(
                filtered_block_count=filtered_count,
                active_block_count=len(active_blocks),
                continuity_fusion_count=total_continuity_fusions,
                inter_page_fusion_count=inter_page_fusions,
                long_distance_fusion_count=long_distance_fusions,
                margin_annotation_fusion_count=margin_annotation_fusions,
                evidence_level_1_count=level_counts.get(1, 0),
                evidence_level_2_count=level_counts.get(2, 0),
                evidence_level_3_count=level_counts.get(3, 0),
                evidence_level_4_count=level_counts.get(4, 0),
                orphan_count=orphan_count,
                ambiguous_count=ambiguous_count,
                llm_call_count=t_llm_calls,
                total_duration_ms=total_duration_ms,
            )

            return AttachmentResult(attached_blocks=attached_blocks, decisions=decisions)

    # ---------------------------------------------------------------------------
    # Étape -1 : Fusion de continuité & pool d'indices
    # ---------------------------------------------------------------------------

    def _detect_and_fuse_continuity(
        self,
        raw_blocks: list[RawExtractedBlock],
    ) -> tuple[list[RawExtractedBlock], int, int, int, dict[str, int]]:
        """
        Étape -1 — Détection et fusion de continuité :
        3.1 — Continuité par proximité immédiate (frontière de page).
        3.2 — Continuité à longue distance (renvoi explicite).
        3.3 — Contenu en marge / annotation.
        3.4 — Pool d'indices des blocs barrés.

        Retourne les compteurs de fusion VENTILÉS (inter_page, long_distance,
        margin_annotation) séparément — jamais un seul total combiné, pour
        permettre d'observer laquelle de ces 3 dispersions domine dans un
        établissement donné (audit doc restauré, point 5).
        """
        if not raw_blocks:
            return [], 0, 0, 0, {}

        # Tri par (page_number, block_order_index)
        sorted_blocks = sorted(raw_blocks, key=lambda b: (b.page_number, b.block_order_index))

        # 3.4 — Pool d'indices des blocs barrés
        struck_index_pool: dict[str, int] = {}
        for b in sorted_blocks:
            if b.is_struck_through and b.student_label:
                norm_lbl = _normalize_label(b.student_label)
                struck_index_pool[norm_lbl] = b.page_number

        # 3.2 — résolution des cibles de renvoi longue distance, en amont du
        # parcours séquentiel (une cible peut être n'importe où dans la
        # liste, pas seulement adjacente — cf. docstring de la méthode).
        long_distance_targets = self._resolve_long_distance_targets(sorted_blocks)
        consumed_indices: set[int] = set(long_distance_targets.values())

        # 3.1 & 3.2 — Fusion inter-pages & renvois
        fused: list[RawExtractedBlock] = []
        inter_page_fusions = 0
        long_distance_fusions = 0

        i = 0
        while i < len(sorted_blocks):
            if i in consumed_indices:
                # Déjà absorbé comme cible d'une fusion 3.2 résolue plus haut
                # — jamais émis séparément, jamais candidat à une fusion 3.1.
                i += 1
                continue

            curr = sorted_blocks[i]

            # 3.2 — Renvoi longue distance résolu (marqueur explicite aux deux
            # extrémités, cf. _resolve_long_distance_targets) : priorité sur
            # la fusion par proximité 3.1, qui repose sur une heuristique
            # plus faible (adjacence + incomplétude syntaxique).
            if i in long_distance_targets:
                target = sorted_blocks[long_distance_targets[i]]
                long_distance_fusions += 1
                fused_ocr = f"{curr.prediction_ocr}\n{target.prediction_ocr}"
                composite_bbox = {
                    "x": min(curr.bounding_box.get("x", 0), target.bounding_box.get("x", 0)),
                    "y": min(curr.bounding_box.get("y", 0), target.bounding_box.get("y", 0)),
                    "width": max(curr.bounding_box.get("width", 100), target.bounding_box.get("width", 100)),
                    "height": max(curr.bounding_box.get("height", 100), target.bounding_box.get("height", 100)),
                }
                merged_block = curr.model_copy(update={
                    "prediction_ocr": fused_ocr,
                    "bounding_box": composite_bbox,
                    "fused_crop_paths": (curr.fused_crop_paths or []) + [target.image_crop_path],
                })
                fused.append(merged_block)
                i += 1
                continue

            # 3.1 — Proximité immédiate (frontière de page)
            if i + 1 < len(sorted_blocks) and (i + 1) not in consumed_indices:
                nxt = sorted_blocks[i + 1]

                # Frontière de page (p.N et p.N+1) sans rature sur aucun des deux
                is_page_boundary = (nxt.page_number == curr.page_number + 1)
                no_struck = (not curr.is_struck_through and not nxt.is_struck_through)
                no_new_label = (nxt.student_label is None)

                # Incomplétude syntaxique en fin de texte curr
                curr_txt = curr.prediction_ocr.strip()
                syntax_incomplete = (
                    bool(curr_txt)
                    and not curr_txt.endswith((".", "!", "?", ":"))
                    and (curr_txt.endswith((",", ";", "+", "=", "-", "et", "donc", "car", "avec"))
                         or len(curr_txt.split()) < 5)
                )

                if is_page_boundary and no_struck and no_new_label and syntax_incomplete:
                    inter_page_fusions += 1
                    # Fusion des deux blocs
                    fused_ocr = f"{curr.prediction_ocr}\n{nxt.prediction_ocr}"
                    composite_bbox = {
                        "x": min(curr.bounding_box.get("x", 0), nxt.bounding_box.get("x", 0)),
                        "y": min(curr.bounding_box.get("y", 0), nxt.bounding_box.get("y", 0)),
                        "width": max(curr.bounding_box.get("width", 100), nxt.bounding_box.get("width", 100)),
                        "height": max(curr.bounding_box.get("height", 100), nxt.bounding_box.get("height", 100)),
                    }
                    merged_block = curr.model_copy(update={
                        "prediction_ocr": fused_ocr,
                        "bounding_box": composite_bbox,
                        "fused_crop_paths": (curr.fused_crop_paths or []) + [nxt.image_crop_path],
                    })
                    fused.append(merged_block)
                    i += 2
                    continue

            fused.append(curr)
            i += 1

        # 3.3 — Contenu en marge/annotation : passe finale sur le résultat
        # 3.1/3.2 (pas sur sorted_blocks) — le bloc principal auquel une
        # annotation se rattache doit être celui réellement émis en sortie
        # (déjà éventuellement fusionné par 3.1/3.2), pas un bloc source
        # intermédiaire qui n'existera plus.
        fused, margin_annotation_fusions = self._apply_margin_annotations(fused)

        return (
            fused,
            inter_page_fusions,
            long_distance_fusions,
            margin_annotation_fusions,
            struck_index_pool,
        )

    _MARGIN_REFERENCE_PHRASES = ("voir marge", "cf. ci-dessus", "note en marge", "cf. ci-contre")

    def _has_margin_signal(self, block: RawExtractedBlock) -> bool:
        """
        §3.3 — Signal 1 (prioritaire) : STRUCTURE/ANNOTATED_DIAGRAM avec une
        relation déjà captée par le modèle vision (flèche/annotation
        explicite, étape 4 de l'agent 1). Signal 2 (repli) : référence
        textuelle canonique, matchée par le même mécanisme flou (rapidfuzz)
        et le même seuil que le Niveau 1. Sans l'un des deux, jamais de
        signal — pas de rattachement par proximité spatiale seule.
        """
        if (
            block.content_type == ExtractionContentType.STRUCTURE
            and block.structure_type == StructureType.ANNOTATED_DIAGRAM
            and isinstance(block.structured_output, dict)
            and block.structured_output.get("relations")
        ):
            return True

        text = (block.prediction_ocr or "").lower()
        if not text:
            return False
        return any(
            fuzz.partial_ratio(phrase, text) >= self._label_fuzzy_threshold
            for phrase in self._MARGIN_REFERENCE_PHRASES
        )

    def _apply_margin_annotations(
        self,
        blocks: list[RawExtractedBlock],
    ) -> tuple[list[RawExtractedBlock], int]:
        """
        Rattache chaque bloc de marge/annotation (cf. _has_margin_signal) au
        bloc principal non barré émis juste avant lui. Le bloc principal
        n'absorbe que la traçabilité (fused_crop_paths) — jamais le contenu
        de l'annotation, de nature différente (STRUCTURE ou simple note) du
        contenu principal. Un bloc sans signal explicite, même adjacent,
        n'est jamais touché : c'est tout l'intérêt de ce garde-fou.

        Retourne aussi le nombre de rattachements réellement effectués —
        jamais compté nulle part avant (audit doc restauré, point 5).
        """
        result: list[RawExtractedBlock] = []
        margin_annotation_fusions = 0
        for block in blocks:
            if block.is_struck_through or not self._has_margin_signal(block):
                result.append(block)
                continue

            main_idx = len(result) - 1
            while main_idx >= 0 and result[main_idx].is_struck_through:
                main_idx -= 1
            if main_idx < 0:
                # Premier bloc du document : aucun bloc principal auquel se
                # rattacher — retombe en traitement normal (Niveaux 1-4).
                result.append(block)
                continue

            main_block = result[main_idx]
            result[main_idx] = main_block.model_copy(update={
                "fused_crop_paths": (main_block.fused_crop_paths or []) + [block.image_crop_path],
            })
            margin_annotation_fusions += 1
            # block lui-même absorbé — jamais ajouté séparément à result.

        return result, margin_annotation_fusions

    _LONG_DISTANCE_PATTERN = re.compile(
        r"suite\s+(?:en\s+page|page)\s*(?P<page>\d+)"
        r"|suite\s+(?:question|q)\.?\s*(?P<question>\d+)",
        re.IGNORECASE,
    )

    def _resolve_long_distance_targets(
        self,
        sorted_blocks: list[RawExtractedBlock],
    ) -> dict[int, int]:
        """
        §3.2 — résout, pour chaque bloc source portant un marqueur de renvoi
        explicite ("suite en page X" / "suite question X"), l'unique bloc
        cible correspondant dans sorted_blocks.

        Marqueur explicite exigé aux DEUX extrémités (jamais une fusion par
        simple proximité ou numéro de page seul) : la cible doit porter un
        student_label non vide. Si le bloc source a lui-même un
        student_label, la cible doit en plus désigner la même question
        (fuzzy match rapidfuzz, même seuil que le Niveau 1) — sinon un
        student_label non vide sur la cible suffit comme preuve d'intention
        explicite.

        Ambiguïté (0 ou ≥2 candidats survivants) -> pas de fusion : jamais un
        choix arbitraire entre plusieurs cibles plausibles.
        """
        targets: dict[int, int] = {}

        for src_idx, curr in enumerate(sorted_blocks):
            match = self._LONG_DISTANCE_PATTERN.search(curr.prediction_ocr)
            if not match:
                continue

            if match.group("page") is not None:
                target_num = match.group("page")
                candidates = [
                    idx for idx, b in enumerate(sorted_blocks)
                    if idx != src_idx and b.student_label and str(b.page_number) == target_num
                ]
            else:
                target_num = match.group("question")
                candidates = [
                    idx for idx, b in enumerate(sorted_blocks)
                    if idx != src_idx and b.student_label
                    and _extract_trailing_number(_normalize_label(b.student_label)) == target_num
                ]

            if curr.student_label:
                candidates = [
                    idx for idx in candidates
                    if fuzz.ratio(
                        _normalize_label(curr.student_label),
                        _normalize_label(sorted_blocks[idx].student_label),
                    ) >= self._label_fuzzy_threshold
                ]

            if len(candidates) == 1:
                targets[src_idx] = candidates[0]
            else:
                logger.debug(
                    f"{self.AGENT_NAME}: renvoi longue distance ambigu pour le bloc "
                    f"#{src_idx} ({len(candidates)} candidat(s)) — pas de fusion."
                )

        return targets

    # ---------------------------------------------------------------------------
    # Rattachement individuel
    # ---------------------------------------------------------------------------

    async def _attach_single_block(
        self,
        block: RawExtractedBlock,
        block_idx: int,
        questions: list[QuestionRef],
        question_labels: dict[int, list[str]],
        ref_embeddings: list[list[float] | None],
        struck_index_pool: dict[str, int],
        context: AgentExecutionContext,
        inherited_label: tuple[uuid.UUID, int] | None = None,
    ) -> BlockVerdict:
        """
        Applique la hiérarchie de preuves (Niveaux 1 à 4).

        inherited_label (2026-09-03, bug réel corrigé, cas zainabsebhi) :
        student_label est documenté "repère visible à PROXIMITÉ" (cf.
        prompt OCR) — une longue réponse tapée à l'ordinateur, découpée en
        plusieurs paragraphes/blocs OCR, n'a souvent qu'UN SEUL bloc portant
        le label explicite (celui qui contient littéralement "1)") ; les
        blocs suivants, sans marqueur visuel supplémentaire, n'ont plus
        AUCUN student_label (constaté en réel : détection non déterministe
        d'un run à l'autre). Sans héritage, ces blocs retombent aux Niveaux
        2/3, qui n'ont souvent aucun signal distinctif tant que la réponse
        n'a pas encore atteint ses calculs concrets (texte de méthodologie
        générique, applicable à N'IMPORTE quelle question de même type) —
        constaté en réel : plusieurs paragraphes d'introduction de Q1
        rattachés à Q2 faute de mieux. (question_id, order) du DERNIER bloc
        confidemment LABEL_EXPLICITE (direct ou déjà hérité) — propagé par
        l'appelant tant qu'aucun NOUVEAU label explicite direct n'est
        rencontré (qui prend toujours le dessus, cf. Niveau 1 ci-dessous,
        et réinitialise donc l'héritage à la question qu'il désigne).
        """
        # --- NIVEAU 1 : Label explicite ---
        student_label = getattr(block, "student_label", None)
        if student_label:
            verdict = self._try_label_match(student_label, questions, question_labels)
            if verdict is not None:
                return verdict

        # Verification via pool d'indices (section 3.4)
        if not student_label and struck_index_pool:
            for lbl_norm, page_num in struck_index_pool.items():
                if block.page_number >= page_num:
                    verdict = self._try_label_match(lbl_norm, questions, question_labels)
                    if verdict is not None:
                        verdict.justification += f" (Indice récupéré du pool d'indices raturés p.{page_num})."
                        return verdict

        # --- NIVEAU 1.5 : Héritage du label du bloc précédent ---
        if not student_label and inherited_label is not None:
            inherited_question_id, inherited_order = inherited_label
            return BlockVerdict(
                block_index=block_idx,
                question_id=inherited_question_id,
                evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
                confidence_score=0.7,
                justification=(
                    f"Aucun label explicite propre à ce bloc — hérité du dernier "
                    f"label explicite rencontré (Q{inherited_order}), aucun nouveau "
                    "label entre-temps."
                ),
                level_used=1,
            )

        # --- NIVEAU 2 : Embeddings cosinus ---
        if block.content_type == ExtractionContentType.STRUCTURE:
            block_text = structure_to_flat_text(block.structured_output) or block.prediction_ocr
        else:
            block_text = block.prediction_ocr or ""
            if isinstance(block.structured_output, dict) and "latex" in block.structured_output:
                block_text = block.structured_output["latex"]

        block_emb = await _embed_text(block_text)

        if block_emb is None:
            # Aucun signal de similarité disponible (texte de bloc vide, ou
            # modèle d'embeddings indisponible — cf. docstring _embed_text) —
            # jamais fabriquer une similarité ni conclure ORPHELIN sans
            # preuve : défère directement au Niveau 3, qui ne dépend pas des
            # embeddings.
            top_indices = list(range(min(3, len(questions))))
            return await self._llm_arbitration(
                block=block,
                block_idx=block_idx,
                questions=questions,
                top_indices=top_indices,
                similarities=[None] * len(questions),
                context=context,
            )

        # Similarité calculée UNIQUEMENT pour les questions dont l'embedding
        # de référence est disponible (ref_emb non None) — préserve l'index
        # d'origine dans `questions` pour retomber juste même si certaines
        # références n'ont pas pu être vectorisées.
        candidates = [
            (idx, _cosine_similarity(block_emb, ref_emb))
            for idx, ref_emb in enumerate(ref_embeddings)
            if ref_emb is not None
        ]
        similarities: list[float | None] = [
            (next((s for i, s in candidates if i == idx), None))
            for idx in range(len(ref_embeddings))
        ]

        if not candidates:
            return BlockVerdict(
                block_index=block_idx,
                question_id=None,
                evidence_level=ExtractionEvidenceLevel.ORPHELIN,
                confidence_score=0.0,
                justification="Aucune question candidate disponible (embeddings de référence indisponibles).",
                level_used=4,
            )

        candidates.sort(key=lambda pair: pair[1], reverse=True)
        best_idx, best_sim = candidates[0]

        # NIVEAU 4 : Similarité cosinus maximale sous le seuil orphelin → ORPHELIN direct
        if best_sim < self._orphan_similarity_threshold:
            return BlockVerdict(
                block_index=block_idx,
                question_id=None,
                evidence_level=ExtractionEvidenceLevel.ORPHELIN,
                confidence_score=float(best_sim),
                justification=(
                    f"Similarité cosinus maximale ({best_sim:.3f}) < "
                    f"{self._orphan_similarity_threshold} — aucune question candidate plausible."
                ),
                level_used=4,
            )

        # Si delta net avec le 2e candidat → NIVEAU 2
        if len(candidates) >= 2:
            second_sim = candidates[1][1]
            delta = best_sim - second_sim
        else:
            delta = 1.0

        # Bug réel corrigé (2026-09-03, cas zainabsebhi) : un delta net ne
        # suffit pas seul — best_sim doit AUSSI dépasser un plancher absolu
        # de confiance, sinon un best_sim faible (contenu mal capturé par
        # l'embedding général all-MiniLM-L6-v2 pour deux exercices très
        # proches en vocabulaire) peut quand même produire un delta ≥ seuil
        # et rattacher un bloc à la mauvaise question avec un faux air de
        # certitude. Sous ce plancher : toujours déférer au Niveau 3 (LLM),
        # jamais conclure seul, quel que soit le delta.
        if delta >= self._cosine_threshold and best_sim >= self._min_confident_similarity:
            q = questions[best_idx]
            return BlockVerdict(
                block_index=block_idx,
                question_id=q.question_id,
                evidence_level=ExtractionEvidenceLevel.CONTENU_VS_REFERENCE,
                confidence_score=min(1.0, best_sim),
                justification=(
                    f"Similarité cosinus nette avec Q{q.order} "
                    f"(delta={delta:.3f} ≥ seuil={self._cosine_threshold}, "
                    f"best_sim={best_sim:.3f} ≥ plancher={self._min_confident_similarity})."
                ),
                level_used=2,
            )

        # NIVEAU 3 : LLM arbitrage pour cas ambigus
        top_indices = [idx for idx, _ in candidates[:3]]
        return await self._llm_arbitration(
            block=block,
            block_idx=block_idx,
            questions=questions,
            top_indices=top_indices,
            similarities=similarities,
            context=context,
        )

    def _try_label_match(
        self,
        student_label: str,
        questions: list[QuestionRef],
        question_labels: dict[int, list[str]],
    ) -> BlockVerdict | None:
        """
        Matching flou du label étudiant contre tous les labels attendus.
        """
        normalized = _normalize_label(student_label)
        best_score = 0
        best_q_idx = -1

        for q_idx, labels in question_labels.items():
            for label in labels:
                score = fuzz.ratio(normalized, label)
                if score > best_score:
                    best_score = score
                    best_q_idx = q_idx

        if best_score >= self._label_fuzzy_threshold and best_q_idx >= 0:
            q = questions[best_q_idx]
            return BlockVerdict(
                block_index=-1,
                question_id=q.question_id,
                evidence_level=ExtractionEvidenceLevel.LABEL_EXPLICITE,
                confidence_score=best_score / 100.0,
                justification=(
                    f"Label étudiant '{student_label}' reconnu → Q{q.order} "
                    f"(score rapidfuzz={best_score}/100)."
                ),
                level_used=1,
            )
        return None

    async def _llm_arbitration(
        self,
        block: RawExtractedBlock,
        block_idx: int,
        questions: list[QuestionRef],
        top_indices: list[int],
        similarities: list[float | None],
        context: AgentExecutionContext,
    ) -> BlockVerdict:
        """
        Niveau 3 : Arbitrage LLM ciblé.
        """
        def _sim_text(idx: int) -> str:
            sim = similarities[idx]
            return f"{sim:.3f}" if sim is not None else "indisponible"

        # Bug réel corrigé (2026-09-03, cas zainabsebhi) : ce Niveau 3 ne
        # montrait au LLM qu'un résumé ABSTRAIT (reasoning_summary, prose
        # générique du type "résout par équilibre des forces") — jamais les
        # formules réelles de la solution de référence, contrairement au
        # Niveau 2 qui embed déjà reference_content en entier (cf. ref_
        # embeddings ci-dessus). Deux exercices de méthode identique (même
        # type de treillis, même démarche) produisent des résumés quasi
        # identiques, rendant le Niveau 3 aveugle aux marqueurs distinctifs
        # réels (ex. sin α = 1/√5 pour Q1 vs sin β = 1/√2 pour Q2) — constaté
        # en test réel : le LLM confirmait la mauvaise question avec 0.85-0.95
        # de confiance en se basant sur des généralités ("méthode par
        # équilibre des nœuds") au lieu du contenu mathématique concret.
        # Extrait de reference_content (pas le texte intégral, économie de
        # tokens) ajouté en plus du résumé, jamais à sa place — le résumé
        # garde son rôle de contexte lisible, l'extrait apporte les
        # marqueurs concrets qui permettent de trancher.
        candidates_summary = "\n".join([
            f"[{i}] Q{questions[idx].order} (section {questions[idx].section_order or 'N/A'}) "
            f"— résumé : {questions[idx].reference_summary or 'non disponible'} "
            f"— extrait de la solution de référence : "
            f"{(questions[idx].reference_content or 'non disponible')[:3000]} "
            f"(similarité cosinus : {_sim_text(idx)})"
            for i, idx in enumerate(top_indices)
        ])

        user_msg = QUESTION_ATTACHMENT_USER_TEMPLATE.format(
            content_type=block.content_type,
            raw_text=block.prediction_ocr[:500],
            student_label=getattr(block, "student_label", "non fourni"),
            candidates_summary=candidates_summary,
        )

        messages = [
            {"role": "system", "content": QUESTION_ATTACHMENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        for attempt in range(2):
            try:
                result, spec, fallback, token_usage = await invoke_llm_with_fallback(
                    task_type=TaskType.DOCUMENT_STRUCTURING,
                    messages=messages,
                    response_schema=_QuestionArbitrationSchema,
                    context=context,
                )
                parsed = (
                    result if isinstance(result, _QuestionArbitrationSchema)
                    else _QuestionArbitrationSchema.model_validate(result)
                )
            except Exception as e:
                logger.warning(f"Erreur LLM Niveau 3 pour bloc #{block_idx} : {e}")
                if attempt == 0:
                    continue
                return BlockVerdict(
                    block_index=block_idx,
                    question_id=questions[top_indices[0]].question_id if top_indices else None,
                    evidence_level=ExtractionEvidenceLevel.AMBIGU,
                    confidence_score=0.2,
                    justification=f"Erreur LLM après retry : {e!s:.200}",
                    level_used=3,
                )

            model_used = f"{spec.provider}:{spec.model_name}"

            if parsed.verdict == "ATTACHED" and parsed.question_index is not None:
                q_index = parsed.question_index
                if q_index < 0 or q_index >= len(top_indices):
                    # Hallucination d'index : retry unique, jamais un AMBIGU
                    # direct dès la première tentative.
                    if attempt == 0:
                        continue
                    return BlockVerdict(
                        block_index=block_idx,
                        question_id=None,
                        evidence_level=ExtractionEvidenceLevel.AMBIGU,
                        confidence_score=0.3,
                        justification=(
                            f"LLM question_index ({q_index}) invalide après retry "
                            "— forcé en AMBIGU."
                        ),
                        model_used=model_used,
                        fallback_occurred=fallback,
                        tokens_used=token_usage.get("total_tokens", 0),
                        level_used=3,
                    )
                real_q_idx = top_indices[q_index]
                q = questions[real_q_idx]
                return BlockVerdict(
                    block_index=block_idx,
                    question_id=q.question_id,
                    evidence_level=ExtractionEvidenceLevel.CONTENU_VS_REFERENCE,
                    confidence_score=parsed.confidence,
                    justification=parsed.justification,
                    model_used=model_used,
                    fallback_occurred=fallback,
                    tokens_used=token_usage.get("total_tokens", 0),
                    level_used=3,
                )
            elif parsed.verdict == "ORPHELIN":
                return BlockVerdict(
                    block_index=block_idx,
                    question_id=None,
                    evidence_level=ExtractionEvidenceLevel.ORPHELIN,
                    confidence_score=parsed.confidence,
                    justification=parsed.justification,
                    model_used=model_used,
                    fallback_occurred=fallback,
                    tokens_used=token_usage.get("total_tokens", 0),
                    level_used=4,
                )
            else:  # AMBIGU
                return BlockVerdict(
                    block_index=block_idx,
                    question_id=questions[top_indices[0]].question_id if top_indices else None,
                    evidence_level=ExtractionEvidenceLevel.AMBIGU,
                    confidence_score=parsed.confidence,
                    justification=parsed.justification,
                    model_used=model_used,
                    fallback_occurred=fallback,
                    tokens_used=token_usage.get("total_tokens", 0),
                    level_used=3,
                )

        return BlockVerdict(
            block_index=block_idx,
            question_id=None,
            evidence_level=ExtractionEvidenceLevel.AMBIGU,
            confidence_score=0.1,
            justification="Échec inattendu du niveau 3 — forcé en AMBIGU.",
            level_used=3,
        )

    # ---------------------------------------------------------------------------
    # Contrôle qualité & Cohérence
    # ---------------------------------------------------------------------------

    def _resolve_label_conflicts(
        self,
        verdicts: list[BlockVerdict],
        blocks: list[RawExtractedBlock],
    ) -> list[BlockVerdict]:
        """
        §14 — Détection des conflits : deux blocs distincts tous les deux
        en Niveau 1 (LABEL_EXPLICITE) attachés à la même question.

        Bug réel corrigé (2026-09-03, test réel zainabsebhi) : une copie
        tapée à l'ordinateur, découpée en plusieurs blocs OCR PAR PARAGRAPHE
        pour une même réponse, fait porter le MÊME label explicite ("1)",
        seul repère visible le long de toute la réponse — cf. docstring
        student_label, "repère visible à PROXIMITÉ" — à 7 blocs consécutifs
        d'affilée. Ce n'est pas un conflit : c'est la confirmation RÉPÉTÉE
        et cohérente du même label sur une réponse longue, le signal le plus
        fiable qui soit (Niveau 1). Forcer ces 7 blocs en AMBIGU les a fait
        perdre leur rattachement à la question qu'ils décrivent réellement.
        Un vrai conflit, en revanche, c'est le MÊME label réapparaissant à
        deux endroits NON CONSÉCUTIFS du document (ex. après un passage
        rattaché à une autre question) — signe que l'étudiant est peut-être
        revenu en arrière, ambigu. D'où la distinction : seuls des indices
        NON CONTIGUS pour un même label/question restent un vrai conflit ;
        un bloc CONSÉCUTIF de blocs portant le même label est une réponse
        longue normale, jamais forcé en AMBIGU.
        """
        level1_by_question: dict[uuid.UUID, list[int]] = {}
        for i, v in enumerate(verdicts):
            if (
                v.evidence_level == ExtractionEvidenceLevel.LABEL_EXPLICITE
                and v.question_id is not None
            ):
                level1_by_question.setdefault(v.question_id, []).append(i)

        updated = list(verdicts)
        for q_id, indices in level1_by_question.items():
            is_contiguous_run = indices == list(range(indices[0], indices[0] + len(indices)))
            if len(indices) >= 2 and not is_contiguous_run:
                for i in indices:
                    v = updated[i]
                    block_labels = [
                        getattr(blocks[j], "student_label", "?") for j in indices
                    ]
                    updated[i] = BlockVerdict(
                        block_index=v.block_index,
                        question_id=None,
                        evidence_level=ExtractionEvidenceLevel.AMBIGU,
                        confidence_score=0.4,
                        justification=(
                            f"Conflit de label : {len(indices)} blocs portent un label "
                            f"attribué à Q{v.question_id} — labels : {block_labels}. Forcé en AMBIGU."
                        ),
                        model_used=v.model_used,
                        level_used=v.level_used,
                    )
                    logger.warning(f"Conflit de label détecté : {len(indices)} blocs → question_id={q_id}")

        return updated

    def _check_referral_consistency(
        self,
        verdicts: list[BlockVerdict],
        blocks: list[RawExtractedBlock],
        questions: list[QuestionRef],
    ) -> list[BlockVerdict]:
        """
        §16 — Cohérence bornée des renvois : si un bloc fait référence explicite ('voir Q2')
        mais est rattaché à une autre question sans raison, ajuste la justification.
        """
        updated = list(verdicts)
        q_by_order = {q.order: q for q in questions}

        for i, (v, b) in enumerate(zip(verdicts, blocks)):
            match_ref = re.search(r"(?:voir|cf\.?)\s*(?:question|q)?\s*(\d+)", b.prediction_ocr, re.IGNORECASE)
            if match_ref:
                target_q_num = int(match_ref.group(1))
                target_q = q_by_order.get(target_q_num)
                if target_q and v.question_id != target_q.question_id:
                    updated[i].justification += (
                        f" [Note de cohérence : le texte mentionne 'voir Q{target_q_num}', "
                        f"mais la preuve l'a rattaché à {v.question_id or 'AMBIGU'}]."
                    )

        return updated
