"""
Exceptions métier spécifiques à Extraction_Verification_Agent.
"""
import uuid


class ExerciseAlreadyPublishedError(Exception):
    """
    L'exercice a déjà été publié — l'agent refuse tout nouveau traitement
    automatique pour ne jamais modifier silencieusement la base de notation
    d'étudiants en cours de composition ou déjà évalués.
    """
    def __init__(self, exercise_id: uuid.UUID, status: str) -> None:
        self.exercise_id = exercise_id
        self.status = status
        super().__init__(
            f"Exercice {exercise_id} déjà publié (status={status}) — "
            "vérification d'extraction automatique refusée. Modification manuelle requise."
        )


class DecompositionSchemaError(Exception):
    """
    La sortie LLM de décomposition en étapes n'est pas conforme au schéma
    attendu après le retry métier unique — ou aucune étape CONCLUSION n'a
    été produite (jamais une conclusion inventée pour combler).
    """
    def __init__(self, question_id: uuid.UUID, raw_response: str) -> None:
        self.question_id = question_id
        super().__init__(
            f"Question {question_id} — décomposition LLM non conforme : {raw_response!r:.200}"
        )


class MissingBaremeError(Exception):
    """
    Cas 3 (§2) — aucun chiffre de notation nulle part dans la correction de
    cette question. Blocage strict, jamais de formulaire : la question ne
    peut recevoir aucune proposition de barème tant qu'aucun chiffre n'est
    présent dans le texte source.
    """
    def __init__(self, question_id: uuid.UUID) -> None:
        self.question_id = question_id
        super().__init__(
            f"Question {question_id} — aucun chiffre de notation trouvé dans la correction, "
            "barème impossible à établir."
        )


class BaremeExtractionSchemaError(Exception):
    """
    La sortie LLM de rattachement/proposition de barème (Cas 1/Cas 2) n'est
    pas conforme au schéma attendu après le retry métier unique.
    """
    def __init__(self, question_id: uuid.UUID, raw_response: str) -> None:
        self.question_id = question_id
        super().__init__(
            f"Question {question_id} — extraction de barème LLM non conforme : {raw_response!r:.200}"
        )


class ModeClassificationSchemaError(Exception):
    """
    La classification de correction_mode d'au moins un critère (Phase 2, §2bis)
    n'est pas conforme au schéma attendu après le retry métier unique — valeur
    hors des 7 modes autorisés, ou champ manquant. Jamais un mode deviné par
    défaut silencieusement.
    """
    def __init__(self, question_id: uuid.UUID, raw_response: str) -> None:
        self.question_id = question_id
        super().__init__(
            f"Question {question_id} — classification de mode LLM non conforme : {raw_response!r:.200}"
        )
