"""
Exceptions métier spécifiques à Question_Attachment_Agent.
"""
import uuid


class MissingReferenceSolutionError(Exception):
    """
    Levée si au moins une Question de l'exercice n'a pas de SolutionVariant
    de référence (is_reference=True) disponible.
    L'agent ne peut pas rattacher sans base de comparaison.
    """
    def __init__(self, exercise_id: uuid.UUID, missing_question_ids: list[uuid.UUID]) -> None:
        self.exercise_id = exercise_id
        self.missing_question_ids = missing_question_ids
        super().__init__(
            f"Exercice {exercise_id} : {len(missing_question_ids)} question(s) sans variante "
            f"de référence — IDs : {missing_question_ids}"
        )


class AttachmentSchemaError(Exception):
    """
    Sortie LLM non conforme au schéma attendu après épuisement du retry métier.
    Le bloc sera forcé en AMBIGU avec cette justification.
    """
    def __init__(self, block_index: int, raw_response: str) -> None:
        self.block_index = block_index
        super().__init__(
            f"Bloc #{block_index} — sortie LLM non conforme après retry : {raw_response!r:.200}"
        )


class AttachmentTimeoutError(Exception):
    """Timeout global dépassé pour le traitement d'une soumission entière."""
    def __init__(self, submission_id: uuid.UUID, timeout_seconds: int) -> None:
        self.submission_id = submission_id
        super().__init__(
            f"Timeout global ({timeout_seconds}s) atteint pour la soumission {submission_id}"
        )
