"""
Sonde dédiée — ferme la chaîne complète du calcul de note classique (ticket
dédié) : reprend EXACTEMENT le scénario de step9b (barème à 7 modes de
step4b + réponse d'étudiant synthétique), puis ajoute l'étape jusqu'ici
jamais testée en réel : Pedagogical_Evaluation_Agent.evaluate_question_
classic() + build_question_report_classic(), pour voir une VRAIE note
classique sortir sur un cas réel (LLM réel, calcul déterministe réel).

La jointure bareme.criteria x report.criterion_results (par id/criterion_id)
réplique exactement ce que fait comparative_evaluation_node.py — pur
assemblage de données, aucune logique de calcul ici (cf. son docstring).

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step10_test_pedagogical_evaluation_classic_probe_gemini.py
"""
import asyncio
import os
import sys
import time
import uuid
from collections import deque
from decimal import Decimal
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
from app.agents.Pedagogical_Evaluation_Agent import (
    ClassicCriterionJoinedInput,
    ClassicQuestionEvaluationInput,
    PedagogicalEvaluationAgent,
)
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from step4b_test_bareme_all_modes_probe_gemini import CORRECTION_TEXT, QUESTION_STATEMENT
from step9b_test_comparative_evaluation_all_modes_probe_gemini import STUDENT_ANSWER_TEXT

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

    criteria_input = [
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

    # --- Étape 2 (déjà validée par step9b) : Comparative_Evaluation_Agent réel ---
    request = EvaluationRequest(
        question_id=question_id,
        question_statement=QUESTION_STATEMENT,
        student_response=StudentResponseInput(
            question_id=question_id,
            student_answer_text=STUDENT_ANSWER_TEXT,
            code_submission=STUDENT_ANSWER_TEXT,
        ),
        criteria=criteria_input,
        reference_solution_text=None,
        reasoning_graph_steps=[],
        general_rules=qres.general_rules,
    )
    eval_agent = ComparativeEvaluationAgent()
    report = await eval_agent.execute(request, context)

    # --- Étape 3 (le vrai objet de ce test) : jointure bareme.criteria x
    # criterion_results (même logique que comparative_evaluation_node.py),
    # puis Pedagogical_Evaluation_Agent.evaluate_question_classic() RÉEL,
    # calcul déterministe pur (aucun appel LLM ici). ---
    results_by_id = {r.criterion_id: r for r in report.criterion_results}
    classic_criteria = [
        ClassicCriterionJoinedInput(
            criterion_id=c.id,
            label=c.label,
            correction_mode=c.correction_mode.value,
            points=c.points,
            disqualifying=c.disqualifying,
            score_ratio=results_by_id[c.id].score_ratio,
            is_satisfied=results_by_id[c.id].is_satisfied,
            justification=results_by_id[c.id].justification,
        )
        for c in qres.bareme.criteria
    ]
    classic_input = ClassicQuestionEvaluationInput(question_id=question_id, criteria=classic_criteria)

    pedagogical_agent = PedagogicalEvaluationAgent()
    score_result = pedagogical_agent.evaluate_question_classic(classic_input)
    question_report = pedagogical_agent.build_question_report_classic(
        question_id=question_id,
        bareme_points=qres.bareme.total_points,
        score_result=score_result,
    )

    print(f"=== Pedagogical_Evaluation_Agent (calcul classique) ===\n")
    for c in score_result.criterion_scores:
        print(
            f"  [{c.correction_mode}] {c.label} : {c.points_possible} pts possibles x "
            f"score_ratio={c.score_ratio} = {c.points_awarded} pts obtenus (is_satisfied={c.is_satisfied})"
        )
    print(f"\ndisqualified : {score_result.disqualified}")
    print(f"TOTAL_SCORE : {score_result.total_score} / {qres.bareme.total_points}")

    print(f"\n=== QuestionReport (copy_report) ===")
    print(f"note : {question_report.note}")
    print(f"bareme_points : {question_report.bareme_points}")
    for line in question_report.criterion_lines:
        print(f"  - {line.label} ({line.correction_mode}) : {line.points_awarded}/{line.points_possible}")

    # Vérification indépendante — même formule, calculée ici en Python pur
    # (Decimal), pour confirmer que le total affiché est bien Σ(points x ratio).
    manual_total = sum(
        (Decimal(str(c.points)) * Decimal(str(results_by_id[c.id].score_ratio))).quantize(Decimal("0.01"))
        for c in qres.bareme.criteria
    )
    print(f"\nVérification manuelle (Σ points x score_ratio, arrondi par critère) : {manual_total}")
    print(f"Concorde avec total_score de l'agent : {manual_total == score_result.total_score or score_result.disqualified}")


if __name__ == "__main__":
    asyncio.run(main())
