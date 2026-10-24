"""
Sonde pour Solution_Variant_Generation_Agent — le nœud suivant dans le
pipeline réel après reasoning_graph_node (cf. app/graph/pipeline_graph.py +
routing.py : reasoning_graph_node -> solution_variant_generation_node).
Chaîne DocumentStructuringAgent -> ExtractionVerificationAgent ->
SolutionVariantGenerationAgent, sur les vraies pages OCR déjà extraites.

reference_content / reference_conclusion répliquent EXACTEMENT ce que fait
solution_variant_generation_service.py::generate_variants_for_question en
production :
  - reference_content = le texte de la variante de référence, c-à-d le texte
    brut combiné des blocs de correction (même contenu que celui persisté
    comme SolutionVariant.content par _persist_reasoning_graph).
  - reference_conclusion = le champ `.formula or .description` de l'étape
    dont step_type == "conclusion" (cf. solution_variant_generation_service.
    py:144-147) — PAS canonical_form, PAS une reconstruction : c'est ce qui
    est réellement lu en production, LaTeX brut compris (d'où le fix
    latex2sympy2_extended appliqué aujourd'hui sur cet agent).

Ce script ne fait PAS tourner Reasoning_Graph_Agent : Solution_Variant_
Generation_Agent ne dépend que de ReasoningStep.formula/.description
(Agent 4), jamais des champs qu'Agent 5 ajoute (depends_on_refs réels,
is_core_step, tools_used) — cohérent avec la lecture réelle du service.

ATTENTION — mêmes bugs déjà trouvés et corrigés AUJOURD'HUI par relecture de
code (jamais testés en réel avant ce script) :
  1. response_schema=None + regex JSON -> structured output.
  2. TaskType.REASONING_GRAPH (mauvais) -> TaskType.SOLUTION_VARIANT_GENERATION.
  3. _extract_sympy_expression cassait le LaTeX non trivial (\\frac{N}{A} ->
     symbole "NA") -> latex2sympy2_extended, même pattern qu'Extraction_
     Verification_Agent. Vérifié uniquement en local (mock) jusqu'ici — ce
     script est le premier test réel bout en bout.

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step6_test_solution_variant_generation_probe_gemini.py [pages]

Ex. pages 1 à 10 :

    .venv/Scripts/python.exe agents_tests/step6_test_solution_variant_generation_probe_gemini.py 1,2,3,4,5,6,7,8,9,10

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
import app.agents.Solution_Variant_Generation_Agent as svga_module
from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import CorrectionBlockInput, QuestionInput
from app.agents.Solution_Variant_Generation_Agent import SolutionVariantGenerationAgent
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.models.assessment.reasoning_step import ReasoningStepType
from app.domain.schemas.solution_variant_generation_schemas import ReferenceStepContext
from app.observability.langfuse import AgentTraceSpan
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
svga_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback


def _combine_block_text(blocks: list[CorrectionBlockInput]) -> str:
    """Réplique exacte de ExtractionVerificationService._combine_block_text."""
    return "\n".join(b.raw_text for b in blocks if b.raw_text)


async def main(pages: set[int] | None) -> None:
    """
    Ouvre UN SEUL span racine englobant toute la chaîne d'agents (cf.
    mémoire de session, fix Langfuse 2026-08-17) : sans lui, chaque agent
    (Document_Structuring_Agent, Extraction_Verification_Agent,
    Solution_Variant_Generation_Agent) ferme son propre span avant que
    l'agent suivant démarre, donc le contexte ambiant est vide à chaque
    fois — chacun devient sa propre racine Langfuse déconnectée malgré un
    trace_id applicatif partagé. En production, ce rôle est tenu par le
    span ouvert autour de graph.ainvoke() dans exercise_tasks.py /
    submission_tasks.py / job_tasks.py — ce script appelle les agents
    directement (sans passer par pipeline_graph.py), donc il doit ouvrir ce
    span lui-même pour que la vérification sur le dashboard soit valide.
    """
    trace_id = str(uuid.uuid4())
    with AgentTraceSpan(
        "test_pipeline_step6", trace_id=trace_id, metadata={"script": "step6_test_solution_variant_generation_probe_gemini"},
    ):
        await _run_pipeline(pages=pages, trace_id=trace_id)


async def _run_pipeline(pages: set[int] | None, trace_id: str) -> None:
    raw_blocks = _load_raw_blocks(pages=pages)
    scope = f"pages {sorted(pages)}" if pages is not None else "document entier"
    print(f"--- {len(raw_blocks)} bloc(s) OCR ({scope}) — via Gemini ({GEMINI_MODEL_NAME}, {MAX_RPM} RPM max) ---\n")

    context = AgentExecutionContext(
        trace_id=trace_id, flow_type="exercise_setup", exercise_id=uuid.uuid4(),
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
    generation_agent = SolutionVariantGenerationAgent()

    for qres in verif_report.questions:
        order = order_by_id[qres.question_id]
        print(f"=== Question order={order} ===")
        print(f"decomposition_error : {qres.decomposition_error}")

        if qres.decomposition_error is not None:
            print("-> décomposition Agent 4 en échec, question ignorée (comme en production réelle).\n")
            continue

        # --- Étape 3 (nouvelle) : Solution_Variant_Generation_Agent, réel, inchangé ---
        # Réplique exacte de solution_variant_generation_service.py:144-147 :
        # reference_conclusion = .formula or .description de l'étape CONCLUSION,
        # jamais canonical_form, jamais reconstruit.
        reference_content = _combine_block_text(blocks_by_question.get(qres.question_id, []))
        reference_conclusion = ""
        for s in qres.steps:
            if s.step_type == ReasoningStepType.CONCLUSION:
                reference_conclusion = s.formula or s.description
        # Toutes les formules de la référence AVEC leur description (v1.3 +
        # v1.9, cf. mémoire de session) — nécessaire pour
        # _verify_intermediate_consistency (comparaison des grandeurs
        # partagées) ET _resolve_symbol_correspondences (correspondance
        # sémantique quand les noms diffèrent, ex. "N" vs "N_5"), pas
        # seulement la conclusion finale. Réplique exacte de
        # solution_variant_generation_service.py (ref_steps_context).
        reference_steps = [
            ReferenceStepContext(formula=s.formula, description=s.description)
            for s in qres.steps if s.formula
        ]
        print(f"[diag] reference_conclusion : {reference_conclusion!r}")
        print(f"[diag] reference_steps ({len(reference_steps)}) :")
        for rs in reference_steps:
            print(f"    {rs.formula!r} — {rs.description!r}")

        question_stmt = next(q.statement for q in questions if q.question_id == qres.question_id)

        try:
            gen_report = await generation_agent.execute(
                question_id=qres.question_id,
                question_statement=question_stmt,
                reference_content=reference_content,
                reference_conclusion=reference_conclusion,
                reference_steps=reference_steps,
                existing_variants=[],
                academic_envelope=None,
                mandated_method=qres.mandated_method,
                trigger_type="proactive",
                context=context,
            )
        except Exception as exc:
            print(f"ÉCHEC Solution_Variant_Generation_Agent : {type(exc).__name__}: {exc}\n")
            continue

        print(f"skipping_reason : {gen_report.skipping_reason}")
        print(f"total_llm_calls : {gen_report.total_llm_calls}")
        print(f"Tentatives ({len(gen_report.attempt_logs)}) :")
        for log in gen_report.attempt_logs:
            line = f"  [{log.status}] {log.strategy_name} (essai #{log.attempt_number})"
            if log.distinction_score is not None:
                line += f" distinction={log.distinction_score}"
            if log.intermediate_verified_count is not None:
                line += f" intermediate_verified_count={log.intermediate_verified_count}"
            if log.rejection_reason:
                line += f" | {log.rejection_reason[:250]}"
            print(line)
            if log.intermediate_check_note:
                print(f"      note: {log.intermediate_check_note}")

        print(f"Candidats acceptés ({len(gen_report.candidates)}) :")
        for cand in gen_report.candidates:
            print(f"\n  ========== {cand.strategy_name} ({cand.difficulty_level.value}) ==========")
            print(f"  résumé      : {cand.reasoning_summary}")
            print(f"  conclusion  : {cand.conclusion_formula!r}")
            print(f"  concept_tags: {cand.concept_tags}")
            print(f"  hors enveloppe académique : {cand.outside_academic_envelope}"
                  + (f" ({cand.outside_concepts})" if cand.outside_academic_envelope else ""))
            print(f"  steps_summary ({len(cand.steps_summary)}) :")
            for s in cand.steps_summary:
                line = f"    [{s.step_type}] order={s.order} : {s.description}"
                if s.formula:
                    line += f" | formule: {s.formula}"
                print(line)
            print(f"  --- contenu complet de la solution générée ---")
            print(f"  {cand.content}")
        print()


if __name__ == "__main__":
    page_set = {int(p) for p in sys.argv[1].split(",")} if len(sys.argv) == 2 else None
    asyncio.run(main(page_set))
