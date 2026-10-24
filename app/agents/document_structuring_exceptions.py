"""
Exceptions métier spécifiques à Document_Structuring_Agent.
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
            "structuration automatique refusée. Modification manuelle requise."
        )


class StructuringIncompleteError(Exception):
    """
    Le document structuré est dans un état INCOMPLETE : il manque des
    rattachements de correction, des résolutions de conflits ou des
    questions sans correction.

    Ce n'est PAS un échec technique de l'agent — c'est un état métier
    légitime qui nécessite l'intervention interactive du professeur.
    """
    def __init__(
        self,
        exercise_id: uuid.UUID,
        unresolved_blocks: int = 0,
        questions_without_correction: int = 0,
        label_conflicts: int = 0,
        empty_sections: int = 0,
    ) -> None:
        self.exercise_id = exercise_id
        self.unresolved_blocks = unresolved_blocks
        self.questions_without_correction = questions_without_correction
        self.label_conflicts = label_conflicts
        self.empty_sections = empty_sections

        reasons = []
        if unresolved_blocks:
            reasons.append(f"{unresolved_blocks} bloc(s) de correction sans numéro identifiable")
        if questions_without_correction:
            reasons.append(f"{questions_without_correction} question(s) sans correction rattachée")
        if label_conflicts:
            reasons.append(f"{label_conflicts} conflit(s) de numérotation")
        if empty_sections:
            reasons.append(f"{empty_sections} section(s) sans aucune question")
        detail = "; ".join(reasons) if reasons else "structuration incomplète"

        super().__init__(
            f"Exercice {exercise_id} — structuration INCOMPLETE : {detail}"
        )


class ClassificationSchemaError(Exception):
    """
    La sortie LLM de classification (STATEMENT/CORRECTION/AUTRE) n'est pas
    conforme au schéma attendu après le retry métier unique.
    """
    def __init__(self, block_index: int, raw_response: str) -> None:
        self.block_index = block_index
        super().__init__(
            f"Bloc #{block_index} — classification LLM non conforme : {raw_response!r:.200}"
        )
