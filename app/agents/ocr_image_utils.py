"""
Utilitaires image partagés pour OCR_Extraction_Agent et le pipeline de soumission.
Conversion document → pages, prétraitement, recadrage de zones.
"""
from __future__ import annotations

import io

import fitz
from PIL import Image

from app.agents.ocr_quality import deskew_and_preprocess, evaluate_image_quality
from app.core.exceptions import DocumentQualityError, OCRExtractionError
from app.domain.schemas.submission_schemas import RawExtractedBlock


def document_to_page_images(document_bytes: bytes, mime_type: str) -> list[bytes]:
    """Convertit un PDF ou une image en liste d'images PNG (une par page)."""
    if "pdf" in mime_type.lower() or document_bytes.startswith(b"%PDF"):
        doc = fitz.open(stream=document_bytes, filetype="pdf")
        return [page.get_pixmap(dpi=150).tobytes("png") for page in doc]

    try:
        img = Image.open(io.BytesIO(document_bytes))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return [buf.getvalue()]
    except Exception as exc:
        raise OCRExtractionError(f"Format de document non supporté : {exc}") from exc


def prepare_document_pages(document_bytes: bytes, mime_type: str) -> list[bytes]:
    """
    Étapes 1–3 du pipeline OCR : contrôle qualité, deskew, découpage pages.
    Lève DocumentQualityError si le scan est inexploitable.
    """
    page_images = document_to_page_images(document_bytes, mime_type)
    if not page_images:
        raise OCRExtractionError("Aucune page n'a pu être extraite du document")

    quality_eval = evaluate_image_quality(page_images[0])
    if not quality_eval["is_usable"]:
        raise DocumentQualityError(
            reason=quality_eval["reason"] or "Qualité de scan insuffisante, merci de redéposer",
            details=quality_eval,
        )

    return [
        deskew_and_preprocess(page_bytes, angle=quality_eval["tilt_angle"])
        for page_bytes in page_images
    ]


def crop_region(page_image_bytes: bytes, bounding_box: dict, padding_ratio: float = 0.0) -> bytes | None:
    """
    Recadre une zone normalisée (0–1000) depuis une image de page.

    padding_ratio : marge additionnelle de chaque côté, en fraction des
    DIMENSIONS DE LA PAGE (pas de la boîte elle-même — un pourcentage de la
    page compense mieux une boîte systématiquement trop serrée qu'un
    pourcentage de sa propre taille, qui reste petit si la boîte l'est déjà).
    0.0 par défaut = comportement historique inchangé pour tout appelant
    existant. Trouvé nécessaire le 2026-08-18 : les bounding-box rapportées
    par un LLM vision sont approximatives (ex. hauteur sous-estimée pour un
    paragraphe manuscrit qui retourne à la ligne plus de fois que prévu) —
    Contestation_Verification_Agent recadre "à l'aveugle" pour une relecture
    indépendante, et un recadrage pixel-exact peut couper le contenu même
    qu'il doit vérifier, produisant un AMBIGU artificiel (rien vu, jamais
    un vrai désaccord) plutôt qu'un vrai verdict. Jamais appliqué à la
    détection initiale d'OCR_Extraction_Agent (sa propre méthode séparée,
    non affectée) — seulement à une relecture dont le but est justement de
    corriger l'imprécision de la première passe.
    """
    try:
        img = Image.open(io.BytesIO(page_image_bytes))
        width, height = img.size
        pad_x = int(padding_ratio * width)
        pad_y = int(padding_ratio * height)
        x = int(bounding_box["x"] / 1000 * width) - pad_x
        y = int(bounding_box["y"] / 1000 * height) - pad_y
        box_w = max(1, int(bounding_box["width"] / 1000 * width)) + 2 * pad_x
        box_h = max(1, int(bounding_box["height"] / 1000 * height)) + 2 * pad_y
        x2 = min(width, x + box_w)
        y2 = min(height, y + box_h)
        cropped = img.crop((max(0, x), max(0, y), x2, y2))
        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def crop_block_from_pages(
    processed_pages: list[bytes],
    block: RawExtractedBlock,
) -> bytes | None:
    page_idx = block.page_number - 1
    if page_idx < 0 or page_idx >= len(processed_pages):
        return None
    return crop_region(processed_pages[page_idx], block.bounding_box)
