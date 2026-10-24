"""
Sonde dédiée — chaîne le barème "parfait" de step4b (les 7 correction_mode
d'un coup) avec une réponse d'étudiant SYNTHÉTIQUE mais réaliste, à travers
Comparative_Evaluation_Agent RÉEL. Objectif : valider RUBRIC_LEVELS/
PROCEDURAL_SEQUENCE en JUGEMENT LLM réel (score_ratio calculé sur une vraie
réponse, pas juste vérifié que l'extraction du barème fonctionne — déjà fait
par step4b).

Réponse d'étudiant construite pour donner un signal PARTIEL sur plusieurs
critères (jamais 100% ni 0% partout, pour vérifier la gradation réelle) :
  - criteria_based : mentionne 2 des 3 conditions explicitement (la 3e
    n'est qu'implicite, jamais nommée "contrainte admissible") -> attendu
    score_ratio ~0.67, pas 1.0.
  - procedural_sequence : les 4 étapes sont TOUTES présentes, mais l'étape
    3 (réactions d'appui) est écrite APRÈS l'étape 2 (diagramme du moment)
    alors que le diagramme nécessite les réactions -> ordre incorrect
    attendu, score_ratio ~0.5 (présence 1.0 x pénalité 0.5, cf. fix du jour).
  - rubric_levels : rédaction correcte mais sommaire, sans justification
    détaillée de chaque étape -> attendu "Satisfaisant", pas "Excellent".
  - multiple_distinct_answers : une méthode alternative est explicitement
    citée.
  - binary_checklist : schéma explicitement mentionné comme présent.
  - test_case_based : fonction Python fournie, cohérente avec la formule
    attendue (sigma_max = M*v/I) -> devrait passer les 2 cas de test.
  - solution_worked : démarche complète et correcte de bout en bout.

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step9b_test_comparative_evaluation_all_modes_probe_gemini.py
"""
import asyncio
import os
import sys
import time
import uuid
from collections import deque
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

import app.agents.Comparative_Evaluation_Agent as cea_module
import app.agents.Extraction_Verification_Agent as eva_module
from app.agents.context import AgentExecutionContext
from app.agents.Comparative_Evaluation_Agent import (
    ComparativeEvaluationAgent,
    CriterionEvaluationInput,
    EvaluationRequest,
    StudentResponseInput,
)
from app.agents.Extraction_Verification_Agent import (
    CorrectionBlockInput,
    ExtractionVerificationAgent,
    QuestionInput,
)
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from step4b_test_bareme_all_modes_probe_gemini import CORRECTION_TEXT, QUESTION_STATEMENT

GEMINI_MODEL_NAME = "gemini-flash-lite-latest"
MAX_RPM = 12

_call_timestamps: deque[float] = deque()


async def _rate_limit() -> None:
    while True:
        now = time.monotonic()
        while _call_timestamps and now - _call_timestamps[0] > 60:
            _call_timestamps.popleft()
        if len(_call_timestamps) < MAX_RPM:
            _call_timestamps.append(now)
            return
        await asyncio.sleep(60 - (now - _call_timestamps[0]) + 0.5)


async def _gemini_invoke_llm_with_fallback(task_type, messages, response_schema, context):
    from langchain_google_genai import ChatGoogleGenerativeAI

    await _rate_limit()
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL_NAME, google_api_key=os.environ["GOOGLE_API_KEY"], temperature=0.1,
    )
    if response_schema is not None:
        llm = llm.with_structured_output(response_schema)
    result = await llm.ainvoke(messages)
    fake_spec = SimpleNamespace(provider="gemini", model_name=GEMINI_MODEL_NAME)
    return result, fake_spec, False, {}


eva_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
cea_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback


STUDENT_ANSWER_TEXT = """1. Identification des charges et appuis : poutre simplement appuyée en A et B, charge répartie q sur toute la longueur.
2. Traçage du diagramme du moment fléchissant à partir de la répartition de charge.
3. Calcul des réactions d'appui : par équilibre global, R_A = 2500 N et R_B = 2500 N.
4. Identification du moment maximal et calcul de la contrainte : le moment fléchissant maximal calculé est M_max = 5000 N.m au centre de la poutre. On calcule ensuite sigma_max = M_max * v / I = 5000 * 0.05 / 0.0002 = 1 250 000 Pa, soit 1,25 MPa. Comme 1,25 MPa reste largement inférieur à la limite, le dimensionnement est valide.

Une autre approche aurait été d'utiliser directement les formulaires de RDM standards pour ce cas de charge, ce qui aurait donné le même résultat sans repasser par le diagramme du moment.

Schéma joint : poutre avec appuis A et B, charge répartie représentée, réactions indiquées aux appuis.

Fonction de vérification demandée :
def contrainte_max(M, I, v):
    return M * v / I
"""


async def main() -> None:
    context = AgentExecutionContext(
        trace_id=str(uuid.uuid4()), flow_type="student_evaluation", exercise_id=uuid.uuid4(),
    )
    question_id = uuid.uuid4()
    question = QuestionInput(question_id=question_id, order=1, statement=QUESTION_STATEMENT, section_order=1)
    block = CorrectionBlockInput(
        block_id=uuid.uuid4(), content_type=ExtractionContentType.TEXT, raw_text=CORRECTION_TEXT,
    )

    # --- Étape 1 (déjà validée par step4b) : extraction du barème réel ---
    extraction_agent = ExtractionVerificationAgent()
    verif_report = await extraction_agent.execute(
        questions=[question],
        blocks_by_question={question_id: [block]},
        exercise_status=ExerciseStatus.DRAFT,
        context=context,
    )
    qres = verif_report.questions[0]
    if qres.bareme is None:
        print("Aucun barème extrait — impossible de continuer.")
        return

    criteria = [
        CriterionEvaluationInput(
            criterion_id=c.id,
            label=c.label,
            points=c.points,
            correction_mode=c.correction_mode,
            verifiable_conditions=c.verifiable_conditions,
            test_cases=[tc.__dict__ for tc in c.test_cases] if c.test_cases else [],
            reference_code=c.reference_code,
            expected_complexity=c.expected_complexity,
            rubric_levels=c.rubric_levels,
            expected_steps=c.expected_steps,
        )
        for c in qres.bareme.criteria
    ]

    # --- Étape 2 (le vrai objet de ce test) : Comparative_Evaluation_Agent
    # RÉEL, sur une réponse d'étudiant synthétique construite pour un signal
    # PARTIEL (cf. docstring module). ---
    request = EvaluationRequest(
        question_id=question_id,
        question_statement=QUESTION_STATEMENT,
        student_response=StudentResponseInput(
            question_id=question_id,
            student_answer_text=STUDENT_ANSWER_TEXT,
            code_submission=STUDENT_ANSWER_TEXT,
        ),
        criteria=criteria,
        reference_solution_text=None,
        reasoning_graph_steps=[],
        general_rules=qres.general_rules,
    )

    eval_agent = ComparativeEvaluationAgent()
    report = await eval_agent.execute(request, context)

    print(f"=== Comparative_Evaluation_Agent : {len(report.criterion_results)} critère(s) évalué(s) ===\n")
    for res in report.criterion_results:
        print(f"[{res.correction_mode.value}] score_ratio={res.score_ratio} is_satisfied={res.is_satisfied} assigned_level={res.assigned_level}")
        print(f"    justification : {res.justification}")
        if res.sequence_ordering:
            print(f"    sequence_ordering : is_order_correct={res.sequence_ordering.is_order_correct} misplaced={res.sequence_ordering.misplaced_steps}")
        if res.step_presence:
            print(f"    step_presence : {[(sp.step_name, sp.present) for sp in res.step_presence]}")
        if res.test_case_results:
            print(f"    test_case_results ({res.execution_mode}) : {[(tr.passed, tr.visibility) for tr in res.test_case_results]}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
