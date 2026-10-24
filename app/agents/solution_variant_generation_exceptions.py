"""
Exceptions spécifiques à Solution_Variant_Generation_Agent.
"""
import uuid


class SolutionVariantGenerationError(Exception):
    """Exception de base pour les erreurs liées à la génération de variantes de solution."""
    pass


class MandatedMethodSkipNotice(SolutionVariantGenerationError):
    """Signalé lorsqu'une méthode est imposée (mandated_method) et qu'aucune variante ne doit être générée."""

    def __init__(self, question_id: uuid.UUID, mandated_method: str) -> None:
        self.question_id = question_id
        self.mandated_method = mandated_method
        super().__init__(
            f"Question {question_id} possède une méthode imposée ('{mandated_method}'). "
            f"Génération de variantes désactivée par construction."
        )


class SympyVerificationError(SolutionVariantGenerationError):
    """Levée lorsqu'une candidate échoue la vérification d'équivalence mathématique."""

    def __init__(self, candidate_summary: str, reason: str) -> None:
        self.candidate_summary = candidate_summary
        self.reason = reason
        super().__init__(f"Échec de validation SymPy pour '{candidate_summary}' : {reason}")


class ExerciseAlreadyPublishedError(SolutionVariantGenerationError):
    """
    Levée uniquement pour le déclencheur proactif (2.1) sur un exercice déjà
    publié. Même famille que les ExerciseAlreadyPublishedError des autres
    agents (une par agent, jamais partagées, cf. exercise_tasks.py) — jamais
    levée pour les déclencheurs 2.2 (à la demande) / 2.3 (guidé), qui sont
    l'exception documentée à la règle de blocage post-publication.
    """
    def __init__(self, exercise_id: uuid.UUID, status: str) -> None:
        self.exercise_id = exercise_id
        self.status = status
        super().__init__(
            f"Impossible d'exécuter une génération proactive de variantes sur "
            f"l'exercice {exercise_id} déjà publié (statut: {status}). "
            f"Les parcours à la demande et guidé restent autorisés."
        )


class StructuralDuplicationError(SolutionVariantGenerationError):
    """Levée lorsqu'une candidate est rejetée car structurellement identique à une variante existante."""

    def __init__(self, candidate_summary: str, existing_variant_id: uuid.UUID, distinction_score: float) -> None:
        self.candidate_summary = candidate_summary
        self.existing_variant_id = existing_variant_id
        self.distinction_score = distinction_score
        super().__init__(
            f"Variante '{candidate_summary}' rejetée comme doublon de {existing_variant_id} "
            f"(score de distinction : {distinction_score:.2f} < 0.35)"
        )
