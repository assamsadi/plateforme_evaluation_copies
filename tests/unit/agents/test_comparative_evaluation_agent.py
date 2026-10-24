"""
Tests unitaires pour Comparative_Evaluation_Agent — sortie structurée
(2026-08-18) pour les 6 formes JSON attendues par _call_llm_json, remplaçant
l'ancien response_schema=None + regex JSON (même bug déjà trouvé et corrigé
sur 5 autres agents cette session). Un seul point d'appel centralisé
(_call_llm_json) : ces tests vérifient qu'il exige désormais response_schema
et gère aussi bien un dict brut (comme le renverrait un mock simple) qu'une
instance déjà validée du schéma (comme le fait réellement invoke_llm_with_
fallback en production).
"""
import uuid
from decimal import Decimal

import pytest

import app.agents.Comparative_Evaluation_Agent as cea_module
from app.agents.comparative_evaluation_exceptions import UnknownCorrectionModeError
from app.agents.context import AgentExecutionContext
from app.agents.Comparative_Evaluation_Agent import (
    ComparativeEvaluationAgent,
    CoherenceStatus,
    CriterionEvaluationInput,
    EvaluationRequest,
    StudentResponseInput,
    _BinaryChecklistSchema,
    _CoherenceCheckSchema,
    _CriteriaBasedSchema,
    _ProceduralSequenceSchema,
    _RubricLevelsSchema,
    _SolutionWorkedSchema,
    _SubquestionJudgmentsSchema,
)
from app.agents.Extraction_Verification_Agent import CorrectionMode

agent = ComparativeEvaluationAgent()
CONTEXT = AgentExecutionContext(trace_id="test-trace", flow_type="student_evaluation")


def _mock_llm(payload):
    """payload : soit un dict brut, soit déjà une instance du schéma attendu — les deux doivent marcher."""
    async def fake_invoke(task_type, messages, response_schema, context):
        result = payload if not isinstance(payload, dict) else payload
        fake_spec = type("S", (), {"provider": "groq", "model_name": "llama-3.3-70b"})()
        return result, fake_spec, False, {"total_tokens": 42}
    return fake_invoke


def _make_request(criteria: list[CriterionEvaluationInput]) -> EvaluationRequest:
    return EvaluationRequest(
        question_id=uuid.uuid4(),
        question_statement="Calculer l'aire du triangle.",
        student_response=StudentResponseInput(
            question_id=uuid.uuid4(), student_answer_text="Aire = 12 cm2.",
        ),
        criteria=criteria,
    )


@pytest.mark.anyio
async def test_call_llm_json_requires_response_schema_and_accepts_raw_dict(monkeypatch):
    """Le point d'appel central exige response_schema, et accepte un dict brut (model_validate)."""
    monkeypatch.setattr(
        cea_module, "invoke_llm_with_fallback",
        _mock_llm({"coherence_score": 0.8}),
    )
    parsed, model_version = await agent._call_llm_json(
        system_prompt="sys", user_prompt="user", ctx=CONTEXT, response_schema=_CoherenceCheckSchema,
    )
    assert isinstance(parsed, _CoherenceCheckSchema)
    assert parsed.coherence_score == 0.8
    assert "groq:llama-3.3-70b" in model_version


@pytest.mark.anyio
async def test_call_llm_json_injects_general_rules_into_system_prompt(monkeypatch):
    """
    2026-08-18 : les règles générales du barème (EvaluationRequest.
    general_rules) doivent être injectées dans le system_prompt envoyé au
    LLM, quel que soit le mode — vérifié en interceptant les `messages`
    réellement passés à invoke_llm_with_fallback.
    """
    captured = {}

    async def fake_invoke(task_type, messages, response_schema, context):
        captured["messages"] = messages
        fake_spec = type("S", (), {"provider": "groq", "model_name": "llama-3.3-70b"})()
        return {"coherence_score": 0.5}, fake_spec, False, {"total_tokens": 1}

    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", fake_invoke)
    await agent._call_llm_json(
        system_prompt="sys de base", user_prompt="user", ctx=CONTEXT,
        response_schema=_CoherenceCheckSchema,
        general_rules=["Toute réponse sans unité est refusée.", "Pénalité de -1 si retard."],
    )
    system_content = captured["messages"][0]["content"]
    assert "sys de base" in system_content
    assert "Toute réponse sans unité est refusée." in system_content
    assert "Pénalité de -1 si retard." in system_content


@pytest.mark.anyio
async def test_call_llm_json_no_general_rules_leaves_system_prompt_unchanged(monkeypatch):
    captured = {}

    async def fake_invoke(task_type, messages, response_schema, context):
        captured["messages"] = messages
        fake_spec = type("S", (), {"provider": "groq", "model_name": "llama-3.3-70b"})()
        return {"coherence_score": 0.5}, fake_spec, False, {"total_tokens": 1}

    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", fake_invoke)
    await agent._call_llm_json(
        system_prompt="sys de base", user_prompt="user", ctx=CONTEXT,
        response_schema=_CoherenceCheckSchema, general_rules=[],
    )
    assert captured["messages"][0]["content"] == "sys de base"


@pytest.mark.anyio
async def test_call_llm_json_accepts_already_validated_instance(monkeypatch):
    """Si invoke_llm_with_fallback renvoie déjà une instance du schéma (comportement réel), pas de double validation."""
    already_parsed = _CoherenceCheckSchema(coherence_score=0.42)
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm(already_parsed))
    parsed, _mv = await agent._call_llm_json(
        system_prompt="sys", user_prompt="user", ctx=CONTEXT, response_schema=_CoherenceCheckSchema,
    )
    assert parsed is already_parsed


# ---------------------------------------------------------------------------
# Les 6 modes — un test de câblage par mode : le bon schéma est utilisé, le
# résultat structuré est correctement transformé dans le dataclass métier.
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_mode1_solution_worked_wires_structured_output(monkeypatch):
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "student_steps": [
            {"step_ref": "s1", "order": 1, "description": "calcul", "justification": "ok",
             "depends_on_refs": [], "aligned_reference_step_ref": None, "is_locally_correct": True},
        ],
        "final_conclusion_value": None,
        "consigne_respected": None,
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c1", label="méthode", points=Decimal("5"), correction_mode=CorrectionMode.SOLUTION_WORKED,
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.SOLUTION_WORKED, crit, request, CONTEXT)
    assert len(result.step_judgments) == 1
    assert result.step_judgments[0].step_ref == "s1"
    assert result.step_judgments[0].is_locally_correct is True


@pytest.mark.anyio
async def test_mode2_criteria_based_wires_structured_output(monkeypatch):
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "condition_evaluations": [
            {"condition_text": "unité correcte", "satisfied": True, "justification": "cm2 présent", "confidence": 0.95},
            {"condition_text": "valeur correcte", "satisfied": False, "justification": "12 au lieu de 24", "confidence": 0.9},
        ],
        "overall_justification": "1/2 conditions satisfaites.",
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c2", label="exactitude", points=Decimal("3"), correction_mode=CorrectionMode.CRITERIA_BASED,
        verifiable_conditions=["unité correcte", "valeur correcte"],
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.CRITERIA_BASED, crit, request, CONTEXT)
    assert result.score_ratio == 0.5
    assert len(result.condition_evaluations) == 2
    assert result.condition_evaluations[0].satisfied is True
    assert result.condition_evaluations[1].satisfied is False


@pytest.mark.anyio
async def test_mode3_binary_checklist_makes_its_own_real_llm_judgment(monkeypatch):
    """
    2026-08-18 : BINARY_CHECKLIST fait désormais son propre jugement LLM
    (_BinaryChecklistSchema), plus une délégation à _eval_criteria_based.
    verifiable_conditions est TOUJOURS vide pour ce mode en production
    (garde-fou anti-biais côté Extraction_Verification_Agent, jamais
    peuplé ici non plus) -- si ce test passait encore via l'ancienne
    délégation, il retomberait dans le repli "aucune condition -> satisfait
    par défaut" et NE VERRAIT JAMAIS le mock ci-dessous répondre False. En
    laissant verifiable_conditions vide ET en mockant une réponse "non
    satisfait", ce test échouerait si la régression (délégation à
    _eval_criteria_based) était réintroduite.
    """
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "satisfied": False,
        "justification": "Aucun schéma n'est mentionné ni fourni dans la réponse transcrite.",
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c3", label="Représentation graphique du problème (schéma)",
        points=Decimal("1"), correction_mode=CorrectionMode.BINARY_CHECKLIST,
        verifiable_conditions=[],  # TOUJOURS vide en production pour ce mode, jamais peuplé ici.
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.BINARY_CHECKLIST, crit, request, CONTEXT)
    assert result.is_satisfied is False
    assert result.score_ratio == 0.0
    assert "schéma" in result.justification.lower()


@pytest.mark.anyio
async def test_mode3_binary_checklist_satisfied_case(monkeypatch):
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "satisfied": True, "justification": "Le résultat final P = 28 kN est clairement présenté.",
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c3b", label="Résultat final clairement présenté",
        points=Decimal("1"), correction_mode=CorrectionMode.BINARY_CHECKLIST,
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.BINARY_CHECKLIST, crit, request, CONTEXT)
    assert result.is_satisfied is True
    assert result.score_ratio == 1.0


@pytest.mark.anyio
async def test_mode4_multiple_distinct_answers_wires_coherence_schema(monkeypatch):
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({"coherence_score": 0.1}))
    crit = CriterionEvaluationInput(
        criterion_id="c4", label="alternative", points=Decimal("4"),
        correction_mode=CorrectionMode.MULTIPLE_DISTINCT_ANSWERS,
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.MULTIPLE_DISTINCT_ANSWERS, crit, request, CONTEXT)
    # coherence_score=0.1 < _COHERENCE_LOW_THRESHOLD (0.3) -> INCOHERENT, pas de clarification.
    assert result.coherence_status == CoherenceStatus.INCOHERENT
    assert result.clarification_request is None


@pytest.mark.anyio
async def test_mode5_rubric_levels_wires_structured_output(monkeypatch):
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "assigned_level": "Bon", "justification": "Méthode correcte, résultat partiellement exact.",
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c5", label="qualité", points=Decimal("5"), correction_mode=CorrectionMode.RUBRIC_LEVELS,
        rubric_levels=[{"level": "Excellent", "description": "x"}, {"level": "Bon", "description": "y"}],
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.RUBRIC_LEVELS, crit, request, CONTEXT)
    assert result.assigned_level == "Bon"


@pytest.mark.anyio
async def test_mode5_rubric_levels_score_ratio_reflects_level_position(monkeypatch):
    """
    Bug fixé (2026-08-18) : score_ratio restait au défaut 0.0 du dataclass,
    quel que soit le niveau assigné. Désormais calculé DÉTERMINISTE selon la
    position du niveau dans rubric_levels (index 0 = meilleur niveau -> 1.0),
    jamais redemandé au LLM. 3 niveaux, niveau du milieu assigné -> 0.5.
    """
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "assigned_level": "Bon", "justification": "Milieu de l'échelle.",
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c5b", label="qualité", points=Decimal("5"), correction_mode=CorrectionMode.RUBRIC_LEVELS,
        rubric_levels=[
            {"level": "Excellent", "description": "x"},
            {"level": "Bon", "description": "y"},
            {"level": "Insuffisant", "description": "z"},
        ],
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.RUBRIC_LEVELS, crit, request, CONTEXT)
    assert result.score_ratio == 0.5
    assert result.is_satisfied is False


@pytest.mark.anyio
async def test_mode5_rubric_levels_best_level_gives_full_ratio(monkeypatch):
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "assigned_level": "Excellent", "justification": "Meilleur niveau.",
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c5c", label="qualité", points=Decimal("5"), correction_mode=CorrectionMode.RUBRIC_LEVELS,
        rubric_levels=[
            {"level": "Excellent", "description": "x"},
            {"level": "Bon", "description": "y"},
            {"level": "Insuffisant", "description": "z"},
        ],
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.RUBRIC_LEVELS, crit, request, CONTEXT)
    assert result.score_ratio == 1.0
    assert result.is_satisfied is True


@pytest.mark.anyio
async def test_mode5_rubric_levels_unknown_assigned_level_defaults_to_zero(monkeypatch):
    """Garde-fou defensive — niveau assigné hors de rubric_levels : jamais deviné, score_ratio=0.0."""
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "assigned_level": "Niveau inconnu", "justification": "?",
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c5d", label="qualité", points=Decimal("5"), correction_mode=CorrectionMode.RUBRIC_LEVELS,
        rubric_levels=[{"level": "Excellent", "description": "x"}, {"level": "Bon", "description": "y"}],
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.RUBRIC_LEVELS, crit, request, CONTEXT)
    assert result.score_ratio == 0.0
    assert result.is_satisfied is False


@pytest.mark.anyio
async def test_mode6_procedural_sequence_wires_structured_output(monkeypatch):
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "step_presence": [
            {"step_name": "identifier les données", "present": True, "justification": "ok"},
            {"step_name": "appliquer la formule", "present": True, "justification": "ok"},
        ],
        "sequence_ordering": {"is_order_correct": True, "misplaced_steps": [], "justification": "ordre respecté"},
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c6", label="procédure", points=Decimal("3"), correction_mode=CorrectionMode.PROCEDURAL_SEQUENCE,
        expected_steps=["identifier les données", "appliquer la formule"],
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.PROCEDURAL_SEQUENCE, crit, request, CONTEXT)
    assert len(result.step_presence) == 2
    assert result.sequence_ordering.is_order_correct is True
    # Bug fixé (2026-08-18) : toutes les étapes présentes + ordre correct -> score_ratio=1.0.
    assert result.score_ratio == 1.0
    assert result.is_satisfied is True


@pytest.mark.anyio
async def test_mode6_procedural_sequence_score_ratio_missing_step(monkeypatch):
    """1 étape manquante sur 2, ordre correct -> presence_ratio=0.5, pas de pénalité d'ordre."""
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "step_presence": [
            {"step_name": "identifier les données", "present": True, "justification": "ok"},
            {"step_name": "appliquer la formule", "present": False, "justification": "absent"},
        ],
        "sequence_ordering": {"is_order_correct": True, "misplaced_steps": [], "justification": "n/a"},
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c6b", label="procédure", points=Decimal("3"), correction_mode=CorrectionMode.PROCEDURAL_SEQUENCE,
        expected_steps=["identifier les données", "appliquer la formule"],
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.PROCEDURAL_SEQUENCE, crit, request, CONTEXT)
    assert result.score_ratio == 0.5
    assert result.is_satisfied is False


@pytest.mark.anyio
async def test_mode6_procedural_sequence_score_ratio_wrong_order_penalty(monkeypatch):
    """
    Bug fixé (2026-08-18) : score_ratio n'était JAMAIS assigné (restait au
    défaut 0.0 du dataclass). Toutes les étapes présentes mais ordre
    incorrect -> pénalité multiplicative (x0.5, cf. docstring
    _eval_procedural_sequence), jamais un score écrasé à 0.0.
    """
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", _mock_llm({
        "step_presence": [
            {"step_name": "identifier les données", "present": True, "justification": "ok"},
            {"step_name": "appliquer la formule", "present": True, "justification": "ok"},
        ],
        "sequence_ordering": {
            "is_order_correct": False,
            "misplaced_steps": ["appliquer la formule"],
            "justification": "ordre inversé",
        },
    }))
    crit = CriterionEvaluationInput(
        criterion_id="c6c", label="procédure", points=Decimal("3"), correction_mode=CorrectionMode.PROCEDURAL_SEQUENCE,
        expected_steps=["identifier les données", "appliquer la formule"],
    )
    request = _make_request([crit])
    result = await agent._dispatch_criterion(CorrectionMode.PROCEDURAL_SEQUENCE, crit, request, CONTEXT)
    assert result.score_ratio == 0.5
    assert result.is_satisfied is False


@pytest.mark.anyio
async def test_unknown_correction_mode_raises_without_calling_llm(monkeypatch):
    """execute() : mode inconnu -> UnknownCorrectionModeError, jamais un repli silencieux, jamais d'appel LLM."""
    called = False

    async def fake_invoke(*args, **kwargs):
        nonlocal called
        called = True
        return {}, None, False, {}
    monkeypatch.setattr(cea_module, "invoke_llm_with_fallback", fake_invoke)

    crit = CriterionEvaluationInput(
        criterion_id="c7", label="?", points=Decimal("1"), correction_mode="not_a_real_mode",
    )
    request = _make_request([crit])
    with pytest.raises(UnknownCorrectionModeError):
        await agent.execute(request, CONTEXT)
    assert called is False
