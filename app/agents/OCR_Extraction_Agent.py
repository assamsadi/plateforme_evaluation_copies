"""
Agent 1 — OCR_Extraction_Agent v3

Transforme un document scanné (PDF ou image) en une liste ordonnée de RawExtractedBlock
localisés et transcrits, incluant la reconstruction des structures spatiales complexes.

Réutilisé à l'identique dans les workflows étudiant et professeur.
Upload des crops Azure lorsque context.submission_id est renseigné (pipeline étudiant).
"""
import asyncio
import base64
import io
import logging
import time
from decimal import Decimal
from typing import Any

from PIL import Image
from pylatexenc.latexwalker import LatexWalker, LatexWalkerError
from pydantic import BaseModel, Field

from app.agents.context import AgentExecutionContext
from app.agents.ocr_block_utils import (
    compute_block_level_aggregates,
    compute_combined_confidence,
    extract_latex_string,
    sanitize_for_postgres_text,
    should_emit_block_at_ocr_output,
    to_decimal_confidence,
    validate_structure_content,
)
from app.agents.ocr_quality import (
    convert_document_to_images,
    deskew_and_preprocess,
    evaluate_image_quality,
)
from app.core.config import settings
from app.core.exceptions import DocumentQualityError, OCRExtractionError
from app.domain.models.assessment.extraction_correction import (
    ExtractionContentType,
    ExtractionEvidenceLevel,
    ExtractionOrigin,
    StructureType,
)
from app.domain.schemas.submission_schemas import RawExtractedBlock
from app.llm.client import invoke_llm_with_fallback
from app.model_registry.models import TaskType
from app.observability.langfuse import AgentTraceSpan
from app.infra_services.storage_paths import exercise_ocr_crop_path, submission_ocr_crop_path
from app.infra_services.storage_service import StorageContainer, storage_service
from app.prompts.ocr_extraction_prompt import (
    OCR_EXTRACTION_SYSTEM_PROMPT,
    OCR_RE_READ_SYSTEM_PROMPT,
    OCR_RE_READ_USER_TEMPLATE,
)

logger = logging.getLogger(__name__)


# --- Schémas Pydantic pour Structured Output LLM ---

class RawBlockOutput(BaseModel):
    content_type: ExtractionContentType
    structure_type: StructureType | None = None
    raw_text: str
    structured_content: dict | str | None = None
    bounding_box: dict = Field(..., description="{'x', 'y', 'width', 'height'} normalisées 0-1000")
    student_label: str | None = None
    model_self_confidence: float = Field(..., ge=0.0, le=1.0)
    reconstruction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    origin: ExtractionOrigin = ExtractionOrigin.HANDWRITTEN
    is_struck_through: bool = False


class PageExtractionResult(BaseModel):
    blocks: list[RawBlockOutput]


class OCRExtractionAgent:
    """Agent 1 v3 : extraction vision, reconstruction structurelle, validation déterministe."""

    @staticmethod
    def _ocr_vision_task_type(context: AgentExecutionContext) -> TaskType:
        """
        2026-08-29 (backlog_bugs_c2pct.md, couche 4) — le document de
        RÉFÉRENCE du professeur (flow_type="exercise_setup") utilise un
        palier de modèle supérieur (cf. TaskType.OCR_VISION_REFERENCE,
        registry.py) : volume structurellement faible (un document par
        exercice) mais impact d'une erreur maximal (propagée à TOUS les
        étudiants de l'exercice), contrairement à une copie individuelle
        (flow_type="student_evaluation"), qui reste sur OCR_VISION. Seul
        point de décision — jamais choisi par l'appelant directement.
        """
        if context.flow_type == "exercise_setup":
            return TaskType.OCR_VISION_REFERENCE
        return TaskType.OCR_VISION

    async def execute(
        self,
        document_bytes: bytes,
        mime_type: str,
        context: AgentExecutionContext,
    ) -> list[RawExtractedBlock]:
        """
        Pipeline v3 :
        1. Contrôle qualité (OpenCV) — échec immédiat si inexploitable.
        2. Prétraitement (deskew, resize).
        3. Découpage en pages.
        4. Lecture vision unifiée (segmentation + structures + ratures + origine).
        5. Validation déterministe (LaTeX / schéma JSON).
        6. Relecture ciblée unique (faible confiance combinée).
        7. Sortie RawExtractedBlock (filtrage PRINTED à la source pour TEXT/EQUATION).
        """
        with AgentTraceSpan(
            "OCR_Extraction_Agent",
            trace_id=context.trace_id,
            metadata={"flow_type": context.flow_type, "version": "v3"},
        ) as span:
            page_images = self._convert_document_to_images(document_bytes, mime_type)
            page_count = len(page_images)
            if page_count == 0:
                raise OCRExtractionError("Aucune page n'a pu être extraite du document")

            t_quality_start = time.perf_counter()
            quality_eval = evaluate_image_quality(page_images[0])
            quality_duration_ms = round((time.perf_counter() - t_quality_start) * 1000, 2)

            if not quality_eval["is_usable"]:
                raise DocumentQualityError(
                    reason=quality_eval["reason"] or "Qualité de scan insuffisante, merci de redéposer",
                    details=quality_eval,
                )

            processed_pages = [
                deskew_and_preprocess(p_bytes, angle=quality_eval["tilt_angle"])
                for p_bytes in page_images
            ]

            t_ocr_start = time.perf_counter()
            semaphore = asyncio.Semaphore(settings.OCR_MAX_CONCURRENCY)

            async def _process_page(page_num: int, img_bytes: bytes):
                async with semaphore:
                    return await self._extract_page_blocks(page_num, img_bytes, context)

            page_results = await asyncio.gather(*[
                _process_page(idx + 1, p_bytes)
                for idx, p_bytes in enumerate(processed_pages)
            ])
            ocr_duration_ms = round((time.perf_counter() - t_ocr_start) * 1000, 2)

            all_blocks: list[dict[str, Any]] = []
            page_image_map: dict[int, bytes] = {}
            provider_used = None
            model_used = None
            fallback_occurred = False
            total_tokens = 0

            for idx, (page_blocks, spec, fallback, tokens) in enumerate(page_results):
                page_image_map[idx + 1] = processed_pages[idx]
                all_blocks.extend(page_blocks)
                provider_used = spec.provider.value if spec else provider_used
                model_used = spec.model_name if spec else model_used
                fallback_occurred = fallback_occurred or fallback
                total_tokens += tokens.get("total_tokens", 0)

            global_index = 0
            for b in all_blocks:
                global_index += 1
                b["block_order_index"] = global_index

            t_validation_start = time.perf_counter()
            for b in all_blocks:
                b["schema_valid"] = self._validate_block_schema(b)
            validation_duration_ms = round((time.perf_counter() - t_validation_start) * 1000, 2)

            re_read_count = 0
            if settings.OCR_MAX_RE_READ_ATTEMPTS > 0:
                for b in all_blocks:
                    combined = compute_combined_confidence(
                        b["model_self_confidence"],
                        b.get("schema_valid"),
                        b.get("reconstruction_confidence"),
                    )
                    b["combined_confidence"] = combined
                    if combined < settings.OCR_CONFIDENCE_THRESHOLD:
                        page_img = page_image_map.get(b["page_number"])
                        if page_img:
                            updated = await self._re_read_block(b, page_img, context)
                            if updated:
                                re_read_count += 1
                                b.update(updated)
                                b["schema_valid"] = self._validate_block_schema(b)
                                b["combined_confidence"] = compute_combined_confidence(
                                    b["model_self_confidence"],
                                    b.get("schema_valid"),
                                    b.get("reconstruction_confidence"),
                                )

            for b in all_blocks:
                agg_origin, agg_struck = compute_block_level_aggregates(
                    b["content_type"],
                    b.get("structured_content"),
                    b.get("origin"),
                    b.get("is_struck_through", False),
                )
                b["origin"] = agg_origin
                b["is_struck_through"] = agg_struck

            # Bug réel corrigé (2026-09-03, cas zainabsebhi) : une copie
            # entièrement tapée à l'ordinateur fait classer une grande partie
            # de son texte en PRINTED par l'agent vision, faute de contraste
            # manuscrit à l'échelle de tout le document — le filtre origin=
            # PRINTED côté étudiant (cf. docstring should_emit_block_at_ocr_
            # output) supprimait alors silencieusement la quasi-totalité du
            # contenu réel de l'étudiant (21 blocs sur 27 dans le cas réel,
            # répartis sur 3 pages entières). Un simple "zéro bloc HANDWRITTEN
            # nulle part" s'est révélé trop strict : le modèle reste
            # INCOHÉRENT sur ce type de document (quelques paragraphes tapés
            # obtiennent quand même HANDWRITTEN, sans raison visuelle
            # distincte des autres) — cf. cas réel, 6 blocs HANDWRITTEN sur
            # une seule page alors que les 3 autres pages, visuellement
            # identiques, sont 100% PRINTED. D'où un seuil de MAJORITÉ plutôt
            # qu'un "zéro absolu" : si les blocs PRINTED sont majoritaires
            # dans TOUTE la soumission, un simple écho d'énoncé sur une copie
            # manuscrite classique n'en représente normalement qu'une petite
            # minorité — une majorité signale que le document lui-même est
            # probablement tapé, pas qu'une page de statement a été recopiée.
            text_or_equation_blocks = [
                b for b in all_blocks
                if b["content_type"] in (ExtractionContentType.TEXT, ExtractionContentType.EQUATION)
            ]
            printed_count = sum(
                1 for b in text_or_equation_blocks if b.get("origin") == ExtractionOrigin.PRINTED
            )
            handwritten_count = len(text_or_equation_blocks) - printed_count
            treat_printed_as_content = (
                context.flow_type == "student_evaluation"
                and bool(text_or_equation_blocks)
                and printed_count > handwritten_count
            )
            if treat_printed_as_content:
                logger.warning(
                    "OCR_Extraction_Agent: majorité de blocs PRINTED (%d) sur "
                    "HANDWRITTEN (%d) pour submission_id=%s — copie probablement "
                    "tapée à l'ordinateur, filtre origin=PRINTED désactivé pour "
                    "ne pas supprimer le contenu réel de l'étudiant.",
                    printed_count, handwritten_count, context.submission_id,
                )

            emit_blocks = [
                b for b in all_blocks
                if should_emit_block_at_ocr_output(
                    b, flow_type=context.flow_type, treat_printed_as_content=treat_printed_as_content,
                )
            ]
            filtered_printed_count = len(all_blocks) - len(emit_blocks)
            struck_through_count = sum(1 for b in all_blocks if b.get("is_struck_through", False))

            if context.submission_id is not None:
                await self._upload_block_crops(
                    emit_blocks,
                    page_image_map,
                    StorageContainer.SUBMISSIONS,
                    lambda page, idx: submission_ocr_crop_path(context.submission_id, page, idx),
                )
            elif context.exercise_id is not None and context.flow_type == "exercise_setup":
                await self._upload_block_crops(
                    emit_blocks,
                    page_image_map,
                    StorageContainer.EXERCISES,
                    lambda page, idx: exercise_ocr_crop_path(context.exercise_id, page, idx),
                )

            raw_extracted_blocks: list[RawExtractedBlock] = []
            for b in emit_blocks:
                combined = b.get("combined_confidence", b["model_self_confidence"])
                crop_path = b.get("image_crop_path")
                if crop_path is None:
                    # Cf. avertissement _upload_block_crops ci-dessus pour la
                    # cause exacte (page absente ou échec de recadrage) — ce
                    # chemin est fabriqué pour respecter RawExtractedBlock.
                    # image_crop_path (str requis, cf. schéma) mais NE POINTE
                    # VERS AUCUN BLOB RÉEL : tout code qui tente de le
                    # retélécharger (ex. dédoublonnage d'images) obtiendra un
                    # 404 BlobNotFound.
                    crop_path = f"temp/crops/page_{b['page_number']}_block_{b['block_order_index']}.png"
                    logger.error(
                        "OCR_Extraction_Agent: bloc #%s (page=%s) sans crop réel "
                        "uploadé — chemin de repli fabriqué (%s), AUCUNE image à "
                        "cette adresse.",
                        b["block_order_index"], b["page_number"], crop_path,
                    )
                raw_extracted_blocks.append(
                    RawExtractedBlock(
                        image_crop_path=crop_path,
                        content_type=b["content_type"],
                        structure_type=b.get("structure_type"),
                        prediction_ocr=sanitize_for_postgres_text(b["raw_text"]),
                        structured_output=sanitize_for_postgres_text(b.get("structured_content")),
                        confidence_score=to_decimal_confidence(combined),
                        reconstruction_confidence=(
                            to_decimal_confidence(b["reconstruction_confidence"])
                            if b.get("reconstruction_confidence") is not None
                            else None
                        ),
                        bounding_box=b["bounding_box"],
                        page_number=b["page_number"],
                        block_order_index=b["block_order_index"],
                        student_label=b.get("student_label"),
                        origin=b.get("origin"),
                        is_struck_through=b.get("is_struck_through", False),
                        evidence_level=(
                            ExtractionEvidenceLevel.LABEL_EXPLICITE
                            if b.get("student_label")
                            else ExtractionEvidenceLevel.AMBIGU
                        ),
                    )
                )

            span.record_metrics(
                quality_check_duration_ms=quality_duration_ms,
                ocr_duration_ms=ocr_duration_ms,
                validation_duration_ms=validation_duration_ms,
                page_count=page_count,
                total_block_count=len(raw_extracted_blocks),
                raw_block_count=len(all_blocks),
                filtered_printed_count=filtered_printed_count,
                typed_submission_detected=treat_printed_as_content,
                re_read_block_count=re_read_count,
                struck_through_block_count=struck_through_count,
                provider_used=provider_used,
                model_used=model_used,
                fallback_occurred=fallback_occurred,
                token_count=total_tokens,
                estimated_cost=round(total_tokens * 0.000002, 6),
            )

            return raw_extracted_blocks

    def _validate_block_schema(self, block: dict[str, Any]) -> bool | None:
        content_type = block["content_type"]
        if content_type == ExtractionContentType.EQUATION:
            latex_str = extract_latex_string(block.get("structured_content"), block["raw_text"])
            return self._validate_latex(latex_str)
        if content_type == ExtractionContentType.STRUCTURE:
            structure_type = block.get("structure_type")
            if isinstance(structure_type, str):
                structure_type = StructureType(structure_type)
            return validate_structure_content(structure_type, block.get("structured_content"))
        return None

    async def _re_read_block(
        self,
        block: dict[str, Any],
        page_image_bytes: bytes,
        context: AgentExecutionContext,
    ) -> dict[str, Any] | None:
        """Relecture ciblée unique sur la zone à faible confiance (étape 6)."""
        crop_bytes = self._crop_region(page_image_bytes, block["bounding_box"])
        if not crop_bytes:
            return None

        messages = [
            {"role": "system", "content": OCR_RE_READ_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": OCR_RE_READ_USER_TEMPLATE.format(page_number=block["page_number"]),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{self._to_base64(crop_bytes)}"},
                    },
                ],
            },
        ]

        try:
            result, _, _, _ = await invoke_llm_with_fallback(
                task_type=self._ocr_vision_task_type(context),
                messages=messages,
                response_schema=PageExtractionResult,
                context=context,
            )
            if not result.blocks:
                return None
            refreshed = result.blocks[0].model_dump()
            return {
                "content_type": refreshed["content_type"],
                "structure_type": refreshed.get("structure_type"),
                "raw_text": refreshed["raw_text"],
                "structured_content": refreshed.get("structured_content"),
                "bounding_box": refreshed["bounding_box"],
                "student_label": refreshed.get("student_label"),
                "model_self_confidence": refreshed["model_self_confidence"],
                "reconstruction_confidence": refreshed.get("reconstruction_confidence"),
                "origin": refreshed.get("origin", ExtractionOrigin.HANDWRITTEN),
                "is_struck_through": refreshed.get("is_struck_through", False),
            }
        except Exception as exc:
            logger.warning("Relecture ciblée échouée pour bloc %s : %s", block.get("block_order_index"), exc)
            return None

    def _convert_document_to_images(self, document_bytes: bytes, mime_type: str) -> list[bytes]:
        return convert_document_to_images(document_bytes, mime_type)

    async def _extract_page_blocks(
        self,
        page_num: int,
        image_bytes: bytes,
        context: AgentExecutionContext,
    ) -> tuple[list[dict[str, Any]], Any, bool, dict]:
        messages = [
            {"role": "system", "content": OCR_EXTRACTION_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extrais tous les blocs de la page {page_num}."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{self._to_base64(image_bytes)}"},
                    },
                ],
            },
        ]

        result, spec, fallback_occurred, token_usage = await invoke_llm_with_fallback(
            task_type=self._ocr_vision_task_type(context),
            messages=messages,
            response_schema=PageExtractionResult,
            context=context,
        )

        blocks_data = []
        for raw_b in result.blocks:
            b_dict = raw_b.model_dump()
            b_dict["page_number"] = page_num
            blocks_data.append(b_dict)

        return blocks_data, spec, fallback_occurred, token_usage

    async def _upload_block_crops(
        self,
        blocks: list[dict[str, Any]],
        page_image_map: dict[int, bytes],
        container: StorageContainer,
        path_builder,
    ) -> None:
        for block in blocks:
            page_img = page_image_map.get(block["page_number"])
            if not page_img:
                # page_image_map est peuplé pour TOUTES les pages du document
                # (cf. execute(), une entrée par page 1..page_count) — si ce
                # get() échoue, block["page_number"] pointe vers une page qui
                # n'existe pas (hallucination OCR sur ce champ). Le bloc ne
                # recevra jamais de crop réel : le repli fabriqué plus bas
                # (RawExtractedBlock.image_crop_path) pointera vers un blob
                # jamais uploadé.
                logger.warning(
                    "OCR_Extraction_Agent: pas d'image de page pour page_number=%s "
                    "(bloc #%s) — pages disponibles : %s. Ce bloc n'aura pas de "
                    "crop réel (image_crop_path de repli, jamais uploadé).",
                    block["page_number"], block.get("block_order_index"), sorted(page_image_map),
                )
                continue
            crop_bytes = self._crop_region(page_img, block["bounding_box"])
            if not crop_bytes:
                logger.warning(
                    "OCR_Extraction_Agent: échec du recadrage pour le bloc #%s "
                    "(page=%s, bounding_box=%s) — cf. avertissement _crop_region "
                    "ci-dessus pour la cause exacte. Ce bloc n'aura pas de crop "
                    "réel (image_crop_path de repli, jamais uploadé).",
                    block.get("block_order_index"), block["page_number"], block["bounding_box"],
                )
                continue
            blob_path = path_builder(block["page_number"], block["block_order_index"])
            await storage_service.upload(
                container,
                blob_path,
                crop_bytes,
                content_type="image/png",
            )
            block["image_crop_path"] = blob_path

    @staticmethod
    def _validate_latex(latex_str: str) -> bool:
        if not latex_str or not latex_str.strip():
            return False
        try:
            LatexWalker(latex_str).get_latex_nodes()
            return True
        except LatexWalkerError:
            return False
        except Exception:
            return False

    @staticmethod
    def _crop_region(page_image_bytes: bytes, bounding_box: dict) -> bytes | None:
        """Recadre une zone normalisée (0-1000) depuis l'image de page."""
        try:
            img = Image.open(io.BytesIO(page_image_bytes))
            w, h = img.size
            # Bug réel corrigé (2026-09-03, test réel zainabsebhi) : le modèle
            # vision a produit un bounding_box hors de l'espace normalisé
            # 0-1000 attendu (ex. y=1098) — x/y n'étaient clampés qu'APRÈS
            # coup via x2=min(w, x+bw)/y2=min(h, y+bh), jamais x/y eux-mêmes.
            # Si x ou y dépasse déjà w/h, x2/y2 (bornés à w/h) finissent
            # INFÉRIEURS à x/y non bornés → PIL lève "Coordinate 'lower' is
            # less than 'upper'" au lieu d'un crop simplement tronqué. x/y
            # clampés en premier ici, avant tout calcul de x2/y2 : plus aucune
            # combinaison de coordonnées ne peut produire un rectangle inversé,
            # quelle que soit la valeur (même invalide) renvoyée par le modèle.
            x = min(w, max(0, int(bounding_box["x"] / 1000 * w)))
            y = min(h, max(0, int(bounding_box["y"] / 1000 * h)))
            bw = max(1, int(bounding_box["width"] / 1000 * w))
            bh = max(1, int(bounding_box["height"] / 1000 * h))
            x2 = min(w, x + bw)
            y2 = min(h, y + bh)

            # Marge de sécurité (2026-09-05, test réel FR/ES) : le bounding_box
            # du modèle vision sous-estime parfois légèrement la zone réelle
            # (constaté visuellement — le haut de la première ligne d'un bloc
            # manuscrit apparaissait tronqué, puis un second constat réel :
            # un mot coupé en deux verticalement sur un bloc très court, où
            # 15% de la hauteur du bloc ne représentait que 4-5px — bien
            # insuffisant). Plancher = le MAX entre une fraction du bloc et
            # une fraction de la page entière (jamais seulement l'un des deux :
            # un bloc d'une seule ligne courte a besoin d'une marge absolue
            # suffisante, pas juste proportionnelle à sa propre petite
            # hauteur). Appliquée UNIQUEMENT à l'image affichée — le
            # bounding_box stocké en base n'est jamais modifié.
            pad_x = max(int(bw * 0.08), int(w * 0.006))
            pad_y = max(int(bh * 0.35), int(h * 0.012))
            x = max(0, x - pad_x)
            y = max(0, y - pad_y)
            x2 = min(w, x2 + pad_x)
            y2 = min(h, y2 + pad_y)
            if x2 <= x or y2 <= y:
                # x/y déjà clampés au bord de l'image (bounding_box hors de
                # l'espace 0-1000 attendu, cf. commentaire ci-dessus) — aucune
                # zone réelle à recadrer ; PIL lève "cannot write empty image"
                # sur un crop de largeur/hauteur nulle, un repli explicite ici
                # évite de dépendre de cette exception pour le même constat.
                return None
            cropped = img.crop((x, y, x2, y2))
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.warning(
                "OCR_Extraction_Agent: exception pendant le recadrage "
                "(bounding_box=%s) : %r", bounding_box, e,
            )
            return None

    @staticmethod
    def _to_base64(data: bytes) -> str:
        return base64.b64encode(data).decode("utf-8")
