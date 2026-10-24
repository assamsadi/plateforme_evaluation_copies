"""Conventions de nommage des blobs Azure."""
import uuid


def submission_original_path(submission_id: uuid.UUID, extension: str) -> str:
    ext = extension.lstrip(".")
    return f"submissions/{submission_id}/original.{ext}"


def submission_ocr_crop_path(
    submission_id: uuid.UUID,
    page_number: int,
    block_order_index: int,
) -> str:
    return f"submissions/{submission_id}/ocr_crops/page_{page_number}_block_{block_order_index}.png"


def exercise_reference_document_path(exercise_id: uuid.UUID, extension: str) -> str:
    ext = extension.lstrip(".")
    return f"exercises/{exercise_id}/reference.{ext}"


def exercise_ocr_crop_path(
    exercise_id: uuid.UUID,
    page_number: int,
    block_order_index: int,
) -> str:
    return f"exercises/{exercise_id}/ocr_crops/page_{page_number}_block_{block_order_index}.png"


def contestation_reread_crop_path(
    extraction_correction_id: uuid.UUID,
    attempt: int,
) -> str:
    """
    Crop en pleine résolution utilisé par Contestation_Verification_Agent pour
    l'OCR2 (Cas A/C) — distinct de submission_ocr_crop_path (potentiellement
    compressé pour le stockage initial). §9 du doc de référence agent exige de
    tracer le chemin EXACT de l'image utilisée pour un verdict donné ; `attempt`
    distingue plusieurs relectures d'un même bloc (jamais un écrasement silencieux).
    """
    return (
        f"contestations/{extraction_correction_id}/reread_attempt_{attempt}.png"
    )


def mime_to_extension(mime_type: str) -> str:
    mapping = {
        "application/pdf": "pdf",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/webp": "webp",
        "image/tiff": "tiff",
    }
    normalized = mime_type.split(";")[0].strip().lower()
    return mapping.get(normalized, "bin")
