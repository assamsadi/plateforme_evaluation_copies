"""
Exceptions pour Comparative_Evaluation_Agent (§5 du document d'architecture).
"""

class ComparativeEvaluationError(Exception):
    """Exception de base pour toutes les erreurs de Comparative_Evaluation_Agent."""


class UnknownCorrectionModeError(ComparativeEvaluationError):
    """Levée lorsqu'un critère porte un correction_mode inconnu/non géré."""

    def __init__(self, mode: str):
        self.mode = mode
        super().__init__(
            f"Mode de correction inconnu ou non pris en charge par Comparative_Evaluation_Agent : {mode!r}. "
            f"Les modes valides sont : 'solution_worked', 'criteria_based', 'binary_checklist', "
            f"'multiple_distinct_answers', 'rubric_levels', 'procedural_sequence', 'test_case_based'."
        )


class SandboxExecutionError(ComparativeEvaluationError):
    """Levée lors d'un échec d'infrastructure du bac à sable d'exécution (Judge0)."""
