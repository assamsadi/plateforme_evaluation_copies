"""
Utilitaires partagés pour OCR_Extraction_Agent v3 et les agents consommateurs.
Validation de schéma, score de confiance combiné, filtrage et agrégats bloc/élément.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.domain.models.assessment.extraction_correction import (
    ExtractionContentType,
    ExtractionOrigin,
    StructureType,
)
from app.domain.schemas.ocr_schemas import STRUCTURE_VALIDATORS
from app.domain.schemas.submission_schemas import RawExtractedBlock


def extract_latex_string(structured_content: dict | str | None, raw_text: str = "") -> str:
    """Normalise structured_content en chaîne LaTeX pour validation."""
    if isinstance(structured_content, str):
        return structured_content.strip()
    if isinstance(structured_content, dict):
        return (structured_content.get("latex") or raw_text or "").strip()
    return (raw_text or "").strip()


def validate_structure_content(
    structure_type: StructureType | None,
    structured_content: dict | str | None,
) -> bool:
    """Valide le JSON structured_content contre le schéma attendu pour structure_type."""
    if not isinstance(structured_content, dict):
        return False
    if structure_type is None:
        return False
    validator_cls = STRUCTURE_VALIDATORS.get(structure_type)
    if validator_cls is None:
        return False
    try:
        validator_cls.model_validate(structured_content)
        return True
    except PydanticValidationError:
        return False


def compute_combined_confidence(
    model_self_confidence: float,
    schema_valid: bool | None,
    reconstruction_confidence: float | None,
) -> float:
    """
    Combine les trois signaux de confiance en un score unique par zone.
    schema_valid=None signifie que la validation ne s'applique pas (TEXT, DIAGRAM).
    """
    scores = [model_self_confidence]
    if reconstruction_confidence is not None:
        scores.append(reconstruction_confidence)
    combined = min(scores)
    if schema_valid is False:
        combined = min(combined, 0.50)
    return combined


def compute_block_level_aggregates(
    content_type: ExtractionContentType,
    structured_content: dict | str | None,
    block_origin: ExtractionOrigin | None,
    block_is_struck_through: bool,
) -> tuple[ExtractionOrigin | None, bool]:
    """
    Calcule origin et is_struck_through agrégés au niveau bloc.
    Pour les blocs simples, retourne les valeurs telles quelles.
    Pour STRUCTURE, dérive des éléments internes si nécessaire.
    """
    if content_type != ExtractionContentType.STRUCTURE or not isinstance(structured_content, dict):
        return block_origin, block_is_struck_through

    origins: list[ExtractionOrigin] = []
    struck_flags: list[bool] = []

    for row in structured_content.get("rows", []):
        for cell in row.get("cells", []):
            origins.append(ExtractionOrigin(cell["origin"]))
            struck_flags.append(cell.get("is_struck_through", False))

    for field in structured_content.get("fields", []):
        origins.append(ExtractionOrigin(field.get("label_origin", "PRINTED")))
        if field.get("value_origin"):
            origins.append(ExtractionOrigin(field["value_origin"]))
        struck_flags.append(field.get("is_struck_through", False))

    for element in structured_content.get("elements", []):
        origins.append(ExtractionOrigin(element["origin"]))
        struck_flags.append(element.get("is_struck_through", False))

    for column in structured_content.get("columns", []):
        for item in column:
            origins.append(ExtractionOrigin(item["origin"]))
            struck_flags.append(item.get("is_struck_through", False))

    if not origins:
        return block_origin, block_is_struck_through

    aggregate_origin = (
        ExtractionOrigin.HANDWRITTEN
        if any(o == ExtractionOrigin.HANDWRITTEN for o in origins)
        else ExtractionOrigin.PRINTED
    )
    if block_is_struck_through:
        aggregate_struck = True
    elif struck_flags and all(struck_flags):
        aggregate_struck = True
    else:
        aggregate_struck = False

    return aggregate_origin, aggregate_struck


def should_emit_block_at_ocr_output(
    block: dict[str, Any], flow_type: str, treat_printed_as_content: bool = False,
) -> bool:
    """
    Filtrage à la source (v3 §4) : exclure les blocs TEXT/EQUATION origin=PRINTED —
    UNIQUEMENT côté étudiant (flow_type="student_evaluation"), où le texte imprimé
    est l'énoncé recopié sur la copie, sans intérêt pour la correction. Les STRUCTURE,
    DIAGRAM et éléments manuscrits passent toujours, quel que soit le flow_type.

    Côté professeur (flow_type="exercise_setup"), le texte imprimé EST le contenu
    principal à structurer (titres, numérotation de sous-questions, énoncé tapé à
    l'ordinateur) — le filtrer ici le supprime AVANT que Document_Structuring_Agent
    ne le voie, quoi que fasse filter_structuring_block en aval (cf. sa docstring,
    qui promet de ne jamais filtrer sur origin côté professeur — promesse qu'il ne
    peut pas tenir si le bloc a déjà disparu ici). Bug constaté en test réel : un
    document à 2 problèmes distincts (numérotés 1.1-7.2 puis à nouveau 1.1-7.2) était
    fusionné en une seule Question, faute des titres/numéros nécessaires pour les
    distinguer — aucun bloc TEXT+PRINTED ne survivait jusqu'à l'agent de structuration.
    Pas de valeur par défaut : force chaque appelant à passer context.flow_type
    explicitement plutôt que de deviner une valeur qui pourrait ne correspondre à
    aucun des deux flows réels (cf. AgentExecutionContext.flow_type).

    treat_printed_as_content (2026-09-03, cas réel zainabsebhi) : une copie
    ENTIÈREMENT tapée à l'ordinateur (pas un scan manuscrit) fait classer une
    grande partie de son texte en origin=PRINTED par l'agent vision — y
    compris le raisonnement réel de l'étudiant, indiscernable visuellement
    d'un énoncé recopié dès lors que rien ne permet de trancher à l'échelle
    de la page. Le filtre ci-dessus supprimait alors SILENCIEUSEMENT la
    quasi-totalité de la copie (aucune ExtractionCorrection persistée, aucune
    erreur de pipeline) — constaté sur une vraie soumission où 3 des 4 pages
    de contenu réel ont ainsi disparu sans trace, empêchant toute notation
    d'une des deux questions. Positionné à True par l'appelant (OCR_
    Extraction_Agent.execute) quand les blocs TEXT/EQUATION origin=PRINTED
    sont MAJORITAIRES sur l'ensemble de la soumission — un simple "zéro bloc
    HANDWRITTEN" s'est révélé trop strict (le modèle reste incohérent sur ce
    type de document : quelques paragraphes tapés obtiennent quand même
    HANDWRITTEN, sans raison visuelle distincte des autres, cf. cas réel).
    Une majorité PRINTED signale que le document lui-même est probablement
    tapé, alors qu'un simple écho d'énoncé sur une copie manuscrite classique
    n'en représente normalement qu'une petite minorité.
    """
    content_type = block["content_type"]
    origin = block.get("origin")
    if content_type in (ExtractionContentType.TEXT, ExtractionContentType.EQUATION):
        if flow_type == "exercise_setup" or treat_printed_as_content:
            return True
        return origin != ExtractionOrigin.PRINTED
    return True


def filter_consumer_block(block: RawExtractedBlock) -> RawExtractedBlock | None:
    """
    Filtrage à l'entrée des agents consommateurs (v3 §7).
    Retourne None si le bloc entier doit être exclu.
    Pour STRUCTURE, retourne une copie avec structured_output filtré élément par élément.
    """
    if block.content_type == ExtractionContentType.STRUCTURE:
        if not isinstance(block.structured_output, dict):
            return block
        filtered = filter_structure_elements(block.structured_output)
        if _structure_is_empty(filtered):
            return None
        return block.model_copy(update={"structured_output": filtered})

    if block.is_struck_through:
        return None
    return block


def filter_structuring_block(block: RawExtractedBlock) -> RawExtractedBlock | None:
    """
    Filtrage à l'entrée du Document_Structuring_Agent (côté professeur).

    Contrairement à filter_consumer_block (côté étudiant, où origin=PRINTED
    signifie "énoncé recopié sur la copie, à ignorer"), le contenu imprimé
    (origin=PRINTED) est ici le contenu principal à structurer — un document
    tapé à l'ordinateur (énoncé ou correction) ne doit JAMAIS être filtré.

    Ne retire que les blocs/éléments avec is_struck_through=True, jamais sur
    la base d'origin, quelle que soit sa valeur.
    """
    if block.content_type == ExtractionContentType.STRUCTURE:
        if not isinstance(block.structured_output, dict):
            return block
        filtered = filter_structure_elements_struck_only(block.structured_output)
        if _structure_is_empty(filtered):
            return None
        return block.model_copy(update={"structured_output": filtered})

    if block.is_struck_through:
        return None
    return block


def filter_structure_elements_struck_only(structured_output: dict) -> dict:
    """Retire uniquement les éléments internes barrés d'une STRUCTURE (conserve l'imprimé)."""
    result = dict(structured_output)

    if "rows" in result:
        filtered_rows = []
        for row in result["rows"]:
            cells = [
                c for c in row.get("cells", [])
                if not c.get("is_struck_through", False)
            ]
            if cells:
                filtered_rows.append({"cells": cells})
        result["rows"] = filtered_rows

    if "fields" in result:
        result["fields"] = [
            f for f in result["fields"]
            if not f.get("is_struck_through", False)
        ]

    if "elements" in result:
        kept_ids = {
            e["id"] for e in result["elements"]
            if not e.get("is_struck_through", False)
        }
        result["elements"] = [e for e in result["elements"] if e["id"] in kept_ids]
        result["relations"] = [
            r for r in result.get("relations", [])
            if r.get("from_id") in kept_ids and r.get("to_id") in kept_ids
        ]

    if "columns" in result:
        result["columns"] = [
            [
                item for item in column
                if not item.get("is_struck_through", False)
            ]
            for column in result["columns"]
        ]
        result["columns"] = [col for col in result["columns"] if col]

    return result


def filter_structure_elements(structured_output: dict) -> dict:
    """Retire les éléments internes barrés ou imprimés d'une STRUCTURE."""
    result = dict(structured_output)

    if "rows" in result:
        filtered_rows = []
        for row in result["rows"]:
            cells = [
                c for c in row.get("cells", [])
                if not c.get("is_struck_through", False)
                and c.get("origin") != ExtractionOrigin.PRINTED
            ]
            if cells:
                filtered_rows.append({"cells": cells})
        result["rows"] = filtered_rows

    if "fields" in result:
        result["fields"] = [
            f for f in result["fields"]
            if not f.get("is_struck_through", False)
            and f.get("value_origin") == ExtractionOrigin.HANDWRITTEN
        ]

    if "elements" in result:
        kept_ids = {
            e["id"] for e in result["elements"]
            if not e.get("is_struck_through", False)
            and e.get("origin") != ExtractionOrigin.PRINTED
        }
        result["elements"] = [e for e in result["elements"] if e["id"] in kept_ids]
        result["relations"] = [
            r for r in result.get("relations", [])
            if r.get("from_id") in kept_ids and r.get("to_id") in kept_ids
        ]

    if "columns" in result:
        result["columns"] = [
            [
                item for item in column
                if not item.get("is_struck_through", False)
                and item.get("origin") != ExtractionOrigin.PRINTED
            ]
            for column in result["columns"]
        ]
        result["columns"] = [col for col in result["columns"] if col]

    return result


def _structure_is_empty(structured_output: dict) -> bool:
    if structured_output.get("rows"):
        return not any(row.get("cells") for row in structured_output["rows"])
    if structured_output.get("fields"):
        return len(structured_output["fields"]) == 0
    if structured_output.get("elements"):
        return len(structured_output["elements"]) == 0
    if structured_output.get("columns"):
        return not any(structured_output["columns"])
    return True


def structure_to_flat_text(structured_output: dict | None) -> str:
    """Produit un texte plat à partir d'une STRUCTURE filtrée (pour embeddings / recherche)."""
    if not structured_output:
        return ""
    parts: list[str] = []
    for row in structured_output.get("rows", []):
        for cell in row.get("cells", []):
            parts.append(cell.get("content", ""))
    for field in structured_output.get("fields", []):
        if field.get("value"):
            parts.append(str(field["value"]))
    for element in structured_output.get("elements", []):
        parts.append(element.get("content", ""))
    for column in structured_output.get("columns", []):
        for item in column:
            parts.append(item.get("content", ""))
    return " ".join(p for p in parts if p)


def to_decimal_confidence(value: float) -> Decimal:
    return Decimal(str(round(value, 3)))


def sanitize_for_postgres_text(value):
    """
    Retire les octets NUL (0x00) d'un texte/structure OCR — l'encodage
    UTF8 de Postgres les rejette purement et simplement
    (asyncpg.exceptions.CharacterNotInRepertoireError : "invalid byte
    sequence for encoding UTF8: 0x00"), constaté en test réel sur du texte
    produit par le LLM vision (cause exacte non identifiée — image
    quasi vierge/corrompue, réponse tronquée...). Sans checkpoint entre
    l'OCR et la structuration (cf. docstring Document_Structuring_Agent),
    cette erreur faisait échouer TOUTE la tâche Celery, qui repart alors
    de zéro à chaque retry — gaspillant tout le quota LLM déjà consommé.
    Appliqué une seule fois, à la source (juste après l'OCR), pour ne
    jamais avoir à dupliquer ce nettoyage à chaque point de persistance
    en aval (TeacherCorrectionBlock, AgentDecisionLog...).
    """
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: sanitize_for_postgres_text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_postgres_text(v) for v in value]
    return value
