"""
Module déterministe de contrôle qualité et prétraitement d'image (Étape 1 & 2 d'OCR_Extraction_Agent).
OpenCV & Pillow — AUCUN appel LLM n'est effectué ici.
"""
import io
import math
import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

from app.core.config import settings
from app.core.exceptions import DocumentQualityError, OCRExtractionError


def convert_document_to_images(document_bytes: bytes, mime_type: str) -> list[bytes]:
    """
    PDF/image brut -> une image PNG par page, dans l'ordre physique.
    Extrait d'OCR_Extraction_Agent (étape 3) pour être réutilisable par
    scan_quality_control_node — le contrôle qualité déterministe (§1) a
    besoin de cette même conversion AVANT même que l'agent OCR ne tourne.
    """
    if "pdf" in mime_type.lower() or document_bytes.startswith(b"%PDF"):
        doc = fitz.open(stream=document_bytes, filetype="pdf")
        return [page.get_pixmap(dpi=150).tobytes("png") for page in doc]

    try:
        img = Image.open(io.BytesIO(document_bytes))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return [buf.getvalue()]
    except Exception as e:
        raise OCRExtractionError(f"Format de document non supporté : {e}") from e


def evaluate_image_quality(image_bytes: bytes) -> dict:
    """
    Calcule les métriques de qualité visuelle d'une image :
    - Variance du Laplacien (netteté)
    - Luminosité moyenne
    - Contraste (écart-type des niveaux de gris)
    - Angle d'inclinaison estimé (deskew)
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise DocumentQualityError("Impossible de décoder le fichier en image valide")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. Netteté via variance du Laplacien
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

    # 2. Luminosité et contraste
    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))

    # 3. Estimation d'inclinaison (angle deskew) via contours/minAreaRect
    angle = _estimate_tilt_angle(gray)

    is_usable = bool(laplacian_var >= settings.OCR_MIN_LAPLACIAN_VARIANCE and contrast >= 15.0)

    reason = None
    if not is_usable:
        if laplacian_var < settings.OCR_MIN_LAPLACIAN_VARIANCE:
            reason = f"Image trop floue (variance Laplacien {laplacian_var:.1f} < {settings.OCR_MIN_LAPLACIAN_VARIANCE})"
        elif contrast < 15.0:
            reason = f"Contraste insuffisant (écart-type {contrast:.1f} < 15.0)"

    return {
        "is_usable": is_usable,
        "laplacian_variance": round(laplacian_var, 2),
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "tilt_angle": round(angle, 2),
        "reason": reason,
    }


def _estimate_tilt_angle(gray_img: np.ndarray) -> float:
    """Estime l'angle d'inclinaison du texte dans l'image."""
    edges = cv2.Canny(gray_img, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100, minLineLength=100, maxLineGap=10)
    if lines is None:
        return 0.0

    angles = []
    for line in lines:
        coords = line.ravel()
        if len(coords) == 4:
            x1, y1, x2, y2 = coords
            angle = math.degrees(math.atan2(float(y2 - y1), float(x2 - x1)))
            if -45 < angle < 45:
                angles.append(angle)

    return float(np.median(angles)) if angles else 0.0


def deskew_and_preprocess(image_bytes: bytes, angle: float, max_dimension: int = 2048) -> bytes:
    """
    Corrige l'inclinaison (deskew) et redimensionne au format optimal pour le modèle Vision.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes

    # Deskew si l'angle est significatif (> 0.5 degré)
    if abs(angle) > 0.5:
        h, w = img.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    # Redimensionnement Pillow tout en conservant le ratio
    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    w, h = pil_img.size
    if max(w, h) > max_dimension:
        ratio = max_dimension / float(max(w, h))
        new_size = (int(w * ratio), int(h * ratio))
        pil_img = pil_img.resize(new_size, Image.Resampling.LANCZOS)

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    return buf.getvalue()
