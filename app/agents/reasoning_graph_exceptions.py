"""
Exceptions spécifiques à Reasoning_Graph_Agent et ReasoningGraphService.
"""
import uuid
from app.core.exceptions import DomainError


class ReasoningGraphError(DomainError):
    """Erreur de base pour Reasoning_Graph_Agent."""
    def __init__(self, message: str) -> None:
        super().__init__(message)


class ReasoningGraphCycleError(ReasoningGraphError):
    """Erreur levée lorsqu'un cycle insoluble est détecté dans le graphe après retries."""
    def __init__(self, variant_id: uuid.UUID, cycle_details: str) -> None:
        self.variant_id = variant_id
        self.cycle_details = cycle_details
        super().__init__(
            f"Graphe invalide pour la variante {variant_id} : cycle détecté ({cycle_details})."
        )


class VariantNotFoundError(ReasoningGraphError):
    """Erreur levée lorsqu'une SolutionVariant n'est pas trouvée en base."""
    def __init__(self, variant_id: uuid.UUID) -> None:
        self.variant_id = variant_id
        super().__init__(f"SolutionVariant {variant_id} introuvable.")


class ExerciseAlreadyPublishedError(ReasoningGraphError):
    """Erreur levée lorsqu'un redéclenchement est tenté sur un exercice publié."""
    def __init__(self, exercise_id: uuid.UUID, status: str) -> None:
        self.exercise_id = exercise_id
        self.status = status
        super().__init__(
            f"Impossible d'exécuter Reasoning_Graph_Agent sur l'exercice {exercise_id} déjà publié (statut: {status})."
        )
