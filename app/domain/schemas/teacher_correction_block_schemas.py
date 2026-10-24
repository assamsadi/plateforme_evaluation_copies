"""
Schémas Pydantic pour TeacherCorrectionBlock et la résolution des ambiguïtés par le professeur.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import settings
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.assessment.teacher_correction_block import BlockEvidenceLevel


class TeacherCorrectionBlockRead(BaseModel):
    """Lecture d'un bloc de correction enseignant."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exercise_id: uuid.UUID
    question_id: uuid.UUID | None = None
    image_crop_url: str | None = None  # URL SAS résolue, jamais le blob_path brut
    content_type: ExtractionContentType
    raw_text: str | None = None
    # dict | str : OCR_Extraction_Agent renvoie une chaîne LaTeX brute (pas
    # un dict structuré) pour une équation isolée simple (ex. "σ_max = 275
    # MPa") — comportement normal de cet agent, jamais transformé en dict
    # artificiellement. Un type trop strict ici (dict | None) faisait
    # planter la construction de TOUTE la liste de blocs dès qu'un seul
    # bloc EQUATION du document arrivait sous cette forme (ValidationError
    # constatée en test réel, pipeline exercise_setup).
    structured_content: dict | str | None = None
    evidence_level: BlockEvidenceLevel
    professor_resolution: str | None = None
    justification: str
    created_at: datetime | None = None
    ocr_confidence: Decimal | None = None
    # B11 (backlog_bugs_c2pct.md) — flag visible non-bloquant, calculé ici
    # (jamais stocké) pour que le frontend n'ait pas à connaître le seuil :
    # même seuil que OCR_Extraction_Agent utilise pour déclencher sa propre
    # relecture ciblée (settings.OCR_CONFIDENCE_THRESHOLD) — un bloc qui
    # reste sous ce seuil APRÈS relecture mérite un signal visible pour le
    # professeur. Ne bloque jamais la publication (contrairement à
    # UNRESOLVED_NO_LABEL) : c'est une invitation à vérifier, pas une
    # ambiguïté sans décision possible.
    is_low_ocr_confidence: bool = False

    @model_validator(mode="after")
    def _compute_is_low_ocr_confidence(self) -> "TeacherCorrectionBlockRead":
        if self.ocr_confidence is not None:
            self.is_low_ocr_confidence = self.ocr_confidence < Decimal(str(settings.OCR_CONFIDENCE_THRESHOLD))
        return self



class BlockResolutionItem(BaseModel):
    """Élément de résolution individuelle pour un bloc UNRESOLVED_NO_LABEL."""
    block_id: uuid.UUID
    question_id: uuid.UUID | None = None
    professor_resolution: str = Field(
        ..., min_length=1, description="Explication/justification du professeur pour cette résolution."
    )


class BulkBlockResolutionRequest(BaseModel):
    """Requête de résolution en masse de blocs de correction."""
    resolutions: list[BlockResolutionItem] = Field(..., min_length=1)
