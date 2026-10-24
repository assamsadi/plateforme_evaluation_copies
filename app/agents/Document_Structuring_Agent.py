"""
Agent 3 — Document_Structuring_Agent

Transforme le document unique déposé par le professeur (énoncé + correction)
en une structure logique d'exercice :
- ExerciseSection (parties/exercices si présent)
- Question (une par groupe d'énoncé délimité par un numéro)
- TeacherCorrectionBlock (rattachement de chaque bloc de correction)

Ne juge rien pédagogiquement — uniquement de la structuration.

Pipeline en 7 étapes :
  0. Filtrage des blocs barrés (is_struck_through=True)
  1. Précondition : l'exercice doit être en statut DRAFT
  2. Classification LLM bloc par bloc (STATEMENT / CORRECTION / AUTRE + détection labels)
  3. Détection des ExerciseSection (étape 3bis — marqueurs explicites de section)
  4. Regroupement & création des Question (order continu global sur l'exercice)
  5. Rattachement des blocs CORRECTION à leurs questions (LABEL_EXPLICITE ou UNRESOLVED_NO_LABEL)
  6. Contrôle qualité & vérification de complétude stricte (COMPLETE vs INCOMPLETE)
"""
import asyncio
import hashlib
import io
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Literal

from PIL import Image
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from app.agents.context import AgentExecutionContext
from app.agents.ocr_block_utils import filter_structuring_block
from app.agents.document_structuring_exceptions import (
    ExerciseAlreadyPublishedError,
    StructuringIncompleteError,
)
from app.core.config import settings
from app.core.exceptions import ExerciseNotFoundError
from app.domain.models.competency.c2pct_scaffold import get_all_subquestions
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType, ExtractionOrigin
from app.domain.models.assessment.teacher_correction_block import BlockEvidenceLevel
from app.domain.schemas.submission_schemas import RawExtractedBlock
from app.infra_services.storage_service import StorageContainer, storage_service
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType
from app.observability.langfuse import AgentTraceSpan
from app.prompts.document_structuring_prompt import (
    CORRECTION_ATTACHMENT_SYSTEM_PROMPT,
    CORRECTION_ATTACHMENT_USER_TEMPLATE,
    CORRECTION_CONFLICT_SYSTEM_PROMPT,
    CORRECTION_CONFLICT_USER_TEMPLATE,
    DOCUMENT_STRUCTURING_SYSTEM_PROMPT,
    DOCUMENT_STRUCTURING_USER_TEMPLATE,
    QUESTION_GROUPING_SYSTEM_PROMPT,
    QUESTION_GROUPING_USER_TEMPLATE,
    STRUCTURED_CONTENT_MAX_CHARS,
    STRUCTURED_CONTENT_SECTION_TEMPLATE,
)

logger = logging.getLogger(__name__)

# Addendum injecté dans le prompt système de _classify_block — instruction GÉNÉRALE
# (jamais limitée à une méthodologie nommée) pour détecter is_supporting_content,
# complétée par la liste des 15 sous-questions officielles C2PCT/CHAABI (générée
# depuis c2pct_scaffold.py, JAMAIS dupliquée en dur ici, cf. son docstring "seule
# source de vérité") comme UN signal parmi d'autres, pas le seul critère — un
# document utilisant une autre méthodologie (ou aucune) doit rester détectable par
# le raisonnement général seul. Chaque bloc étant classifié isolément (sans voir les
# blocs voisins), une règle purement descriptive ne suffit pas si le bloc ne répète
# pas l'intitulé de la phase à côté de son numéro (ex. bloc "1.1- Escribe toda la
# información..." seul, sans "1° REFORMULAR LA TAREA" à proximité dans CE bloc) —
# constaté en test réel (agents_tests/step3_test_document_structuring_probe*.py).
# La liste explicite permet aussi la correspondance sémantique dans une langue
# différente du français source (ex. document en espagnol).
# Référentiel des 15 sous-questions C2PCT/CHAABI, construit UNE SEULE FOIS et
# partagé par _SUPPORTING_CONTENT_ADDENDUM (1er passage, par bloc) ET
# _C2PCT_GROUPING_ADDENDUM (2e passage, regroupement holistique, cf. plus bas)
# — jamais dupliqué en dur, cf. docstring c2pct_scaffold.py "seule source de
# vérité".
_C2PCT_SUBQUESTIONS_REFERENCE_BLOCK = "\n".join(
    f"- {sq.id} : {sq.reference_prompt}" for sq in get_all_subquestions()
)

_SUPPORTING_CONTENT_ADDENDUM = (
    "\n\nis_supporting_content=true pour TOUT bloc de contenu préparatoire ou "
    "méthodologique (donnée listée, schéma préparatoire, étape intermédiaire, "
    "sous-tâche, réponse partielle...) qui accompagne un problème sans être "
    "l'énoncé du problème lui-même — quelle que soit la méthodologie sous-jacente, "
    "y compris une méthodologie non listée ci-dessous ou l'absence de méthodologie "
    "nommée. Retourne aussi question_label=null pour un tel bloc, quel que soit le "
    "numéro écrit à côté (\"1°\", \"1.1\", \"3.2\"...) : ce n'est jamais un numéro de "
    "question. Un bloc qui EST l'énoncé du problème (ou un titre d'exercice) doit "
    "avoir is_supporting_content=false, même sans label.\n\n"
    "Référentiel officiel des 15 sous-questions de la méthodologie C2PCT/CHAABI, "
    "UN signal parmi d'autres (peuvent apparaître traduites/reformulées dans une "
    "autre langue que ci-dessous) — un bloc qui y correspond, même approximativement, "
    "est TOUJOURS is_supporting_content=true, mais l'absence de correspondance ne "
    "signifie pas automatiquement false (d'autres formes de contenu préparatoire "
    "existent, cf. règle générale ci-dessus) :\n"
    + _C2PCT_SUBQUESTIONS_REFERENCE_BLOCK
)

# Addendum optionnel du 2e passage (QUESTION_GROUPING_SYSTEM_PROMPT), injecté
# UNIQUEMENT si le document entier est détecté comme utilisant la méthodologie
# C2PCT/CHAABI (cf. Document_Structuring_Agent._looks_like_c2pct_document) —
# jamais pour un document générique, qui doit garder le prompt de regroupement
# volontairement neutre (cf. docstring QUESTION_GROUPING_SYSTEM_PROMPT).
# Motif : le 1er passage (_classify_block) connaît déjà ce référentiel, mais le
# 2e passage — celui qui décide RÉELLEMENT des frontières de question — ne
# l'avait pas, alors qu'il dispose d'un signal bien plus fort que le jugement
# sémantique seul : la numérotation officielle. Constaté en test réel : un
# document où le même diagramme d'énoncé était redessiné/redécrit différemment
# par l'OCR à chaque page faisait échouer la règle générique #1 du prompt
# ("répété MOT POUR MOT") — la numérotation, elle, ne varie jamais.
_C2PCT_GROUPING_ADDENDUM = (
    "\n\nCe document utilise la méthodologie C2PCT/CHAABI — référentiel officiel "
    "des 15 sous-questions (peuvent apparaître traduites/reformulées) :\n"
    + _C2PCT_SUBQUESTIONS_REFERENCE_BLOCK
    + "\n\nSignal supplémentaire, PRIORITAIRE sur le jugement sémantique seul quand "
    "il est présent : la numérotation \"<n° problème>.<n° sous-question>\" (ex. "
    "\"1.1\", \"1.2\", \"2.1\"...) est CONTINUE au sein d'UN MÊME problème — toutes "
    "les sous-questions 1.1 à 7.2 (ou jusqu'à la dernière rencontrée) d'un même "
    "numéro de problème appartiennent au MÊME groupe, quelle que soit la diversité "
    "de leur contenu (schéma, texte, calcul...) ou la variation de leur description "
    "d'un bloc à l'autre. Un RETOUR à \"1.1\" après avoir déjà vu une numérotation "
    "aller jusqu'à \"6.x\" ou \"7.x\" signale un NOUVEAU problème distinct — c'est le "
    "signal le plus fiable de changement de problème sur ce type de document, plus "
    "fiable qu'une simple différence de contenu entre deux blocs."
    "\n\nERREUR FRÉQUENTE À NE JAMAIS COMMETTRE (bug réel constaté, examen à "
    "plusieurs exercices) : NE regroupe JAMAIS les blocs par ÉTIQUETTE DE "
    "SOUS-QUESTION IDENTIQUE à travers le document (ex. mettre tous les blocs "
    "\"1.1\" ensemble, tous les blocs \"1.2\" ensemble, etc., peu importe le "
    "problème auquel ils appartiennent). C'est FAUX : chaque groupe est UN "
    "PROBLÈME ENTIER (toutes ses sous-questions 1.1 à 7.2 ENSEMBLE), jamais une "
    "seule sous-question isolée répétée sur plusieurs problèmes.\n"
    "Exemple avec 3 problèmes consécutifs, chacun redémarrant sa numérotation à "
    "1.1 :\n"
    "  Blocs vus dans l'ordre : [0]=1.1(pb1) [1]=1.2(pb1) [2]=...(pb1, jusqu'à "
    "7.2) [3]=1.1(pb2) [4]=1.2(pb2) [5]=...(pb2, jusqu'à 7.2) [6]=1.1(pb3) "
    "[7]=1.2(pb3) ...\n"
    "  CORRECT (3 groupes, un par problème) : {\"groups\": ["
    "{\"question_label\": null, \"block_indices\": [0, 1, 2, ...]}, "
    "{\"question_label\": null, \"block_indices\": [3, 4, 5, ...]}, "
    "{\"question_label\": null, \"block_indices\": [6, 7, ...]}]}\n"
    "  FAUX, NE JAMAIS FAIRE (groupé par numéro de sous-question au lieu du "
    "problème) : {\"groups\": ["
    "{\"question_label\": \"1.1\", \"block_indices\": [0, 3, 6]}, "
    "{\"question_label\": \"1.2\", \"block_indices\": [1, 4, 7]}, ...]}"
)


# ---------------------------------------------------------------------------
# Structures de données internes pour le pipeline d'agent
# ---------------------------------------------------------------------------

class BlockClassificationResult(BaseModel):
    """
    Sortie structurée LLM pour _classify_block (cf. DOCUMENT_STRUCTURING_
    SYSTEM_PROMPT pour le contrat exact) — remplace l'ancienne extraction
    par regex (recherche de la première/dernière accolade sur texte libre)
    + json.loads. Cette regex captait une paire d'accolades invalide dès
    que raw_text contenait du LaTeX (frac{...}{...}, sigma_{max}) —
    constaté de façon reproductible sur les blocs EQUATION, identique sur
    Groq ET OpenRouter (donc un problème de PARSING, pas d'un fournisseur
    en particulier) — cf. agents_tests/step3_test_document_structuring_probe*.py.
    """
    classification: Literal["STATEMENT", "CORRECTION", "AUTRE"]
    section_label: str | None = None
    question_label: str | None = None
    # True si ce bloc est du contenu préparatoire/méthodologique (donnée listée,
    # schéma, étape intermédiaire...) plutôt que l'énoncé du problème lui-même — cf.
    # _SUPPORTING_CONTENT_ADDENDUM, généralisé à N'IMPORTE QUELLE méthodologie, pas
    # seulement C2PCT/CHAABI. Simple INDICE transmis au 2e passage (cf.
    # _partition_statement_blocks_into_questions) — jamais suivi aveuglément, jugé
    # bloc par bloc donc pas fiable à 100% seul (cf. sa docstring).
    is_supporting_content: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    justification: str


@dataclass
class ClassifiedBlock:
    """Bloc d'entrée après classification LLM."""
    raw_block: RawExtractedBlock
    block_index: int
    classification: str  # "STATEMENT", "CORRECTION", "AUTRE"
    section_label: str | None
    question_label: str | None
    confidence: float
    justification: str
    is_supporting_content: bool = False
    model_used: str | None = None
    fallback_occurred: bool = False
    tokens_used: int = 0
    # Renseignés par _attach_corrections() pour les blocs CORRECTION rattachés :
    # l'order global de la Question matchée, et l'order de sa section (si applicable).
    assigned_question_order: int | None = None
    assigned_question_section_order: int | None = None
    # Dédoublonnage d'images DIAGRAM/STRUCTURE (cf. _detect_duplicate_diagrams) —
    # identifiant du bloc PRIMAIRE (index dans active_blocks) partagé par tous
    # les membres d'un même groupe de doublons (primaire inclus, mappé sur
    # lui-même) ; None si le bloc est unique ou non concerné. Traverse
    # _extract_sections/_build_questions intact (mêmes objets, jamais reclonés)
    # pour permettre à _partition_statement_blocks_into_questions de ré-fusionner
    # déterministiquement les doublons, quelle que soit leur position locale
    # dans la section — jamais via un jugement LLM sur du texte OCR variable.
    dedup_group_id: int | None = None
    # Renseigné par _attach_corrections() pour CHAQUE bloc CORRECTION (résolu ou
    # non) — remplace l'ancienne inférence "assigned_question_order is not None
    # => LABEL_EXPLICITE" (fausse pour les 2 nouveaux chemins de repli, cf.
    # BlockEvidenceLevel). None pour les blocs STATEMENT/AUTRE, jamais consommé.
    evidence_level: BlockEvidenceLevel | None = None


@dataclass
class SectionSpec:
    """Spécification d'une section d'exercice détectée."""
    order: int
    title: str
    section_label: str
    blocks: list[ClassifiedBlock] = field(default_factory=list)


class QuestionGroupResult(BaseModel):
    """Un groupe de blocs (par index, cf. QuestionGroupingResult) formant UNE question réelle."""
    question_label: str | None = None
    block_indices: list[int]


class QuestionGroupingResult(BaseModel):
    """
    Sortie structurée du 2e passage LLM (cf. _partition_statement_blocks_into_
    questions et QUESTION_GROUPING_SYSTEM_PROMPT) — regroupement holistique de
    TOUS les blocs STATEMENT d'une section en un seul appel, contrairement à
    _classify_block qui juge chaque bloc isolément sans contexte des autres.
    """
    groups: list[QuestionGroupResult]


class CorrectionAttachmentResult(BaseModel):
    """Rattachement d'UN bloc de correction (par index) à une question candidate (par index), ou null si indéterminable."""
    block_index: int
    question_index: int | None = None


class CorrectionAttachmentBatchResult(BaseModel):
    """
    Sortie structurée du 3e passage LLM (cf. _attach_unresolved_corrections_via_
    llm et CORRECTION_ATTACHMENT_SYSTEM_PROMPT) — rattachement holistique de
    plusieurs blocs de correction sans label exploitable à la bonne question
    parmi PLUSIEURS candidates réelles de la même section (le cas à une seule
    question candidate est déjà réglé sans appel LLM par l'appelant).
    """
    attachments: list[CorrectionAttachmentResult]


class CorrectionConflictGroup(BaseModel):
    """Un groupe de blocs (par index) mutuellement contradictoires — jamais juste différents."""
    block_indices: list[int]
    reason: str


class CorrectionConflictDetectionResult(BaseModel):
    """
    Sortie structurée du 4e passage LLM (cf. _detect_correction_conflicts_via_
    llm et CORRECTION_CONFLICT_SYSTEM_PROMPT) — détection holistique de
    contradictions RÉELLES entre les blocs de correction d'une même question,
    remplace une ancienne heuristique par paire (similarité de texte) qui
    signalait à tort des blocs simplement différents mais complémentaires.
    """
    conflicts: list[CorrectionConflictGroup]


@dataclass
class QuestionSpec:
    """Spécification d'une question à créer."""
    order: int
    question_label: str
    statement: str
    section_order: int | None
    statement_blocks: list[ClassifiedBlock] = field(default_factory=list)
    correction_blocks: list[ClassifiedBlock] = field(default_factory=list)


@dataclass
class StructuringReport:
    """Rapport de complétude produit par l'agent."""
    exercise_id: uuid.UUID
    status: str  # "COMPLETE" ou "INCOMPLETE"
    sections_created: list[dict]
    questions_created: list[dict]
    correction_blocks_created: list[dict]
    unresolved_block_count: int
    questions_without_correction_count: int
    label_conflict_count: int
    empty_section_count: int
    unlabelled_statement_block_count: int = 0
    correction_label_conflict_count: int = 0
    details: dict = field(default_factory=dict)
    # Une entrée par bloc classifié (STATEMENT/CORRECTION/AUTRE confondus) —
    # alimente AgentDecisionLog côté service (§16 du doc de référence).
    block_classifications: list[dict] = field(default_factory=list)
    # Localisation précise des manques/conflits agrégés ci-dessus — pas
    # seulement des compteurs : le professeur doit voir OÙ est le problème.
    empty_sections_detail: list[dict] = field(default_factory=list)
    label_conflicts_detail: list[dict] = field(default_factory=list)
    correction_label_conflicts_detail: list[dict] = field(default_factory=list)
    # Une entrée par appel LLM de _partition_statement_blocks_into_questions
    # (cf. sa docstring) — alimente AgentDecisionLog côté service, seule trace
    # a posteriori de ce que le LLM de regroupement a vu/proposé (jusqu'ici
    # invisible, contrairement à la classification bloc par bloc).
    question_grouping_decisions: list[dict] = field(default_factory=list)


# Taille de lot maximale pour _attach_unresolved_corrections_via_llm (2026-09-03,
# bug réel constaté sur un examen à 3 exercices partageant la même section) —
# cf. son site d'appel dans _attach_corrections pour le détail complet du bug
# et du raisonnement.
_CORRECTION_ATTACHMENT_BATCH_SIZE = 20

# ---------------------------------------------------------------------------
# Classe Principale de l'Agent 3
# ---------------------------------------------------------------------------

class DocumentStructuringAgent:
    """
    Agent 3 : Structuration du document professeur (énoncé + correction).

    Pipeline déterministe et LLM pour extraire l'arborescence Exercise -> Sections -> Questions -> Corrections.
    """

    AGENT_NAME = "Document_Structuring_Agent"

    # Dédoublonnage d'images (cf. _detect_duplicate_diagrams) — content_types
    # concernés (schémas/figures redessinés en rappel sur plusieurs pages) et
    # seuil de distance de Hamming (hash average 8x8 = 64 bits) sous lequel
    # deux images sont considérées comme le même diagramme rescanné. Valeur
    # conservatrice choisie pour tolérer le bruit de rescan/redessin sans
    # confondre deux diagrammes réellement différents — à resserrer si des
    # faux positifs sont constatés en usage réel.
    _DEDUP_CONTENT_TYPES = {ExtractionContentType.DIAGRAM, ExtractionContentType.STRUCTURE}
    _DUPLICATE_IMAGE_HAMMING_THRESHOLD = 6

    # Dédoublonnage de texte (B6, backlog_bugs_c2pct.md, 2026-08-29, cf.
    # _detect_duplicate_text_blocks) — mécanisme SÉPARÉ de celui des images
    # ci-dessus (comparaison exacte sur texte normalisé, jamais une distance
    # floue) : un même énoncé IMPRIMÉ transcrit deux fois par l'OCR donne un
    # texte quasi-identique (contrairement à un diagramme rescanné, sujet à
    # du bruit visuel réel) — un flou introduirait ici un risque de fusionner
    # à tort deux sous-questions réellement différentes, pire qu'un doublon
    # manqué. Seuil de longueur minimale : jamais dédupliquer un fragment
    # court (numéro de page, "1.", etc.) où une coïncidence textuelle est
    # plausible et le gain négligeable.
    _TEXT_DEDUP_MIN_LENGTH = 40

    # Exclusion des tableaux de barème du dédoublonnage de texte ci-dessus —
    # bug réel constaté (2026-09-04, examen C2PCT à 3 exercices) : un barème
    # C2PCT natif réutilisant le même gabarit de points d'un exercice à
    # l'autre (ex. "1.1 → 0.3, 1.2 → 0.3, ...", chiffres identiques sur
    # Ejercicio 1 ET Ejercicio 2) redevient, une fois normalisé, un texte
    # BYTE POUR BYTE identique à celui d'un autre exercice — exactement le
    # signal que _detect_duplicate_text_blocks interprète comme "même énoncé
    # réimprimé en rappel" (son cas d'usage d'origine). Un vrai barème
    # d'Ejercicio 2 se retrouvait alors purement et simplement absorbé comme
    # doublon d'Ejercicio 1, jamais reclassé pour lui-même — perte
    # silencieuse d'un barème entier. Un tableau de barème se reconnaît
    # déterministiquement à sa forte densité de nombres décimaux courts
    # (identifiants de sous-question "N.N" ET/OU valeurs de points), très
    # rare dans un énoncé/des instructions en prose normale. Seuil
    # volontairement bas : le coût d'un faux positif ici (un vrai doublon de
    # mise en page non reconnu, donc reclassé par LLM en plus) est très
    # inférieur au coût d'un faux négatif (un barème entier disparu en
    # silence).
    _BAREME_DECIMAL_PATTERN = re.compile(r"\b\d{1,2}\.\d{1,2}\b")
    _BAREME_MIN_DECIMAL_MATCHES = 4

    @classmethod
    def _looks_like_bareme_table(cls, normalized_text: str) -> bool:
        return len(cls._BAREME_DECIMAL_PATTERN.findall(normalized_text)) >= cls._BAREME_MIN_DECIMAL_MATCHES

    # Détection best-effort "ce document utilise C2PCT/CHAABI" — même principe
    # (deux motifs indépendants, OU logique) que le prefilter Cas 0 déjà
    # éprouvé dans Extraction_Verification_Agent (jamais importé d'ici :
    # c2pct_scaffold.py documente explicitement "aucune détection, aucune
    # logique métier" comme contrainte de conception de ce module — cette
    # détection reste donc locale à chaque agent qui en a besoin, chacun sur
    # SA propre notion de "texte du document").
    _SUBQUESTION_ID_PATTERN = re.compile(r"\b\d\.\d\b")
    _C2PCT_METHODOLOGY_MENTION_PATTERN = re.compile(r"c2pct|chaabi", re.IGNORECASE)

    @classmethod
    def _looks_like_c2pct_document(cls, full_document_text: str) -> bool:
        return bool(
            cls._SUBQUESTION_ID_PATTERN.search(full_document_text or "")
            or cls._C2PCT_METHODOLOGY_MENTION_PATTERN.search(full_document_text or "")
        )

    async def execute(
        self,
        raw_blocks: list[RawExtractedBlock],
        exercise_status: ExerciseStatus,
        context: AgentExecutionContext,
    ) -> StructuringReport:
        """
        Exécute la structuration sur un ensemble de blocs bruts d'un exercice.

        raw_blocks      : Liste des blocs OCR bruts produits par Agent 1.
        exercise_status : Statut actuel de l'exercice (DRAFT exigé).
        context         : Contexte d'exécution de l'agent.

        Retourne StructuringReport avec status="COMPLETE" ou "INCOMPLETE".
        """
        exercise_id = context.exercise_id or uuid.UUID(int=0)

        span_metadata = {
            "flow_type": context.flow_type,
            "exercise_id": str(exercise_id),
            "professor_id": str(context.user_id) if context.user_id else None,
        }

        with AgentTraceSpan(self.AGENT_NAME, trace_id=context.trace_id, metadata=span_metadata) as span:
            t_start = time.perf_counter()

            # ----------------------------------------------------------------
            # Étape 1 — Précondition : exercice en DRAFT
            # ----------------------------------------------------------------
            if exercise_status != ExerciseStatus.DRAFT:
                raise ExerciseAlreadyPublishedError(exercise_id, str(exercise_status))

            # ----------------------------------------------------------------
            # Étape 0 — Filtrage v3 (barrés uniquement, granularité STRUCTURE)
            # ----------------------------------------------------------------
            all_blocks = list(raw_blocks)
            active_blocks: list[RawExtractedBlock] = []
            for b in all_blocks:
                filtered = filter_structuring_block(b)
                if filtered is not None:
                    active_blocks.append(filtered)
            filtered_count = len(all_blocks) - len(active_blocks)

            logger.info(
                f"{self.AGENT_NAME}: {len(all_blocks)} blocs reçus, "
                f"{filtered_count} barrés filtrés, {len(active_blocks)} blocs actifs."
            )

            if not active_blocks:
                span.record_metrics(
                    filtered_block_count=filtered_count,
                    active_block_count=0,
                    status="INCOMPLETE",
                )
                return StructuringReport(
                    exercise_id=exercise_id,
                    status="INCOMPLETE",
                    sections_created=[],
                    questions_created=[],
                    correction_blocks_created=[],
                    unresolved_block_count=0,
                    questions_without_correction_count=0,
                    label_conflict_count=0,
                    empty_section_count=0,
                    details={
                        "reason": "Aucun bloc actif non barré fourni.",
                        "total_active_blocks": 0,
                    },
                )

            # ----------------------------------------------------------------
            # Étape 1bis — détection best-effort "document C2PCT/CHAABI"
            # (cf. _looks_like_c2pct_document) sur le texte OCR entier — passée
            # telle quelle jusqu'au 2e passage de regroupement (cf. _build_
            # questions/_partition_statement_blocks_into_questions) pour lui
            # injecter le référentiel des sous-questions comme signal
            # supplémentaire UNIQUEMENT sur ce type de document.
            # ----------------------------------------------------------------
            document_is_c2pct = self._looks_like_c2pct_document(
                "\n".join(b.prediction_ocr for b in active_blocks)
            )

            # ----------------------------------------------------------------
            # Étape 1ter — dédoublonnage déterministe des images DIAGRAM/
            # STRUCTURE répétées (cf. docstring _detect_duplicate_diagrams).
            # AVANT la classification LLM, pour que les doublons sautent
            # complètement l'appel LLM (jamais classifiés puis ignorés après
            # coup) — bug constaté en test réel : un même schéma redessiné en
            # rappel sur presque chaque page d'un document de 36 pages faisait
            # naître 6 "questions" au lieu de 2 réelles.
            #
            # B6 (backlog_bugs_c2pct.md, 2026-08-29) — même principe pour les
            # blocs TEXT identiques (énoncé imprimé réaffiché en rappel sur
            # chaque page), cf. docstring _detect_duplicate_text_blocks.
            # Fusion sûre : les deux méthodes filtrent sur des content_type
            # mutuellement exclusifs (DIAGRAM/STRUCTURE vs TEXT), donc jamais
            # de collision de clé entre les deux dicts.
            # ----------------------------------------------------------------
            duplicate_group_of = {
                **await self._detect_duplicate_diagrams(active_blocks),
                **self._detect_duplicate_text_blocks(active_blocks),
            }

            # ----------------------------------------------------------------
            # Étape 2 — Classification LLM bloc par bloc, parallélisée sous
            # sémaphore (même pattern que OCR_Extraction_Agent._process_page)
            # pour respecter la limite de concurrence fournisseur tout en
            # traitant tous les blocs en parallèle plutôt qu'en série.
            # ----------------------------------------------------------------
            semaphore = asyncio.Semaphore(settings.DOCUMENT_STRUCTURING_MAX_CONCURRENCY)

            async def _classify_with_limit(idx: int, block: RawExtractedBlock) -> ClassifiedBlock:
                async with semaphore:
                    return await self._classify_block(block, idx, context)

            # Seuls les blocs "primaires" (uniques, ou premier représentant
            # d'un groupe de doublons) passent par le LLM.
            indices_needing_llm = [
                idx for idx in range(len(active_blocks))
                if duplicate_group_of.get(idx, idx) == idx
            ]
            llm_results = await asyncio.gather(*[
                _classify_with_limit(idx, active_blocks[idx]) for idx in indices_needing_llm
            ])
            classified_by_index: dict[int, ClassifiedBlock] = dict(zip(indices_needing_llm, llm_results))

            for idx in range(len(active_blocks)):
                if idx in classified_by_index:
                    if idx in duplicate_group_of:  # primaire d'un groupe réel (>=2 membres)
                        classified_by_index[idx] = replace(classified_by_index[idx], dedup_group_id=idx)
                    continue
                primary_idx = duplicate_group_of[idx]
                primary_result = classified_by_index[primary_idx]
                # B6 — libellé neutre (contrairement à l'ancien "Image
                # identique" en dur, désormais faux pour un doublon TEXT,
                # cf. _detect_duplicate_text_blocks) : le content_type du
                # bloc lui-même distingue déjà les deux cas si besoin.
                duplicate_kind = "image" if active_blocks[idx].content_type in self._DEDUP_CONTENT_TYPES else "texte"
                classified_by_index[idx] = replace(
                    primary_result,
                    raw_block=active_blocks[idx],
                    block_index=idx,
                    dedup_group_id=primary_idx,
                    justification=(
                        f"Contenu {duplicate_kind} identique au bloc primaire #{primary_idx} — "
                        f"dédoublonnage déterministe, aucun appel LLM. Verdict du primaire : "
                        f"{primary_result.justification}"
                    ),
                    model_used=None,
                    fallback_occurred=False,
                    tokens_used=0,
                )

            classified_blocks: list[ClassifiedBlock] = [
                classified_by_index[idx] for idx in range(len(active_blocks))
            ]

            # Trace de chaque décision de classification, TOUTES catégories
            # confondues (STATEMENT/CORRECTION/AUTRE) — alimente AgentDecisionLog
            # côté service (une ligne par bloc classifié, §16).
            block_classifications_data = [
                {
                    "block_index": c.block_index,
                    "classification": c.classification,
                    "content_type": c.raw_block.content_type,
                    "image_crop_path": c.raw_block.image_crop_path,
                    "model_used": c.model_used,
                    "fallback_occurred": c.fallback_occurred,
                    "tokens_used": c.tokens_used,
                    "confidence": c.confidence,
                    "justification": c.justification,
                }
                for c in classified_blocks
            ]

            # Filtrage des blocs AUTRE (écarter sans bloquer)
            structuring_blocks = [b for b in classified_blocks if b.classification != "AUTRE"]

            # ----------------------------------------------------------------
            # Étape 3 — Détection des ExerciseSection (étape 3bis)
            # ----------------------------------------------------------------
            sections, statement_blocks = self._extract_sections(structuring_blocks)

            # ----------------------------------------------------------------
            # Étape 4 — Regroupement & création des Question
            # ----------------------------------------------------------------
            questions, label_conflicts, unlabelled_count, label_conflicts_detail, question_grouping_decisions = (
                await self._build_questions(sections, statement_blocks, context, document_is_c2pct)
            )

            # ----------------------------------------------------------------
            # Étape 5 — Rattachement des blocs CORRECTION
            # ----------------------------------------------------------------
            correction_blocks = [b for b in structuring_blocks if b.classification == "CORRECTION"]
            attached_corrections, unresolved_count, correction_conflicts, correction_conflicts_detail = (
                await self._attach_corrections(correction_blocks, questions, sections, context)
            )

            # ----------------------------------------------------------------
            # Étape 6 — Contrôle qualité & vérification de complétude stricte
            # ----------------------------------------------------------------
            # 1. Sections vides (aucune question sous la section) — localisées
            # par order/title, pas seulement comptées.
            empty_sections_list = [
                sec for sec in sections if not any(q.section_order == sec.order for q in questions)
            ]
            empty_section_count = len(empty_sections_list)
            empty_sections_detail = [
                {"order": sec.order, "title": sec.title} for sec in empty_sections_list
            ]

            # 2. Questions sans correction rattachée
            questions_without_corr = sum(
                1 for q in questions if not q.correction_blocks
            )

            # unlabelled_count n'est PAS un critère de complétude : depuis
            # _build_questions (cf. sa docstring), un bloc STATEMENT sans
            # question_label forme désormais systématiquement une Question
            # (regroupé par similarité de contenu) — il ne reste plus jamais
            # "perdu" comme avant, donc plus rien à signaler ici. Le compteur
            # est conservé dans le rapport à titre informatif uniquement (le
            # professeur peut vérifier que le regroupement automatique est
            # correct), jamais comme condition bloquante.
            is_complete = (
                unresolved_count == 0
                and questions_without_corr == 0
                and label_conflicts == 0
                and empty_section_count == 0
                and len(questions) > 0
                and correction_conflicts == 0
            )

            status_str = "COMPLETE" if is_complete else "INCOMPLETE"

            # Formater les sorties
            sections_created_data = [
                {"order": sec.order, "title": sec.title} for sec in sections
            ]
            questions_created_data = [
                {
                    "order": q.order,
                    "question_label": q.question_label,
                    "statement": q.statement,
                    "section_order": q.section_order,
                    "correction_count": len(q.correction_blocks),
                }
                for q in questions
            ]
            correction_blocks_data = [
                {
                    "block_index": c.raw_block.image_crop_path,  # ref crop
                    "content_type": c.raw_block.content_type,
                    # Tracé explicitement par _attach_corrections pour chaque bloc
                    # (chemin réel de rattachement, jamais réinféré depuis assigned_
                    # question_order seul — LABEL_EXPLICITE ne veut PAS dire la même
                    # chose que INFERRED_SINGLE_QUESTION ou CONTENT_MATCHED, cf.
                    # BlockEvidenceLevel).
                    "evidence_level": c.evidence_level or BlockEvidenceLevel.UNRESOLVED_NO_LABEL,
                    "question_order": c.assigned_question_order,
                    "section_order": c.assigned_question_section_order,
                    "justification": c.justification,
                    "image_crop_path": c.raw_block.image_crop_path,
                    "raw_text": c.raw_block.prediction_ocr,
                    "structured_content": c.raw_block.structured_output,
                    # Position réelle dans le document (B5, backlog_bugs_
                    # c2pct.md) — déjà porté par RawExtractedBlock, jamais
                    # transmis jusqu'ici avant ce fix.
                    "page_number": c.raw_block.page_number,
                    "block_order_index": c.raw_block.block_order_index,
                    # B11 (backlog_bugs_c2pct.md) — déjà porté par
                    # RawExtractedBlock (confiance combinée, après relecture
                    # ciblée éventuelle), jamais transmis jusqu'ici : un bloc
                    # mal lu restait indiscernable d'un bloc fiable côté prof.
                    "ocr_confidence": c.raw_block.confidence_score,
                }
                for c in attached_corrections
            ]

            duration_ms = round((time.perf_counter() - t_start) * 1000, 2)
            span.record_metrics(
                filtered_block_count=filtered_count,
                active_block_count=len(active_blocks),
                sections_count=len(sections),
                questions_count=len(questions),
                unresolved_block_count=unresolved_count,
                questions_without_corr=questions_without_corr,
                label_conflicts=label_conflicts,
                empty_sections=empty_section_count,
                unlabelled_statement_blocks=unlabelled_count,
                correction_label_conflicts=correction_conflicts,
                status=status_str,
                duration_ms=duration_ms,
            )

            return StructuringReport(
                exercise_id=exercise_id,
                status=status_str,
                sections_created=sections_created_data,
                questions_created=questions_created_data,
                correction_blocks_created=correction_blocks_data,
                unresolved_block_count=unresolved_count,
                questions_without_correction_count=questions_without_corr,
                label_conflict_count=label_conflicts,
                empty_section_count=empty_section_count,
                unlabelled_statement_block_count=unlabelled_count,
                correction_label_conflict_count=correction_conflicts,
                details={
                    "total_active_blocks": len(active_blocks),
                    "other_blocks_ignored": len(classified_blocks) - len(structuring_blocks),
                },
                block_classifications=block_classifications_data,
                empty_sections_detail=empty_sections_detail,
                label_conflicts_detail=label_conflicts_detail,
                correction_label_conflicts_detail=correction_conflicts_detail,
                question_grouping_decisions=question_grouping_decisions,
            )

    # ---------------------------------------------------------------------------
    # Méthodes d'implémentation privées
    # ---------------------------------------------------------------------------

    @staticmethod
    def _compute_image_hash(image_bytes: bytes) -> int:
        """
        Hash perceptuel simple (average-hash 8x8, PIL seul — aucune
        dépendance supplémentaire) : détecte des images QUASI identiques
        (même diagramme rescanné/redessiné sur plusieurs pages), jamais un
        hash cryptographique (qui ne détecterait que des octets strictement
        identiques — inutile ici, chaque scan a un bruit/compression différent).
        """
        with Image.open(io.BytesIO(image_bytes)) as img:
            pixels = list(img.convert("L").resize((8, 8), Image.LANCZOS).getdata())
        average = sum(pixels) / len(pixels)
        bits = 0
        for pixel in pixels:
            bits = (bits << 1) | (1 if pixel >= average else 0)
        return bits

    @staticmethod
    def _hamming_distance(a: int, b: int) -> int:
        return bin(a ^ b).count("1")

    async def _detect_duplicate_diagrams(
        self, active_blocks: list[RawExtractedBlock]
    ) -> dict[int, int]:
        """
        Détection déterministe (sans LLM) des blocs DIAGRAM/STRUCTURE
        représentant la MÊME image, réapparue sur plusieurs pages — ex. le
        schéma de l'énoncé redessiné en rappel sur chaque page d'une
        méthodologie de résolution guidée (constaté en test réel : sans
        cette étape, chaque réoccurrence — décrite différemment à chaque
        relecture OCR — pouvait être classifiée comme son propre énoncé
        indépendant, fragmentant 2 problèmes réels en 6 "questions").

        Best-effort : un échec de téléchargement/hash sur un bloc particulier
        ne bloque jamais la structuration, ce bloc est simplement traité
        comme unique (même discipline que le reste de l'agent — cf. Cas 0
        barème C2PCT natif, toujours best-effort et jamais bloquant).

        Retourne {index_bloc: index_bloc_primaire} pour CHAQUE membre d'un
        groupe de doublons RÉELLEMENT détecté (primaire inclus, mappé sur
        lui-même) — absent du dict si le bloc est unique ou hors
        _DEDUP_CONTENT_TYPES, jamais une entrée degré-1 ambiguë.
        """
        hashes: dict[int, int] = {}
        for idx, block in enumerate(active_blocks):
            if block.content_type not in self._DEDUP_CONTENT_TYPES:
                continue
            try:
                image_bytes = await storage_service.download(
                    StorageContainer.EXERCISES, block.image_crop_path
                )
                hashes[idx] = self._compute_image_hash(image_bytes)
            except Exception as e:
                logger.warning(
                    f"{self.AGENT_NAME}: échec hash image bloc #{idx} "
                    f"({block.image_crop_path}) — traité comme unique : {e}"
                )

        group_of: dict[int, int] = {}
        primary_hashes: list[tuple[int, int]] = []  # (primary_index, hash)
        for idx in sorted(hashes):
            h = hashes[idx]
            match = next(
                (
                    primary_idx for primary_idx, primary_hash in primary_hashes
                    if self._hamming_distance(h, primary_hash) <= self._DUPLICATE_IMAGE_HAMMING_THRESHOLD
                ),
                None,
            )
            if match is None:
                primary_hashes.append((idx, h))
            else:
                group_of[idx] = match
                group_of.setdefault(match, match)

        if group_of:
            n_groups = len({v for v in group_of.values()})
            logger.info(
                f"{self.AGENT_NAME}: {len(group_of) - n_groups} bloc(s) image "
                f"identifié(s) comme doublon(s) d'un diagramme déjà vu "
                f"({n_groups} groupe(s))."
            )
        return group_of

    @classmethod
    def _normalize_text_for_dedup(cls, text: str) -> str:
        """Minuscules + espaces/retours à la ligne réduits à un seul espace, trim — jamais plus (aucune tolérance de contenu, cf. docstring _detect_duplicate_text_blocks)."""
        return re.sub(r"\s+", " ", text).strip().lower()

    def _detect_duplicate_text_blocks(self, active_blocks: list[RawExtractedBlock]) -> dict[int, int]:
        """
        B6 (backlog_bugs_c2pct.md, 2026-08-29) — détection déterministe
        (sans LLM, sans appel réseau contrairement à _detect_duplicate_
        diagrams qui télécharge chaque image) des blocs TEXT identiques
        réapparus sur plusieurs pages — ex. l'énoncé du problème réimprimé
        en rappel en haut de chaque page d'une méthodologie de résolution
        guidée. Constaté en test réel : sans ceci, CHAQUE réoccurrence
        déclenchait sa propre relecture LLM (`indices_needing_llm` ne
        contient que les indices absents de `duplicate_group_of`), un coût
        de classification doublé sur un document de 36 pages, et le même
        texte répété survivait jusque dans le contenu final persisté
        (`Question.statement`).

        Scope volontairement restreint (jamais un dédoublonnage agressif) :
        - UNIQUEMENT content_type == TEXT (jamais EQUATION : une formule
          répétée peut légitimement réapparaître dans un raisonnement, un
          énoncé ne se répète que par artefact de mise en page imprimée).
        - UNIQUEMENT origin == PRINTED — jamais HANDWRITTEN, une réponse
          manuscrite ne doit JAMAIS être fusionnée avec une autre même si
          le texte transcrit coïncide (risque de perte de contenu réel,
          bien pire qu'un appel LLM économisé).
        - UNIQUEMENT au-delà de _TEXT_DEDUP_MIN_LENGTH caractères (texte
          normalisé) — jamais un fragment court où une coïncidence
          textuelle est plausible sans être un vrai doublon.
        - Comparaison EXACTE sur texte normalisé (cf. _normalize_text_for_
          dedup), jamais une distance floue (cf. docstring de la constante
          _TEXT_DEDUP_MIN_LENGTH pour le raisonnement complet).
        - JAMAIS un bloc qui ressemble à un tableau de barème (cf.
          _looks_like_bareme_table) — un barème C2PCT réutilisant le même
          gabarit de points d'un exercice à l'autre redevient, une fois
          normalisé, byte-pour-byte identique à un autre exercice ; sans
          cette exclusion, ce mécanisme absorbait un vrai barème comme
          "doublon d'énoncé" et le faisait disparaître en silence (bug réel
          constaté, examen C2PCT à 3 exercices, 2026-09-04).

        Même contrat de retour que _detect_duplicate_diagrams : {index_bloc:
        index_bloc_primaire} pour CHAQUE membre d'un groupe RÉELLEMENT
        détecté (primaire inclus, mappé sur lui-même), absent du dict sinon.
        """
        primary_by_hash: dict[str, int] = {}
        group_of: dict[int, int] = {}
        for idx, block in enumerate(active_blocks):
            if block.content_type != ExtractionContentType.TEXT:
                continue
            if block.origin != ExtractionOrigin.PRINTED:
                continue
            normalized = self._normalize_text_for_dedup(block.prediction_ocr or "")
            if len(normalized) < self._TEXT_DEDUP_MIN_LENGTH:
                continue
            if self._looks_like_bareme_table(normalized):
                continue
            text_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            primary_idx = primary_by_hash.get(text_hash)
            if primary_idx is None:
                primary_by_hash[text_hash] = idx
            else:
                group_of[idx] = primary_idx
                group_of.setdefault(primary_idx, primary_idx)

        if group_of:
            n_groups = len({v for v in group_of.values()})
            logger.info(
                f"{self.AGENT_NAME}: {len(group_of) - n_groups} bloc(s) texte "
                f"identifié(s) comme doublon(s) d'un énoncé déjà vu "
                f"({n_groups} groupe(s))."
            )
        return group_of

    async def _classify_block(
        self,
        block: RawExtractedBlock,
        block_idx: int,
        context: AgentExecutionContext,
    ) -> ClassifiedBlock:
        """Appelle le LLM pour classifier un bloc brut."""
        # Construire la section structured_content si le bloc en possède un
        structured_content_section = ""
        if block.structured_output is not None:
            structured_repr = json.dumps(block.structured_output, ensure_ascii=False)
            if len(structured_repr) > STRUCTURED_CONTENT_MAX_CHARS:
                structured_repr = structured_repr[:STRUCTURED_CONTENT_MAX_CHARS] + "..."
            structured_content_section = STRUCTURED_CONTENT_SECTION_TEMPLATE.format(
                structured_content_repr=structured_repr
            )

        user_msg = DOCUMENT_STRUCTURING_USER_TEMPLATE.format(
            content_type=block.content_type,
            raw_text=block.prediction_ocr[:600],
            structured_content_section=structured_content_section,
        )
        messages = [
            {"role": "system", "content": DOCUMENT_STRUCTURING_SYSTEM_PROMPT + _SUPPORTING_CONTENT_ADDENDUM},
            {"role": "user", "content": user_msg},
        ]

        # 1 retry métier autorisé
        for attempt in range(2):
            try:
                result, spec, fallback, token_usage = await invoke_llm_with_fallback(
                    task_type=TaskType.DOCUMENT_STRUCTURING,
                    messages=messages,
                    response_schema=BlockClassificationResult,
                    context=context,
                )

                return ClassifiedBlock(
                    raw_block=block,
                    block_index=block_idx,
                    classification=result.classification,
                    section_label=result.section_label.strip() if result.section_label else None,
                    question_label=result.question_label.strip() if result.question_label else None,
                    confidence=result.confidence,
                    justification=result.justification,
                    is_supporting_content=result.is_supporting_content,
                    model_used=f"{spec.provider}:{spec.model_name}",
                    fallback_occurred=fallback,
                    tokens_used=token_usage.get("total_tokens", 0),
                )
            except Exception as e:
                logger.warning(f"Erreur classification LLM bloc #{block_idx} (essai {attempt}): {e}")
                if attempt == 0:
                    continue
                # Repli de sécurité si LLM crash
                return ClassifiedBlock(
                    raw_block=block,
                    block_index=block_idx,
                    classification="AUTRE",
                    section_label=None,
                    question_label=None,
                    confidence=0.0,
                    justification=f"Échec classification LLM : {e}",
                )

        return ClassifiedBlock(
            raw_block=block,
            block_index=block_idx,
            classification="AUTRE",
            section_label=None,
            question_label=None,
            confidence=0.0,
            justification="Échec classification LLM après retry.",
        )

    def _extract_sections(
        self,
        blocks: list[ClassifiedBlock],
    ) -> tuple[list[SectionSpec], list[ClassifiedBlock]]:
        """
        Extrait les marqueurs d'ExerciseSection parmi les blocs STATEMENT.

        Un section_label détecté sur UN SEUL bloc n'est PAS promu en Section
        réelle — corroboration exigée (≥2 blocs distincts partageant le même
        section_label, fuzzy-matché) avant de créer une SectionSpec. Motif :
        un bloc isolément mal classifié (ex. un sous-titre de correction comme
        "Comprobación a tracción" étiqueté à tort STATEMENT + section_label
        par _classify_block, qui juge chaque bloc sans contexte des autres)
        suffisait sinon à créer une section fantôme, cassant le rattachement
        de la vraie section pour tous les autres blocs du document (constaté
        en test réel). Un vrai marqueur de section globale ("Exercice 2",
        "PROBLEMA 1") est normalement répété/confirmé par plusieurs blocs —
        un signal unique et isolé est plus probablement une erreur de
        classification qu'une section réelle sans autre occurrence.

        Retourne (liste des sections, liste des blocs STATEMENT non-section) —
        un bloc dont le section_label n'a pas été corroboré reste dans
        statement_blocks mais n'appartient à AUCUNE SectionSpec (traité comme
        non-sectionné en aval, jamais rattaché en silence à une section fantôme).
        """
        statement_blocks = [b for b in blocks if b.classification == "STATEMENT"]

        # 1er passage : regrouper par section_label (fuzzy), sans encore créer de SectionSpec.
        candidate_groups: list[tuple[str, list[ClassifiedBlock]]] = []
        for block in statement_blocks:
            if not block.section_label:
                continue
            existing = next(
                (g for g in candidate_groups if fuzz.ratio(g[0].lower(), block.section_label.lower()) > 90),
                None,
            )
            if existing:
                existing[1].append(block)
            else:
                candidate_groups.append((block.section_label, [block]))

        # 2e passage : ne promouvoir en SectionSpec que les groupes corroborés (≥2 blocs).
        sections: list[SectionSpec] = []
        curr_section_order = 0
        for label, group_blocks in candidate_groups:
            if len(group_blocks) < 2:
                logger.info(
                    f"{self.AGENT_NAME}: section_label '{label}' ignoré (un seul bloc, non "
                    "corroboré) — probable erreur de classification isolée, pas une section réelle."
                )
                continue
            curr_section_order += 1
            title = group_blocks[0].raw_block.prediction_ocr.split("\n")[0][:100]
            sec = SectionSpec(
                order=curr_section_order,
                title=title if title else f"Section {curr_section_order}",
                section_label=label,
            )
            sec.blocks.extend(group_blocks)
            sections.append(sec)

        return sections, statement_blocks

    _UNLABELLED_QUESTION_LABEL_PREFIX = "Sans label"

    def _resolve_section_key_for_block(
        self,
        block: ClassifiedBlock,
        sections: list[SectionSpec],
    ) -> int | None:
        """
        Clé de regroupement de section pour _build_questions — résolue contre
        les SectionSpec déjà détectés (fuzzy match), JAMAIS la chaîne
        section_label brute du bloc telle quelle. Motif : cette chaîne est
        détectée bloc par bloc (cf. _classify_block, isolément) et peut varier
        légèrement d'un bloc à l'autre pour la MÊME section réelle (ex. un
        bloc porte "PROBLEMA 1: ESTRATEGIA CHAABI", un autre bloc du même
        problème n'a aucun section_label du tout) — grouper par chaîne brute
        aurait alors envoyé ces blocs vers des appels de regroupement
        holistique SÉPARÉS, qui ne peuvent par construction jamais les
        fusionner puisqu'ils ne se voient jamais (constaté en test réel :
        "PROBLEMA 1" et l'énoncé réel du problème restaient deux Questions
        distinctes malgré le 2e passage holistique).

        Document à une seule section détectée (cas courant) : tous les blocs
        y vont, quelle que soit l'incohérence de leur section_label brut —
        rien d'autre à distinguer. Plusieurs sections détectées : fuzzy match
        du section_label du bloc contre chaque SectionSpec ; None (bucket à
        part, jamais mélangé arbitrairement à une section existante) si aucun
        match, cas encore ambigu non résolu par cette seule méthode.
        """
        if not sections:
            return None
        if len(sections) == 1:
            return sections[0].order
        if block.section_label:
            for s in sections:
                if fuzz.ratio(s.section_label.lower(), block.section_label.lower()) > 90:
                    return s.order
        return None

    async def _partition_statement_blocks_into_questions(
        self,
        blocks: list[ClassifiedBlock],
        context: AgentExecutionContext,
        document_is_c2pct: bool = False,
    ) -> tuple[list[QuestionGroupResult], dict | None]:
        """
        Regroupe TOUS les blocs STATEMENT d'une même section en questions
        réelles via UN SEUL appel LLM voyant tous les blocs à la fois — cf.
        QUESTION_GROUPING_SYSTEM_PROMPT pour le raisonnement demandé et la
        justification de cette approche (classifier bloc par bloc, sans
        contexte des autres, ne peut pas répondre correctement à "ces blocs
        forment-ils la même question" : constaté en test réel, un clustering
        par similarité de texte fragmentait à tort 19 puis 12 "questions"
        pour 1 seul problème réel dans un document utilisant une méthodologie
        de résolution guidée).

        Repli : si le LLM échoue, omet des index ou en invente, chaque bloc
        jamais retourné forme son propre groupe (jamais perdu en silence) —
        et un échec total de l'appel retombe sur un groupe par bloc, jamais
        un plantage qui bloquerait toute la structuration du document.

        Dédoublonnage d'images (cf. Document_Structuring_Agent._detect_
        duplicate_diagrams) : un seul REPRÉSENTANT par dedup_group_id est
        soumis à ce passage LLM — les autres membres du groupe (même image
        réapparue sur d'autres pages) sont ré-insérés dans le même groupe
        juste après, DÉTERMINISTIQUEMENT, jamais via un jugement LLM (qui
        n'a de toute façon accès qu'à un texte OCR différent à chaque
        occurrence — bug constaté en test réel : 6 "questions" au lieu de 2
        sur un document où le même schéma était redessiné à chaque page).

        document_is_c2pct (cf. Document_Structuring_Agent._looks_like_c2pct_
        document, calculé une fois dans execute() sur le document entier) :
        si True, injecte _C2PCT_GROUPING_ADDENDUM dans le prompt système —
        le référentiel des 15 sous-questions officielles ET la règle de
        numérotation continue/redémarrage, un signal bien plus fiable que le
        seul jugement sémantique pour ce type précis de document. QUESTION_
        GROUPING_SYSTEM_PROMPT lui-même reste volontairement neutre (aucune
        méthodologie nommée en dur) pour continuer à fonctionner sur
        n'importe quel autre document — cet addendum est un complément
        conditionnel, jamais une modification du prompt de base.

        Retourne (groups, decision_log) — decision_log est None quand aucun
        appel LLM n'a eu lieu (0 ou 1 bloc représentant, rien à arbitrer),
        sinon un dict tracé tel quel dans AgentDecisionLog (cf. execute() et
        document_structuring_service.py) : labels vus par le LLM AVANT son
        verdict, nombre de groupes qu'il a RÉELLEMENT proposés, et nombre de
        groupes final après le filet de sécurité (déterministe, ne peut
        qu'AUGMENTER ce compte, jamais le réduire) — la seule façon de savoir
        après coup si une fusion excessive vient du jugement du LLM lui-même
        ou d'ailleurs, ce regroupement n'étant pas encore journalisé bloc par
        bloc comme _classify_block (constaté : impossible de diagnostiquer
        un cas réel de fusion à tort de deux problèmes distincts sans ça).
        """
        if len(blocks) <= 1:
            return [QuestionGroupResult(question_label=blocks[0].question_label if blocks else None,
                                         block_indices=[0] if blocks else [])], None

        representative_indices: list[int] = []
        seen_group_ids: set[int] = set()
        for i, b in enumerate(blocks):
            gid = b.dedup_group_id
            if gid is None or gid not in seen_group_ids:
                representative_indices.append(i)
                if gid is not None:
                    seen_group_ids.add(gid)

        decision_log: dict | None = None

        if len(representative_indices) <= 1:
            groups = [
                QuestionGroupResult(
                    question_label=blocks[representative_indices[0]].question_label if representative_indices else None,
                    block_indices=list(representative_indices),
                )
            ]
        else:
            rep_blocks = [blocks[i] for i in representative_indices]
            blocks_listing = "\n".join(
                f"[{pos}] (label tentatif: {b.question_label or 'aucun'}, "
                f"contenu de support: {b.is_supporting_content}) "
                f"{b.raw_block.prediction_ocr[:300]}"
                for pos, b in enumerate(rep_blocks)
            )
            user_msg = QUESTION_GROUPING_USER_TEMPLATE.format(count=len(rep_blocks), blocks_listing=blocks_listing)
            system_prompt = QUESTION_GROUPING_SYSTEM_PROMPT + (
                _C2PCT_GROUPING_ADDENDUM if document_is_c2pct else ""
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ]

            # 1 retry métier autorisé — même discipline que _classify_block
            # (ligne ~750) : cet appel décide de TOUTE la structure du
            # document (pas d'un seul bloc), un enjeu bien plus grand qui ne
            # justifie pas MOINS de résilience. Chaque tentative relance la
            # chaîne de fournisseurs complète (Gemini puis Gemini_2, cf.
            # registry.py) depuis le début — jamais un "essai" partagé entre
            # les deux, invoke_llm_with_fallback n'a pas d'état résiduel.
            result = None
            spec = None
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    result, spec, _, _ = await invoke_llm_with_fallback(
                        task_type=TaskType.DOCUMENT_STRUCTURING,
                        messages=messages,
                        response_schema=QuestionGroupingResult,
                        context=context,
                    )
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        f"{self.AGENT_NAME}: échec du regroupement LLM des questions "
                        f"(essai {attempt}) : {e}"
                    )
            if last_error is not None:
                logger.warning(
                    f"{self.AGENT_NAME}: regroupement LLM définitivement échoué après retry "
                    f"— repli un groupe par bloc : {last_error}"
                )

            seen_positions: set[int] = set()
            groups = []
            if result is not None:
                for group in result.groups:
                    valid_positions = [
                        pos for pos in group.block_indices
                        if 0 <= pos < len(rep_blocks) and pos not in seen_positions
                    ]
                    if not valid_positions:
                        continue
                    seen_positions.update(valid_positions)
                    groups.append(QuestionGroupResult(
                        question_label=group.question_label,
                        block_indices=[representative_indices[pos] for pos in valid_positions],
                    ))

            # Aucun représentant oublié en silence (échec LLM total, ou
            # positions manquantes dans la réponse) — forme son propre groupe.
            for pos, local_idx in enumerate(representative_indices):
                if pos not in seen_positions:
                    groups.append(QuestionGroupResult(
                        question_label=blocks[local_idx].question_label,
                        block_indices=[local_idx],
                    ))

            decision_log = {
                "document_is_c2pct": document_is_c2pct,
                "representative_labels": [b.question_label for b in rep_blocks],
                "llm_call_succeeded": result is not None,
                "llm_proposed_group_labels": (
                    [g.question_label for g in result.groups] if result is not None else None
                ),
                "model_used": spec.model_name if spec else None,
                # None si succès (dès le 1er essai ou après retry) — sinon le
                # message de la DERNIÈRE tentative (cf. boucle ci-dessus),
                # pour savoir a posteriori POURQUOI le filet de sécurité
                # (1 groupe par bloc) s'est déclenché, sans devoir rouvrir
                # les logs bruts du worker Celery.
                "llm_error": str(last_error) if last_error is not None else None,
            }

        return self._expand_and_finalize_groups(groups, blocks, decision_log)

    @staticmethod
    def _expand_and_finalize_groups(
        groups: list[QuestionGroupResult],
        blocks: list[ClassifiedBlock],
        decision_log: dict | None,
    ) -> tuple[list[QuestionGroupResult], dict | None]:
        """
        Étape finale commune à tous les chemins de regroupement (LLM ou
        déterministe, cf. leurs docstrings respectifs) : ré-expansion des
        doublons d'image + filet de sécurité "aucun bloc oublié", jamais
        dupliquée entre les deux chemins.
        """
        # Ré-expansion déterministe des doublons : chaque bloc partageant le
        # dedup_group_id d'un membre déjà présent dans un groupe rejoint ce
        # même groupe — jamais un second jugement LLM sur ce point.
        expanded_groups: list[QuestionGroupResult] = []
        covered: set[int] = set()
        for group in groups:
            expanded = list(group.block_indices)
            for local_idx in list(group.block_indices):
                gid = blocks[local_idx].dedup_group_id
                if gid is None:
                    continue
                for j, b in enumerate(blocks):
                    if b.dedup_group_id == gid and j not in expanded:
                        expanded.append(j)
            covered.update(expanded)
            expanded_groups.append(QuestionGroupResult(question_label=group.question_label, block_indices=expanded))

        # Filet de sécurité final sur TOUS les blocs de la section (pas
        # seulement les représentants envoyés au LLM) — même esprit que le
        # filet d'origine, jamais un bloc perdu en silence.
        for i in range(len(blocks)):
            if i not in covered:
                expanded_groups.append(QuestionGroupResult(question_label=blocks[i].question_label, block_indices=[i]))
                covered.add(i)

        if decision_log is not None:
            decision_log["final_group_count"] = len(expanded_groups)

        return expanded_groups, decision_log

    async def _build_questions(
        self,
        sections: list[SectionSpec],
        statement_blocks: list[ClassifiedBlock],
        context: AgentExecutionContext,
        document_is_c2pct: bool = False,
    ) -> tuple[list[QuestionSpec], int, int, list[dict], list[dict]]:
        """
        Regroupe les blocs STATEMENT en Question réelles — le label ou
        l'absence de label détecté bloc par bloc (cf. _classify_block) n'est
        qu'un INDICE transmis au 2e passage holistique (cf.
        _partition_statement_blocks_into_questions), jamais une vérité
        imposée : un même contenu peut recevoir un label incohérent d'un
        bloc à l'autre (constaté en test réel), donc c'est le 2e passage,
        voyant TOUS les blocs d'une section à la fois, qui tranche.

        Une question réellement présente dans le document mais dépourvue de
        numérotation explicite devient quand même une Question — jamais
        ignorée. Le regroupement se fait par section (section_label brut du
        bloc, indépendamment du SectionSpec déjà détecté) : deux sections
        différentes ne mélangent jamais leurs questions (Correctif 4).

        L'ordre Question.order est un index continu global (1, 2, 3...).

        Retourne (questions, label_conflicts, unlabelled_statement_block_count,
        label_conflicts_detail, question_grouping_decisions) — le 4e élément
        localise précisément chaque conflit détecté (deux groupes distincts
        de la même section partageant le même label), pas seulement le
        compteur agrégé. unlabelled_statement_block_count reste un compteur
        INFORMATIF (combien de blocs sont dans un groupe sans label après le
        2e passage, à vérifier par le professeur) — il ne bloque plus le
        statut COMPLETE depuis que ces blocs forment systématiquement une
        Question (cf. execute(), le gate de complétude ne teste plus ce
        compteur). question_grouping_decisions (5e élément) — une entrée par
        appel LLM de _partition_statement_blocks_into_questions (un par
        section, absente si 0/1 bloc représentant) — alimente AgentDecisionLog
        (cf. document_structuring_service.py) pour rendre visible a posteriori
        ce que le LLM a réellement vu/proposé, seule façon de diagnostiquer
        une fusion à tort de plusieurs problèmes distincts en une Question.
        """
        questions: list[QuestionSpec] = []
        question_grouping_decisions: list[dict] = []
        label_conflicts = 0
        label_conflicts_detail: list[dict] = []
        unlabelled_statement_block_count = 0
        global_question_order = 0

        blocks_by_section: dict[int | None, list[ClassifiedBlock]] = {}
        for block in statement_blocks:
            blocks_by_section.setdefault(self._resolve_section_key_for_block(block, sections), []).append(block)

        for sec_key, blocks in blocks_by_section.items():
            groups, grouping_decision = await self._partition_statement_blocks_into_questions(
                blocks, context, document_is_c2pct
            )
            if grouping_decision is not None:
                grouping_decision["section_order"] = sec_key
                question_grouping_decisions.append(grouping_decision)

            # Conflit : deux groupes DISTINCTS de la même section partagent le même
            # label non-null — signe d'ambiguïté (le LLM aurait dû soit les fusionner
            # s'ils étaient réellement la même question, soit donner des labels
            # différents s'ils étaient réellement distincts).
            labels_seen: dict[str, int] = {}

            for group in groups:
                group_blocks = [blocks[i] for i in group.block_indices]
                if not group_blocks:
                    continue

                global_question_order += 1
                lbl = group.question_label
                if lbl:
                    if lbl in labels_seen:
                        label_conflicts += 1
                        label_conflicts_detail.append({
                            "question_label": lbl,
                            "section_order": sec_key,
                            "blocks": [
                                {"block_index": b.block_index, "image_crop_path": b.raw_block.image_crop_path}
                                for b in group_blocks
                            ],
                        })
                    labels_seen[lbl] = labels_seen.get(lbl, 0) + 1
                else:
                    unlabelled_statement_block_count += len(group_blocks)

                # Dédoublonnage d'images (cf. _detect_duplicate_diagrams) : les
                # blocs dupliqués restent dans group_blocks (crops/rattachement
                # aval), mais leur texte OCR — décrivant la MÊME image avec des
                # mots différents à chaque relecture — ne doit apparaître
                # qu'UNE fois dans l'énoncé, jamais une fois par occurrence
                # (constaté en test réel : un même diagramme répété ~20 fois
                # produisait un énoncé illisible, concaténant 20 descriptions
                # quasi identiques du même schéma).
                statement_source_blocks = [
                    b for b in group_blocks
                    if b.dedup_group_id is None or b.dedup_group_id == b.block_index
                ] or group_blocks
                full_statement = "\n\n".join(b.raw_block.prediction_ocr for b in statement_source_blocks)
                q_spec = QuestionSpec(
                    order=global_question_order,
                    question_label=lbl or f"{self._UNLABELLED_QUESTION_LABEL_PREFIX} {global_question_order}",
                    statement=full_statement,
                    section_order=sec_key,
                    statement_blocks=group_blocks,
                )
                questions.append(q_spec)

        return questions, label_conflicts, unlabelled_statement_block_count, label_conflicts_detail, question_grouping_decisions

    def _find_section_for_block(
        self,
        block: ClassifiedBlock,
        sections: list[SectionSpec],
    ) -> SectionSpec | None:
        """Retrouve la section correspondant au section_label d'un bloc, si présent."""
        if not block.section_label:
            return None
        norm = block.section_label.lower()
        for s in sections:
            if fuzz.ratio(s.section_label.lower(), norm) > 90 or s.section_label.lower() == norm:
                return s
        return None

    async def _attach_unresolved_corrections_via_llm(
        self,
        blocks: list[ClassifiedBlock],
        candidate_questions: list[QuestionSpec],
        context: AgentExecutionContext,
    ) -> None:
        """
        Rattache par CONTENU (pas par label) des blocs de correction restés
        sans label exploitable, quand PLUSIEURS questions candidates existent
        dans la même section (le cas à une seule candidate est réglé sans
        appel LLM par l'appelant — aucune ambiguïté possible). Mute les
        QuestionSpec.correction_blocks et les blocs en place ; les blocs non
        rattachés (question_index=null, index omis ou invalide) restent
        NON rattachés — jamais un choix arbitraire.
        """
        questions_listing = "\n".join(
            f"[{i}] {q.statement[:300]}" for i, q in enumerate(candidate_questions)
        )
        blocks_listing = "\n".join(
            f"[{i}] {b.raw_block.prediction_ocr[:300]}" for i, b in enumerate(blocks)
        )
        user_msg = CORRECTION_ATTACHMENT_USER_TEMPLATE.format(
            q_count=len(candidate_questions), questions_listing=questions_listing,
            b_count=len(blocks), blocks_listing=blocks_listing,
        )
        messages = [
            {"role": "system", "content": CORRECTION_ATTACHMENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            result, _, _, _ = await invoke_llm_with_fallback(
                task_type=TaskType.DOCUMENT_STRUCTURING,
                messages=messages,
                response_schema=CorrectionAttachmentBatchResult,
                context=context,
            )
        except Exception as e:
            logger.warning(f"{self.AGENT_NAME}: échec du rattachement LLM des corrections — laissées non rattachées : {e}")
            return

        for attachment in result.attachments:
            if not (0 <= attachment.block_index < len(blocks)):
                continue
            if attachment.question_index is None or not (0 <= attachment.question_index < len(candidate_questions)):
                continue
            block = blocks[attachment.block_index]
            matched_q = candidate_questions[attachment.question_index]
            block.assigned_question_order = matched_q.order
            block.assigned_question_section_order = matched_q.section_order
            block.evidence_level = BlockEvidenceLevel.CONTENT_MATCHED
            block.justification += (
                " [Rattaché par correspondance de contenu (LLM) — aucun label explicite "
                "trouvé, plusieurs questions candidates dans la section.]"
            )
            matched_q.correction_blocks.append(block)

    async def _detect_correction_conflicts_via_llm(
        self,
        question: QuestionSpec,
        context: AgentExecutionContext,
    ) -> list[dict]:
        """
        Détecte les contradictions RÉELLES entre les blocs de correction TEXT
        d'UNE question, en UN SEUL appel voyant tous ces blocs à la fois —
        remplace l'ancienne heuristique par paire (similarité de texte, cf.
        historique de ce fichier) qui signalait à tort deux blocs simplement
        différents (ex. deux nœuds d'un même flowchart méthodologique) comme
        "conflit" dès que leur texte ne se ressemblait pas assez, ce qui
        devenait de plus en plus fréquent à mesure que _build_questions
        regroupe correctement de nombreux blocs complémentaires dans UNE
        question (constaté en test réel).

        Ne s'applique qu'aux blocs TEXT (comportement identique à l'ancienne
        heuristique, jamais étendu aux STRUCTURE/EQUATION/DIAGRAM ici). Repli
        prudent : silence total en cas d'échec LLM — un conflit non détecté
        n'est jamais pire qu'un faux positif, jamais l'inverse ici.

        Retourne les entrées prêtes pour correction_label_conflicts_detail.
        """
        text_blocks = [b for b in question.correction_blocks if b.raw_block.content_type == ExtractionContentType.TEXT]
        if len(text_blocks) < 2:
            return []

        blocks_listing = "\n".join(
            f"[{i}] {b.raw_block.prediction_ocr[:300]}" for i, b in enumerate(text_blocks)
        )
        user_msg = CORRECTION_CONFLICT_USER_TEMPLATE.format(
            question_label=question.question_label, count=len(text_blocks), blocks_listing=blocks_listing,
        )
        messages = [
            {"role": "system", "content": CORRECTION_CONFLICT_SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        try:
            result, _, _, _ = await invoke_llm_with_fallback(
                task_type=TaskType.DOCUMENT_STRUCTURING,
                messages=messages,
                response_schema=CorrectionConflictDetectionResult,
                context=context,
            )
        except Exception as e:
            logger.warning(f"{self.AGENT_NAME}: échec de la détection LLM de conflits — aucun conflit signalé : {e}")
            return []

        details: list[dict] = []
        for group in result.conflicts:
            valid_blocks = [text_blocks[i] for i in group.block_indices if 0 <= i < len(text_blocks)]
            if len(valid_blocks) < 2:
                continue
            logger.warning(
                f"{self.AGENT_NAME}: Conflit de correction sur la question '{question.question_label}' "
                f"entre {len(valid_blocks)} bloc(s) — {group.reason}"
            )
            details.append({
                "question_order": question.order,
                "question_label": question.question_label,
                "reason": group.reason,
                "blocks": [
                    {"block_index": b.block_index, "image_crop_path": b.raw_block.image_crop_path}
                    for b in valid_blocks
                ],
            })
        return details

    async def _attach_corrections(
        self,
        correction_blocks: list[ClassifiedBlock],
        questions: list[QuestionSpec],
        sections: list[SectionSpec],
        context: AgentExecutionContext,
    ) -> tuple[list[ClassifiedBlock], int, int, list[dict]]:
        """
        Rattache chaque bloc CORRECTION à une Question par label explicite,
        en tenant compte de la section (Correctif 4).

        Si aucun label exploitable ne permet un rattachement (absent, ou ne
        matchant aucune Question connue) : repli sans deviner à l'aveugle —
        rattachement direct si une SEULE Question existe dans la section
        (aucune ambiguïté possible), sinon rattachement par LE CONTENU via un
        passage LLM holistique voyant toutes les Questions candidates de la
        section à la fois (cf. _attach_unresolved_corrections_via_llm) —
        jamais un bloc laissé orphelin simplement parce qu'il n'a pas de
        label, tant qu'une décision fiable (déterministe ou par le sens) est
        possible. Un bloc en collision de label entre plusieurs sections
        (ambiguïté déjà détectée explicitement) n'entre PAS dans ce repli —
        cette ambiguïté-là reste non résolue à dessein.

        Détecte aussi les conflits entre corrections contradictoires (Correctif 5).

        Retourne (attached, unresolved_count, correction_label_conflict_count,
        correction_label_conflicts_detail) — le 4e élément localise précisément
        chaque conflit (question, blocs impliqués), pas seulement le compteur.
        """
        attached: list[ClassifiedBlock] = []
        unresolved_count = 0
        correction_label_conflict_count = 0
        correction_label_conflicts_detail: list[dict] = []
        needs_content_fallback: list[ClassifiedBlock] = []

        for block in correction_blocks:
            matched_q: QuestionSpec | None = None

            if block.question_label:
                # Étape 1 : matcher d'abord sur la section (si le bloc en a une)
                block_section = self._find_section_for_block(block, sections)

                # Étape 2 : matcher sur question_label parmi les questions de cette section
                norm_block_lbl = block.question_label.lower().replace("question", "").replace("q", "").strip()

                candidate_questions = questions
                if block_section is not None:
                    candidate_questions = [
                        q for q in questions if q.section_order == block_section.order
                    ]

                # Si le bloc n'a pas de section explicite mais qu'il existe plusieurs
                # sections avec des numéros de question en collision, ne pas trancher
                # arbitrairement → UNRESOLVED_NO_LABEL (ambiguïté à dessein non résolue,
                # jamais envoyée au repli par contenu ci-dessous).
                if block_section is None and len(sections) > 1:
                    # Vérifier s'il y a collision de numéros de question entre sections
                    section_question_labels: dict[int, set[str]] = {}
                    for q in questions:
                        section_question_labels.setdefault(q.section_order, set()).add(
                            q.question_label.lower().replace("question", "").replace("q", "").strip()
                        )
                    # Compter combien de sections contiennent ce label de question
                    sections_with_label = sum(
                        1 for labels in section_question_labels.values() if norm_block_lbl in labels
                    )
                    if sections_with_label > 1:
                        # Collision : ne pas deviner la section
                        block.assigned_question_order = None
                        block.assigned_question_section_order = None
                        block.evidence_level = BlockEvidenceLevel.UNRESOLVED_NO_LABEL
                        unresolved_count += 1
                        attached.append(block)
                        continue

                for q in candidate_questions:
                    norm_q_lbl = q.question_label.lower().replace("question", "").replace("q", "").strip()
                    if fuzz.ratio(norm_block_lbl, norm_q_lbl) > 85 or norm_block_lbl == norm_q_lbl:
                        matched_q = q
                        break

            if matched_q:
                block.assigned_question_order = matched_q.order
                block.assigned_question_section_order = matched_q.section_order
                block.evidence_level = BlockEvidenceLevel.LABEL_EXPLICITE
                matched_q.correction_blocks.append(block)
            else:
                block.assigned_question_order = None
                block.assigned_question_section_order = None
                needs_content_fallback.append(block)

            attached.append(block)

        # Repli sans label exploitable : par section résolue (jamais la chaîne
        # section_label brute, cf. _resolve_section_key_for_block), rattachement
        # déterministe si 1 seule Question candidate, sinon passage LLM holistique.
        fallback_by_section: dict[int | None, list[ClassifiedBlock]] = {}
        for block in needs_content_fallback:
            fallback_by_section.setdefault(self._resolve_section_key_for_block(block, sections), []).append(block)

        for sec_key, blocks in fallback_by_section.items():
            candidate_questions = [q for q in questions if q.section_order == sec_key]
            if len(candidate_questions) == 1:
                matched_q = candidate_questions[0]
                for block in blocks:
                    block.assigned_question_order = matched_q.order
                    block.assigned_question_section_order = matched_q.section_order
                    block.evidence_level = BlockEvidenceLevel.INFERRED_SINGLE_QUESTION
                    block.justification += (
                        " [Rattaché automatiquement : aucun label explicite, mais question "
                        "unique dans cette section — aucune ambiguïté possible.]"
                    )
                    matched_q.correction_blocks.append(block)
            elif len(candidate_questions) > 1:
                # Bug réel corrigé (2026-09-03, test réel examen C2PCT à 3
                # exercices) : un seul appel LLM avec TOUS les blocs sans
                # label d'une section (51 blocs constatés, un exercice entier
                # d'un examen à 3 exercices partageant la même section) a
                # silencieusement échoué à en rattacher aucun — probablement
                # une limite de sortie/complexité côté modèle sur un batch
                # aussi large, jamais rencontrée avec un seul exercice par
                # section. Découpage en lots de taille bornée, chaque lot
                # avec son propre appel (et son propre retry/repli en cas
                # d'échec, cf. _attach_unresolved_corrections_via_llm) —
                # jamais un tout-ou-rien sur l'ensemble de la section.
                for batch_start in range(0, len(blocks), _CORRECTION_ATTACHMENT_BATCH_SIZE):
                    batch = blocks[batch_start:batch_start + _CORRECTION_ATTACHMENT_BATCH_SIZE]
                    await self._attach_unresolved_corrections_via_llm(batch, candidate_questions, context)
            # 0 candidate : rien à faire, ces blocs restent non rattachés (compté ci-dessous).

        # Tout bloc encore sans evidence_level ici n'a été résolu par AUCUN chemin
        # (0 candidate, ou échec/omission du passage LLM) — jamais laissé à None.
        for block in needs_content_fallback:
            if block.evidence_level is None:
                block.evidence_level = BlockEvidenceLevel.UNRESOLVED_NO_LABEL

        unresolved_count += sum(1 for b in needs_content_fallback if b.assigned_question_order is None)

        # Correctif 5 : détection des conflits entre corrections contradictoires —
        # passage LLM holistique par question (cf. _detect_correction_conflicts_via_llm),
        # jamais une heuristique par paire (similarité de texte, faux positifs sur du
        # contenu simplement différent mais complémentaire).
        for q in questions:
            if len(q.correction_blocks) < 2:
                continue
            conflicts_for_q = await self._detect_correction_conflicts_via_llm(q, context)
            correction_label_conflict_count += len(conflicts_for_q)
            correction_label_conflicts_detail.extend(conflicts_for_q)

        return attached, unresolved_count, correction_label_conflict_count, correction_label_conflicts_detail