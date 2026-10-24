"""
Service d'évaluation du score de confiance de la correction automatique.
Détermine si une copie doit être validée directement ou envoyée en arbitrage enseignant.
"""
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class CorrectionConfidenceScorer:
    """Calculateur du score de confiance d'une correction IA (0.0 à 1.0)."""

    def compute_confidence(
        self,
        ocr_confidence: float,
        llm_uncertainty: float,
        rubric_alignment: float,
    ) -> Decimal:
        """
        Calcule un score global pondéré :
        - 40% qualité OCR
        - 40% certitude du modèle de raisonnement
        - 20% alignement avec le barème
        """
        score = (ocr_confidence * 0.4) + ((1.0 - llm_uncertainty) * 0.4) + (rubric_alignment * 0.2)
        score_bounded = max(0.0, min(1.0, score))
        return Decimal(str(round(score_bounded, 4)))

    def requires_arbitration(self, confidence_score: Decimal, threshold: Decimal = Decimal("0.75")) -> bool:
        """Détermine si la correction manque de certitude et nécessite un arbitrage humain."""
        return confidence_score < threshold
