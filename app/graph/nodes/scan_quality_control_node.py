"""
Nœud LangGraph — scan_quality_control_node.

Contrôle qualité globale déterministe (netteté, luminosité/contraste,
inclinaison — OpenCV, aucun appel LLM), commun aux deux flows, exécuté
avant tout appel à OCR_Extraction_Agent. Fichier anticipé de longue date
dans le repo (nom déjà présent) mais jamais implémenté ni câblé jusqu'ici —
le contrôle existait seulement comme étape 1 interne d'OCR_Extraction_Agent.

Ce nœud NE remplace PAS ce contrôle interne, il s'y ajoute (défense en
profondeur, décision actée) : échouer ici évite de dépenser un
téléchargement + une conversion PDF->images dans document_structuring_node/
question_attachment_node sur un document déjà connu inexploitable, mais
OCR_Extraction_Agent reste protégé même appelé hors graph (tests, usage
direct) puisqu'il refait le même contrôle en étape 1 de son propre pipeline.

Ne vérifie que la première page (même convention que OCR_Extraction_Agent
étape 1) — un contrôle exhaustif page par page serait un vrai gain futur,
mais changerait la sémantique de l'échec (page N vs document entier), hors
mandat de ce ticket.
"""
from datetime import datetime, timezone

from app.agents.ocr_quality import convert_document_to_images, evaluate_image_quality
from app.core.exceptions import DocumentQualityError, OCRExtractionError
from app.graph.state import PipelineState
from app.infra_services.storage_service import StorageContainer, storage_service


async def scan_quality_control_node(state: PipelineState) -> PipelineState:
    container = (
        StorageContainer.EXERCISES
        if state.flow_type == "exercise_setup"
        else StorageContainer.SUBMISSIONS
    )

    document_bytes = await storage_service.download(container, state.raw_file_path)
    page_images = convert_document_to_images(document_bytes, state.mime_type)
    if not page_images:
        raise OCRExtractionError("Aucune page n'a pu être extraite du document")

    quality_eval = evaluate_image_quality(page_images[0])
    if not quality_eval["is_usable"]:
        raise DocumentQualityError(
            reason=quality_eval["reason"] or "Qualité de scan insuffisante, merci de redéposer",
            details=quality_eval,
        )

    state.status = "RUNNING"
    state.updated_at = datetime.now(timezone.utc)
    return state
