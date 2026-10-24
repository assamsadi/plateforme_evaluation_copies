"""
Tests unitaires pour Feedback_Agent — non-régression du bug trouvé sur test
réel (2026-08-18, sonde step11) : result.content peut être une LISTE de
blocs (certains clients LangChain, ex. ChatGoogleGenerativeAI, renvoient une
réponse multi-parties) plutôt qu'une chaîne — .strip() plantait dessus
(AttributeError). Aucun fichier de test n'existait pour cet agent avant ce
ticket (vérifié via Glob).
"""
import uuid
from types import SimpleNamespace

import pytest

import app.agents.Feedback_Agent as feedback_module
from app.agents.context import AgentExecutionContext
from app.agents.Feedback_Agent import FeedbackAgent

agent = FeedbackAgent()
CONTEXT = AgentExecutionContext(trace_id="test-trace", flow_type="student_evaluation")


def _mock_invoke(content):
    async def fake_invoke(task_type, messages, response_schema, context):
        fake_spec = SimpleNamespace(provider="gemini", model_name="gemini-flash-lite-latest")
        return SimpleNamespace(content=content), fake_spec, False, {}
    return fake_invoke


@pytest.mark.anyio
async def test_call_llm_handles_plain_string_content(monkeypatch):
    monkeypatch.setattr(feedback_module, "invoke_llm_with_fallback", _mock_invoke("Une question ? Oui."))
    result = await agent._call_llm([{"role": "user", "content": "x"}], CONTEXT)
    assert result == "Une question ? Oui."


@pytest.mark.anyio
async def test_call_llm_handles_list_of_dict_parts(monkeypatch):
    """Cas réel rencontré (ChatGoogleGenerativeAI) : content = liste de blocs {"type": "text", "text": "..."}."""
    monkeypatch.setattr(
        feedback_module, "invoke_llm_with_fallback",
        _mock_invoke([{"type": "text", "text": "Première partie. "}, {"type": "text", "text": "Deuxième partie ?"}]),
    )
    result = await agent._call_llm([{"role": "user", "content": "x"}], CONTEXT)
    assert result == "Première partie. Deuxième partie ?"


@pytest.mark.anyio
async def test_call_llm_handles_list_of_plain_strings(monkeypatch):
    monkeypatch.setattr(feedback_module, "invoke_llm_with_fallback", _mock_invoke(["Partie 1. ", "Partie 2 ?"]))
    result = await agent._call_llm([{"role": "user", "content": "x"}], CONTEXT)
    assert result == "Partie 1. Partie 2 ?"


@pytest.mark.anyio
async def test_generate_feedback_retries_once_when_not_socratic(monkeypatch):
    """Garde-fou _is_socratic — texte sans "?" -> un seul retry, puis utilisé tel quel (jamais bloquant)."""
    call_count = {"n": 0}

    async def fake_invoke(task_type, messages, response_schema, context):
        call_count["n"] += 1
        fake_spec = SimpleNamespace(provider="gemini", model_name="gemini-flash-lite-latest")
        # Jamais socratique, même après retry -> vérifie qu'un seul retry est tenté (2 appels max).
        return SimpleNamespace(content="Texte sans point d'interrogation."), fake_spec, False, {}

    monkeypatch.setattr(feedback_module, "invoke_llm_with_fallback", fake_invoke)
    report = await agent.generate_feedback(
        student_id=uuid.uuid4(), submission_id=uuid.uuid4(),
        competencies=[], recommendations=[], ctx=CONTEXT,
    )
    assert call_count["n"] == 2  # 1 appel initial + 1 retry, jamais plus
    assert report.feedback_text == "Texte sans point d'interrogation."  # utilisé quand même, jamais bloquant
