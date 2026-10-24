"""
Sonde dédiée — Feedback_Agent (§7, "Feedback Intelligent"), SEUL agent du
pipeline student_evaluation qui appelle un LLM pour produire du texte
DESTINÉ À L'ÉTUDIANT (Competency_Assessment_Agent/Recommendation_Agent sont
des calculs déterministes purs, cf. leurs docstrings — pas de probe LLM
pertinente pour eux, testés à l'unité à la place, cf. test_recommendation_
agent.py).

Entrées 100% synthétiques mais réalistes (CompetencyFeedbackInput/
RecommendedExerciseInput sont de simples dataclasses, aucun accès DB requis
pour tester l'agent isolément) — construites pour vérifier concrètement :
  1. Le principe socratique (garde-fou _is_socratic : au moins un "?").
  2. Que le texte s'ancre RÉELLEMENT sur les strengths/weaknesses/
     identified_difficulties fournis (jamais une question générique).
  3. Que les exercices recommandés sont mentionnés naturellement en
     conclusion (jamais une liste plaquée).
  4. Le cas "aucune recommandation" (une 2e compétence sans exercice
     recommandé) — ne doit rien inventer.

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step11_test_feedback_agent_probe_gemini.py
"""
import asyncio
import os
import uuid
from decimal import Decimal

from dotenv import load_dotenv

load_dotenv()

import app.agents.Feedback_Agent as feedback_module
from app.agents.context import AgentExecutionContext
from app.agents.Feedback_Agent import (
    CompetencyFeedbackInput,
    FeedbackAgent,
    RecommendedExerciseInput,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode


async def _gemini_invoke_llm_with_fallback(task_type, messages, response_schema, context):
    from langchain_google_genai import ChatGoogleGenerativeAI
    from types import SimpleNamespace

    llm = ChatGoogleGenerativeAI(
        model="gemini-flash-lite-latest", google_api_key=os.environ["GOOGLE_API_KEY"], temperature=0.3,
    )
    result = await llm.ainvoke(messages)
    fake_spec = SimpleNamespace(provider="gemini", model_name="gemini-flash-lite-latest")
    return result, fake_spec, False, {}


feedback_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback


COMPETENCIES = [
    CompetencyFeedbackInput(
        competency=C2PCTSkillCode.DATA_AND_PLANNING,
        mastery_level=Decimal("45.0"),
        trend="DECLINING",
        strengths=["A correctement listé toutes les données numériques de l'énoncé (diamètre, élancement)."],
        weaknesses=["1.5 (Identifier les données manquantes, à calculer)"],
        identified_difficulties=[
            "N'a jamais mentionné la contrainte admissible du matériau, pourtant nécessaire à la conclusion.",
        ],
    ),
    CompetencyFeedbackInput(
        competency=C2PCTSkillCode.ALGORITHMIC_STRUCTURING,
        mastery_level=Decimal("90.0"),
        trend="STABLE",
        strengths=["Démarche de résolution en 4 étapes claires et dans l'ordre logique attendu."],
        weaknesses=[],
        identified_difficulties=[],
    ),
]

# Une seule recommandation, uniquement pour la compétence faible — la 2e
# compétence (déjà maîtrisée) ne doit JAMAIS se voir inventer un exercice.
RECOMMENDATIONS = [
    RecommendedExerciseInput(
        exercise_title="Exercice bibliothèque - identification de données manquantes",
        competency=C2PCTSkillCode.DATA_AND_PLANNING,
        reason="Faiblesse persistante en data_and_planning (maîtrise 45.0%) — exercice de remédiation, niveau facile.",
    ),
]


async def main() -> None:
    context = AgentExecutionContext(
        trace_id=str(uuid.uuid4()), flow_type="student_evaluation",
        submission_id=uuid.uuid4(), exercise_id=uuid.uuid4(),
    )
    agent = FeedbackAgent()
    report = await agent.generate_feedback(
        student_id=uuid.uuid4(),
        submission_id=uuid.uuid4(),
        competencies=COMPETENCIES,
        recommendations=RECOMMENDATIONS,
        ctx=context,
    )

    print("=== Feedback_Agent : texte généré ===\n")
    print(report.feedback_text)
    print()

    print("=== Vérifications ===")
    print(f"Contient au moins un '?' (garde-fou _is_socratic) : {'?' in report.feedback_text}")
    print(f"Mentionne la force réelle (contrainte/diamètre/élancement listés) : "
          f"{any(k in report.feedback_text.lower() for k in ['diamètre', 'élancement', 'donnée'])}")
    print(f"Mentionne l'exercice recommandé : "
          f"{'identification de données manquantes' in report.feedback_text.lower()}")
    print(f"competencies_addressed : {[c.value for c in report.competencies_addressed]}")


if __name__ == "__main__":
    asyncio.run(main())
