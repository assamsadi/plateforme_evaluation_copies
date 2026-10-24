"""
Tests unitaires pour Extraction_Verification_Agent — garde-fou anti-biais
sur BaremeCriterionProposal.rubric_levels/expected_steps (ticket calcul de
note classique, 2026-08-18) : ces 2 champs n'existaient pas du tout avant
ce fix (RUBRIC_LEVELS/PROCEDURAL_SEQUENCE recevaient toujours une liste
vide, quel que soit le texte du barème réel). Couvre uniquement
_criterion_from_schema (calcul pur, aucun appel LLM) — le reste de l'agent
(extraction LLM elle-même) n'a pas de test dédié dans ce fichier (vérifié
via Glob, aucun fichier de test n'existait pour cet agent avant ce ticket).
"""
from app.agents.Extraction_Verification_Agent import (
    CorrectionMode,
    ExtractionVerificationAgent,
    _BaremeCriterionSchema,
    _RubricLevelSchema,
)


def _schema(
    correction_mode: str,
    rubric_levels: list[_RubricLevelSchema] | None = None,
    expected_steps: list[str] | None = None,
) -> _BaremeCriterionSchema:
    return _BaremeCriterionSchema(
        label="critère",
        points=1.0,
        correction_mode=correction_mode,
        rubric_levels=rubric_levels or [],
        expected_steps=expected_steps or [],
    )


def test_rubric_levels_kept_when_mode_is_rubric_levels():
    schema = _schema(
        "rubric_levels",
        rubric_levels=[
            _RubricLevelSchema(level="Excellent", description="Tout est correct."),
            _RubricLevelSchema(level="Insuffisant", description="Rien n'est correct."),
        ],
    )
    proposal = ExtractionVerificationAgent._criterion_from_schema(schema)
    assert proposal.rubric_levels == [
        {"level": "Excellent", "description": "Tout est correct."},
        {"level": "Insuffisant", "description": "Rien n'est correct."},
    ]
    assert proposal.expected_steps == []


def test_rubric_levels_forced_empty_for_other_modes():
    """Garde-fou anti-biais — même si le LLM renvoie des niveaux, ils sont ignorés hors RUBRIC_LEVELS."""
    schema = _schema(
        "criteria_based",
        rubric_levels=[_RubricLevelSchema(level="Excellent", description="x")],
    )
    proposal = ExtractionVerificationAgent._criterion_from_schema(schema)
    assert proposal.rubric_levels == []


def test_expected_steps_kept_when_mode_is_procedural_sequence():
    schema = _schema(
        "procedural_sequence",
        expected_steps=["identifier les données", "appliquer la formule"],
    )
    proposal = ExtractionVerificationAgent._criterion_from_schema(schema)
    assert proposal.expected_steps == ["identifier les données", "appliquer la formule"]
    assert proposal.rubric_levels == []


def test_expected_steps_forced_empty_for_other_modes():
    """Garde-fou anti-biais — même si le LLM renvoie des étapes, elles sont ignorées hors PROCEDURAL_SEQUENCE."""
    schema = _schema(
        "solution_worked",
        expected_steps=["une étape hallucinée"],
    )
    proposal = ExtractionVerificationAgent._criterion_from_schema(schema)
    assert proposal.expected_steps == []


def test_neither_field_populated_for_unrelated_mode():
    schema = _schema("binary_checklist")
    proposal = ExtractionVerificationAgent._criterion_from_schema(schema)
    assert proposal.rubric_levels == []
    assert proposal.expected_steps == []
    assert proposal.correction_mode == CorrectionMode.BINARY_CHECKLIST
