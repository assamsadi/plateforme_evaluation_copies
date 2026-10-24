"""
Sonde pour Comparative_Evaluation_Agent — premier test réel du fix du
2026-08-18 (sortie structurée dans _call_llm_json, 6 modes couverts par une
seule correction). Chaîne complète, réelle, aucune donnée inventée :

  1. document.pdf (professeur, déjà en cache) -> Document_Structuring_Agent
     -> Extraction_Verification_Agent, comme step6/7/8 — produit à la fois
     les steps de référence ET un VRAI barème structuré (BaremeResult,
     déjà observé "bareme_detailed: 1" sur tous les runs précédents de ce
     document). C'est CE barème, jamais un critère inventé à la main, qui
     alimente EvaluationRequest.criteria (BaremeCriterionProposal mappé
     champ à champ vers CriterionEvaluationInput).
  2. copie1_raw_blocks_dump.json (étudiant, déjà en cache depuis step7/8,
     aucun nouvel appel OCR) — combiné en un seul texte de réponse.
  3. ComparativeEvaluationAgent.execute(), RÉEL et INCHANGÉ dans ce script
     (le fix est dans app/agents/Comparative_Evaluation_Agent.py lui-même).

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step9_test_comparative_evaluation_probe_gemini.py
"""
import asyncio
import json
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
import app.agents.Document_Structuring_Agent as dsa_module
import app.agents.Extraction_Verification_Agent as eva_module
from app.agents.context import AgentExecutionContext
from app.agents.Comparative_Evaluation_Agent import (
    ComparativeEvaluationAgent,
    CriterionEvaluationInput,
    EvaluationRequest,
    StudentResponseInput,
)
from app.agents.Extraction_Verification_Agent import CorrectionBlockInput, QuestionInput
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.schemas.submission_schemas import RawExtractedBlock
from app.observability.langfuse import AgentTraceSpan
from step3_test_document_structuring_probe import _load_raw_blocks

GEMINI_MODEL_NAME = "gemini-flash-lite-latest"
MAX_RPM = 12

COPIE_DUMP_PATH = Path(__file__).resolve().parent / "copie1_raw_blocks_dump.json"

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


class _FakeProvider(str):
    """Cf. step7/8 — réplique ModelProvider (str + .value)."""
    @property
    def value(self) -> str:
        return str(self)


async def _gemini_invoke_llm_with_fallback(task_type, messages, response_schema, context):
    from langchain_google_genai import ChatGoogleGenerativeAI

    await _rate_limit()
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL_NAME, google_api_key=os.environ["GOOGLE_API_KEY"], temperature=0.1,
    )
    if response_schema is not None:
        llm = llm.with_structured_output(response_schema)
    result = await llm.ainvoke(messages)
    fake_spec = SimpleNamespace(provider=_FakeProvider("gemini"), model_name=GEMINI_MODEL_NAME)
    return result, fake_spec, False, {}


dsa_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
eva_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
cea_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback


def _combine_block_text(blocks: list[CorrectionBlockInput]) -> str:
    """Réplique exacte de ExtractionVerificationService._combine_block_text."""
    return "\n".join(b.raw_text for b in blocks if b.raw_text)


def _load_student_answer_text() -> str:
    if not COPIE_DUMP_PATH.exists():
        print(f"{COPIE_DUMP_PATH} introuvable — relancer step7 d'abord.")
        sys.exit(1)
    payload = json.loads(COPIE_DUMP_PATH.read_text(encoding="utf-8"))
    blocks = [RawExtractedBlock.model_validate(b) for b in payload["blocks"]]
    return "\n".join(b.prediction_ocr for b in blocks if b.prediction_ocr)


async def main() -> None:
    trace_id = str(uuid.uuid4())
    with AgentTraceSpan(
        "test_pipeline_step9", trace_id=trace_id,
        metadata={"script": "step9_test_comparative_evaluation_probe_gemini"},
    ):
        await _run_pipeline(trace_id=trace_id)


async def _run_pipeline(trace_id: str) -> None:
    # --- Étapes 1-2 (déjà validées, réplique exacte de step6/7/8) ---
    raw_blocks = _load_raw_blocks(pages=None)
    print(f"--- {len(raw_blocks)} bloc(s) OCR professeur (document.pdf, en cache) ---\n")

    context = AgentExecutionContext(
        trace_id=trace_id, flow_type="exercise_setup", exercise_id=uuid.uuid4(),
    )
    structuring_agent = dsa_module.DocumentStructuringAgent()
    structuring_report = await structuring_agent.execute(
        raw_blocks=raw_blocks, exercise_status=ExerciseStatus.DRAFT, context=context,
    )
    if not structuring_report.questions_created:
        print("Aucune question créée côté professeur — impossible de continuer.")
        return

    order_to_id = {q["order"]: uuid.uuid4() for q in structuring_report.questions_created}
    questions = [
        QuestionInput(
            question_id=order_to_id[q["order"]], order=q["order"],
            statement=q["statement"], section_order=q["section_order"],
        )
        for q in structuring_report.questions_created
    ]
    blocks_by_question: dict[uuid.UUID, list[CorrectionBlockInput]] = {qid: [] for qid in order_to_id.values()}
    for c in structuring_report.correction_blocks_created:
        if c["question_order"] is None:
            continue
        qid = order_to_id.get(c["question_order"])
        if qid is None:
            continue
        content_type = c["content_type"]
        if not isinstance(content_type, ExtractionContentType):
            content_type = ExtractionContentType(content_type)
        blocks_by_question[qid].append(CorrectionBlockInput(
            block_id=uuid.uuid4(), content_type=content_type, raw_text=c["raw_text"],
            structured_content=c["structured_content"], evidence_level=c["evidence_level"],
        ))

    verification_agent = eva_module.ExtractionVerificationAgent()
    verif_report = await verification_agent.execute(
        questions=questions, blocks_by_question=blocks_by_question,
        exercise_status=ExerciseStatus.DRAFT, context=context,
    )

    # --- Étape 3 (nouvelle) : construire EvaluationRequest à partir de
    # données 100% réelles — AUCUN critère inventé à la main. ---
    qres = verif_report.questions[0]
    print(f"decomposition_error : {qres.decomposition_error}")
    if qres.decomposition_error is not None:
        print("-> décomposition Agent 4 en échec, impossible de continuer.")
        return
    if qres.bareme is None:
        print(f"-> aucun barème structuré disponible (bareme_error={qres.bareme_error!r}), impossible de continuer.")
        return

    print(f"--- Barème RÉEL ({qres.bareme.case}, {qres.bareme.total_points} points, {len(qres.bareme.criteria)} critère(s)) ---")
    print(f"--- Règles générales RÉELLES ({len(qres.general_rules)}) --- ")
    for rule in qres.general_rules:
        print(f"    - {rule}")
    print()
    criteria: list[CriterionEvaluationInput] = []
    for c in qres.bareme.criteria:
        print(f"    [{c.correction_mode.value}] {c.label} ({c.points} pts) — id={c.id}")
        criteria.append(CriterionEvaluationInput(
            criterion_id=c.id,
            label=c.label,
            points=c.points,
            correction_mode=c.correction_mode,
            verifiable_conditions=c.verifiable_conditions,
            test_cases=[tc.__dict__ for tc in c.test_cases] if c.test_cases else [],
            reference_code=c.reference_code,
            expected_complexity=c.expected_complexity,
            # Extraction_Verification_Agent extrait désormais réellement ces
            # 2 champs (2026-08-18) — jusqu'ici absents de BaremeCriterionProposal,
            # donc RUBRIC_LEVELS/PROCEDURAL_SEQUENCE recevaient toujours une
            # liste vide ici peu importe le barème réel.
            rubric_levels=c.rubric_levels,
            expected_steps=c.expected_steps,
        ))
    print()

    reasoning_graph_steps = [
        {
            "step_ref": s.step_ref, "order": s.order, "step_type": str(s.step_type),
            "description": s.description, "formula": s.formula, "canonical_form": s.canonical_form,
        }
        for s in qres.steps
    ]

    question_stmt = next(q.statement for q in questions if q.question_id == qres.question_id)
    reference_content = _combine_block_text(blocks_by_question.get(qres.question_id, []))
    student_answer_text = _load_student_answer_text()
    print(f"--- Réponse étudiante réelle ({len(student_answer_text)} car., copie1.jpg) ---")
    print(f"    {student_answer_text[:300]!r}...\n")

    # Calcul de note classique (ticket dédié) — même garde-fou que
    # comparative_evaluation_node.py : covered_subquestions n'est transmis à
    # l'agent QUE si cette question a réellement un barème C2PCT natif
    # chiffré (subquestion_points). Sans ce garde-fou ici, cette sonde
    # rejouerait l'ancien comportement (15 subquestion_judgments gaspillés
    # sur un barème classique) et ne testerait plus le comportement réel du
    # pipeline.
    print(f"--- subquestion_points RÉELS : {qres.subquestion_points} ---\n")
    covered_subquestions_for_scoring = qres.covered_subquestions if qres.subquestion_points else []

    request = EvaluationRequest(
        question_id=qres.question_id,
        question_statement=question_stmt,
        student_response=StudentResponseInput(
            question_id=qres.question_id, student_answer_text=student_answer_text,
        ),
        criteria=criteria,
        reference_solution_text=reference_content,
        reasoning_graph_steps=reasoning_graph_steps,
        mandated_method=qres.mandated_method,
        covered_subquestions=covered_subquestions_for_scoring,
        general_rules=qres.general_rules,
    )

    # --- Étape 4 (le vrai objet de ce test) : Comparative_Evaluation_Agent
    # RÉEL avec la sortie structurée (fix du 2026-08-18) ---
    agent = ComparativeEvaluationAgent()
    report = await agent.execute(request, context)

    print(f"=== Comparative_Evaluation_Agent : {len(report.criterion_results)} critère(s) évalué(s) ===\n")
    for res in report.criterion_results:
        print(f"  [{res.correction_mode.value}] critère={res.criterion_id}")
        print(f"      is_satisfied={res.is_satisfied} score_ratio={res.score_ratio} assigned_level={res.assigned_level}")
        print(f"      confidence={res.confidence_score}")
        print(f"      justification : {res.justification}")
        if res.step_judgments:
            print(f"      step_judgments ({len(res.step_judgments)}) :")
            for j in res.step_judgments:
                print(
                    f"        - [{j.step_ref}] order={j.order} correct={j.is_locally_correct} "
                    f"carries_forward_error={j.carries_forward_error} aligned_ref={j.aligned_reference_step_ref}"
                )
                print(f"          justification: {j.justification}")
        if res.clarification_request:
            print(f"      clarification : {res.clarification_request.agent_question}")
        print()

    print(f"overall_confidence : {report.overall_confidence:.3f}")
    print(f"subquestion_judgments : {len(report.subquestion_judgments)}")
    for sq in report.subquestion_judgments:
        print(
            f"  - {sq.subquestion_id} : addressed={sq.addressed} is_correct={sq.is_correct} "
            f"completion_ratio={sq.completion_ratio} source={sq.source}"
        )
    print(f"decision_entries : {len(report.decision_entries)}")
    for de in report.decision_entries:
        print(f"  - [{de.decision}] {de.subquestion_id} ({de.competency.value}) : {de.reason}")


if __name__ == "__main__":
    asyncio.run(main())
