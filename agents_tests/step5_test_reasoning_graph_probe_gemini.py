"""
Sonde pour Reasoning_Graph_Agent v2 — le nœud suivant dans le pipeline réel
après extraction_verification_node (cf. app/graph/pipeline_graph.py +
routing.py : extraction_verification_node -> reasoning_graph_node ->
solution_variant_generation_node). Chaîne les TROIS vraies classes de
production, jamais dupliquées : DocumentStructuringAgent ->
ExtractionVerificationAgent -> ReasoningGraphAgent, sur les vraies pages OCR
déjà extraites.

Reproduit la transformation réelle de production APRÈS le refactor v2 (cf.
app/services/reasoning_graph_service.py::build_graph_for_variant) :
Reasoning_Graph_Agent ne reparse plus le texte brut — il reçoit directement
les steps DÉJÀ décomposés par Extraction_Verification_Agent (qres.steps,
de vraies ReasoningStepOutput) convertis en ExistingStepInput, et enrichit
UNIQUEMENT les dépendances/is_core_step/tools_used/concept_tags. En
production ces steps viendraient de la table ReasoningStep déjà persistée
(step_id = str(ReasoningStep.id)) ; ce script, qui ne touche pas la DB,
utilise directement les step_ref d'Agent 4 ("s1", "s2"...) comme step_id —
identifiant opaque, aucune différence de comportement pour l'agent.

Pourquoi ce changement (cf. mémoire de session, refactor v2) : la v1
reparsait le texte source indépendamment d'Agent 4, ce qui causait une perte
de données active — les ReasoningStep d'Agent 4 (avec canonical_form/
dimensional_check_result) étaient supersédés par la seconde passe d'Agent 5
(qui ne portait jamais ces signaux), les perdant avant qu'ils n'atteignent
Comparative_Evaluation_Agent. La v2 élimine aussi source_coverage_ratio :
plus de redécouverte de texte, donc plus rien à "manquer" structurellement.

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step5_test_reasoning_graph_probe_gemini.py [pages]

Ex. pages 1 à 10 :

    .venv/Scripts/python.exe agents_tests/step5_test_reasoning_graph_probe_gemini.py 1,2,3,4,5,6,7,8,9,10

Sans argument : document entier.
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

import app.agents.Document_Structuring_Agent as dsa_module
import app.agents.Extraction_Verification_Agent as eva_module
import app.agents.Reasoning_Graph_Agent as rga_module
from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import CorrectionBlockInput, QuestionInput
from app.agents.Reasoning_Graph_Agent import ExistingStepInput
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from step3_test_document_structuring_probe import _load_raw_blocks

GEMINI_MODEL_NAME = "gemini-flash-lite-latest"
MAX_RPM = 12  # marge sous les ~15 RPM annoncés pour la famille flash-lite

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
        model=GEMINI_MODEL_NAME,
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.1,
    )
    if response_schema is not None:
        llm = llm.with_structured_output(response_schema)
    result = await llm.ainvoke(messages)
    fake_spec = SimpleNamespace(provider="gemini", model_name=GEMINI_MODEL_NAME)
    return result, fake_spec, False, {}


# Monkeypatch des références importées dans CHAQUE module d'agent — jamais les fichiers source.
dsa_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
eva_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
rga_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback


async def main(pages: set[int] | None) -> None:
    raw_blocks = _load_raw_blocks(pages=pages)
    scope = f"pages {sorted(pages)}" if pages is not None else "document entier"
    print(f"--- {len(raw_blocks)} bloc(s) OCR ({scope}) — via Gemini ({GEMINI_MODEL_NAME}, {MAX_RPM} RPM max) ---\n")

    context = AgentExecutionContext(
        trace_id=str(uuid.uuid4()), flow_type="exercise_setup", exercise_id=uuid.uuid4(),
    )

    # --- Étape 1 (déjà validée) : Document_Structuring_Agent, réel, inchangé ---
    structuring_agent = dsa_module.DocumentStructuringAgent()
    structuring_report = await structuring_agent.execute(
        raw_blocks=raw_blocks, exercise_status=ExerciseStatus.DRAFT, context=context,
    )
    print(
        f"--- Document_Structuring_Agent : statut={structuring_report.status}, "
        f"{len(structuring_report.questions_created)} question(s) ---\n"
    )
    if not structuring_report.questions_created:
        print("Aucune question créée — impossible de continuer.")
        return

    order_to_id = {q["order"]: uuid.uuid4() for q in structuring_report.questions_created}
    questions = [
        QuestionInput(
            question_id=order_to_id[q["order"]],
            order=q["order"],
            statement=q["statement"],
            section_order=q["section_order"],
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
            block_id=uuid.uuid4(),
            content_type=content_type,
            raw_text=c["raw_text"],
            structured_content=c["structured_content"],
            evidence_level=c["evidence_level"],
        ))

    total_corrections = sum(len(v) for v in blocks_by_question.values())
    print(
        f"--- Extraction_Verification_Agent : {len(questions)} question(s), "
        f"{total_corrections} bloc(s) de correction rattaché(s) ---\n"
    )

    # --- Étape 2 (déjà validée) : Extraction_Verification_Agent, réel, inchangé ---
    verification_agent = eva_module.ExtractionVerificationAgent()
    verif_report = await verification_agent.execute(
        questions=questions,
        blocks_by_question=blocks_by_question,
        exercise_status=ExerciseStatus.DRAFT,
        context=context,
    )

    order_by_id = {q.question_id: q.order for q in questions}
    reasoning_agent = rga_module.ReasoningGraphAgent()

    for qres in verif_report.questions:
        order = order_by_id[qres.question_id]
        print(f"=== Question order={order} ===")
        print(f"decomposition_error : {qres.decomposition_error}")

        if qres.decomposition_error is not None:
            print("-> décomposition Agent 4 en échec, question ignorée (comme en production réelle).\n")
            continue

        # --- Étape 3 (nouvelle, v2) : Reasoning_Graph_Agent, réel, inchangé ---
        # Réplique la production post-refactor : les steps déjà décomposés
        # par Agent 4 (qres.steps, de vraies ReasoningStepOutput) deviennent
        # directement l'entrée d'Agent 5 — jamais un texte brut à reparser.
        # step_id = step_ref d'Agent 4 ("s1", "s2"...), un identifiant opaque
        # tel quel (en production ce serait str(ReasoningStep.id), mais rien
        # dans l'agent n'exige un format UUID).
        steps_input = [
            ExistingStepInput(
                step_id=step.step_ref,
                order=step.order,
                step_type=step.step_type,
                description=step.description,
                formula=step.formula,
                source_span=step.source_span,
            )
            for step in qres.steps
        ]
        variant_id = uuid.uuid4()
        print(f"[diag] {len(steps_input)} étape(s) d'Agent 4 transmises à Agent 5 pour enrichissement")

        try:
            graph_report = await reasoning_agent.execute(
                variant_id=variant_id,
                steps=steps_input,
                question_domain_type=qres.question_domain_type.value,
                context=context,
            )
        except Exception as exc:
            print(f"ÉCHEC Reasoning_Graph_Agent : {type(exc).__name__}: {exc}\n")
            continue

        print(f"construction_confidence : {graph_report.construction_confidence}")
        print(f"is_valid_dag            : {graph_report.is_valid_dag}")
        print(f"Étapes ({len(graph_report.steps)}) :")
        for s in graph_report.steps:
            line = f"  [{s.step_type.value}] {s.step_ref} <- {s.depends_on_refs} : {s.description[:90]}"
            if s.formula:
                line += f" | formule: {s.formula}"
            print(line)
            print(f"      is_core_step={s.is_core_step} tools_used={s.tools_used} concept_tags={s.concept_tags}")
            top_weights = sorted(s.competency_weights, key=lambda cw: -cw.weight)[:2]
            if top_weights and top_weights[0].weight > 0:
                print(f"      competencies: {[(cw.code.value, cw.weight) for cw in top_weights]}")

        print(f"Clarifications ({len(graph_report.clarifications)}) :")
        for cl in graph_report.clarifications:
            print(f"  [{cl.severity.value}] {cl.related_field} : {cl.agent_question[:150]}")
        print()


if __name__ == "__main__":
    page_set = {int(p) for p in sys.argv[1].split(",")} if len(sys.argv) == 2 else None
    asyncio.run(main(page_set))
