"""
Exceptions métier spécifiques à Contestation_Verification_Agent.
"""
import uuid


class AlreadyResolvedContestationError(Exception):
    """
    Garde-fou défensif pour §2 étape 8 du doc de référence : jamais un second
    passage automatique par l'agent sur le même bloc après un premier verdict
    IMPLAUSIBLE (ou déjà RESOLVED par le professeur). L'appelant doit escalader
    directement vers teacher_arbitration_node, jamais réinvoquer l'agent.
    """
    def __init__(self, extraction_correction_id: uuid.UUID, current_status: str) -> None:
        self.extraction_correction_id = extraction_correction_id
        self.current_status = current_status
        super().__init__(
            f"Correction {extraction_correction_id} déjà tranchée (statut={current_status}) "
            "— aucun second passage automatique par l'agent n'est autorisé."
        )


class ContestationSchemaError(Exception):
    """Sortie LLM non conforme au schéma attendu après épuisement du retry métier."""
    def __init__(self, extraction_correction_id: uuid.UUID, raw_response: str) -> None:
        self.extraction_correction_id = extraction_correction_id
        super().__init__(
            f"Correction {extraction_correction_id} — sortie LLM non conforme "
            f"après retry : {raw_response!r:.200}"
        )


class FusionGroupNotFoundError(Exception):
    """
    Cas D ('wrongly_merged') : le bloc contesté ne référence aucun groupe de
    fusion exploitable (fused_extraction_correction_ids vide côté survivant,
    et le bloc n'est identifié comme consommé par aucun autre groupe fourni)
    — il n'y a rien à défusionner.
    """
    def __init__(self, extraction_correction_id: uuid.UUID) -> None:
        self.extraction_correction_id = extraction_correction_id
        super().__init__(
            f"Correction {extraction_correction_id} : aucun groupe de fusion de continuité "
            "associé — contestation de fusion sans fusion à revérifier."
        )


class StructureElementNotFoundError(Exception):
    """Cas C : contested_element_id ne résout à aucun élément dans structured_output."""
    def __init__(self, extraction_correction_id: uuid.UUID, contested_element_id: str) -> None:
        self.extraction_correction_id = extraction_correction_id
        self.contested_element_id = contested_element_id
        super().__init__(
            f"Correction {extraction_correction_id} : élément '{contested_element_id}' "
            "introuvable dans structured_output."
        )
