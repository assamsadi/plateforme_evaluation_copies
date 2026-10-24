"""
Sonde pour Extraction_Verification_Agent — l'agent qui s'exécute côté
professeur juste après Document_Structuring_Agent (Agent 3, déjà testé et
corrigé le 2026-08-16). Chaîne les VRAIES classes de production, jamais
dupliquées : DocumentStructuringAgent tourne d'abord sur les vraies pages
OCR déjà extraites (cf. gemini_ocr_dump.json, step1_test_ocr_gemini_probe.py),
puis ExtractionVerificationAgent tourne sur la Question + les blocs de
correction RÉELLEMENT produits par le premier — aucune donnée fabriquée à la
main, contrairement à un test unitaire isolé.

ATTENTION — Extraction_Verification_Agent utilise EXACTEMENT le même schéma
d'extraction JSON fragile que Document_Structuring_Agent AVANT son fix du
2026-08-16 (regex sur la 1ere/derniere accolade + json.loads, response_schema
=None dans ses 3 appels LLM : _decompose_steps, _extract_or_propose_bareme,
_extract_subquestion_points) — jamais corrigé ici, aucun fichier app/ modifié
par ce script. Cet agent manipule justement des formules/LaTeX (champ
`formula`, vérification sympy/pint) — le même bug de parsing JSON cassé par
du LaTeX (cf. historique Document_Structuring_Agent) est probable ici aussi.
Ce test sert à le confirmer ou l'infirmer sur de vraies données.

TaskType.EXTRACTION_VERIFICATION n'étant pas plus disponible sur Groq (quota
épuisé) qu'OpenAI (crédit épuisé), ce script redirige LES DEUX agents vers
OpenRouter (même monkeypatch en mémoire que step3_test_document_structuring_
probe_openrouter.py, jamais un fichier app/ modifié) : TaskType.DOCUMENT_
STRUCTURING pour le premier agent, TaskType.EXTRACTION_VERIFICATION pour le second.

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step4_test_extraction_verification_probe.py [pages]

Ex. pages 1 à 10 (déjà éprouvées à fond pour Agent 3, statut COMPLETE) :

    .venv/Scripts/python.exe agents_tests/step4_test_extraction_verification_probe.py 1,2,3,4,5,6,7,8,9,10

Sans argument : document entier.
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

import app.agents.Document_Structuring_Agent as dsa_module
import app.agents.Extraction_Verification_Agent as eva_module
from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import CorrectionBlockInput, QuestionInput
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from step3_test_document_structuring_probe import _load_raw_blocks

OPENROUTER_MODEL_NAME = "meta-llama/llama-3.3-70b-instruct"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


async def _openrouter_invoke_llm_with_fallback(task_type, messages, response_schema, context):
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=OPENROUTER_MODEL_NAME,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
        temperature=0.1,
    )
    if response_schema is not None:
        llm = llm.with_structured_output(response_schema)
    result = await llm.ainvoke(messages)
    fake_spec = SimpleNamespace(provider="openrouter", model_name=OPENROUTER_MODEL_NAME)
    return result, fake_spec, False, {}


# Monkeypatch des références importées dans CHAQUE module d'agent — jamais les fichiers source.
dsa_module.invoke_llm_with_fallback = _openrouter_invoke_llm_with_fallback
eva_module.invoke_llm_with_fallback = _openrouter_invoke_llm_with_fallback


async def main(pages: set[int] | None) -> None:
    raw_blocks = _load_raw_blocks(pages=pages)
    scope = f"pages {sorted(pages)}" if pages is not None else "document entier"
    print(f"--- {len(raw_blocks)} bloc(s) OCR ({scope}) ---\n")

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
        print("Aucune question créée — impossible de tester Extraction_Verification_Agent.")
        return

    # --- Conversion du VRAI rapport d'Agent 3 en entrée d'Extraction_Verification_Agent ---
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
        ))

    total_corrections = sum(len(v) for v in blocks_by_question.values())
    print(
        f"--- Extraction_Verification_Agent : {len(questions)} question(s), "
        f"{total_corrections} bloc(s) de correction rattaché(s) ---\n"
    )

    # --- Étape 2 (nouvelle) : Extraction_Verification_Agent, réel, inchangé ---
    verification_agent = eva_module.ExtractionVerificationAgent()
    verif_report = await verification_agent.execute(
        questions=questions,
        blocks_by_question=blocks_by_question,
        exercise_status=ExerciseStatus.DRAFT,
        context=context,
    )

    order_by_id = {q.question_id: q.order for q in questions}
    for qres in verif_report.questions:
        print(f"=== Question order={order_by_id[qres.question_id]} ===")
        print(f"decomposition_error : {qres.decomposition_error}")
        print(f"Étapes ({len(qres.steps)}) :")
        for s in qres.steps:
            line = f"  [{s.step_type.value}] {s.description[:100]}"
            if s.formula:
                line += f" | formule: {s.formula}"
            if s.anomaly_detected:
                line += f" | ANOMALIE: {s.anomaly_justification}"
            print(line)

        print(f"bareme_error : {qres.bareme_error}")
        if qres.bareme:
            print(
                f"Barème : case={qres.bareme.case} status={qres.bareme.status} "
                f"total={qres.bareme.total_points}"
            )
            for crit in qres.bareme.criteria:
                print(f"  - {crit.label} ({crit.points} pts) mode={crit.correction_mode.value}")

        print(f"mandated_method : {qres.mandated_method}")
        print(f"question_domain_type : {qres.question_domain_type.value}")
        print(f"covered_subquestions : {qres.covered_subquestions}")
        print(f"competencies_mobilized : {[c.value for c in qres.competencies_mobilized]}")
        print(f"subquestion_points : {qres.subquestion_points}")
        print(f"depends_on_question_order : {qres.depends_on_question_order}")

        print(f"Clarifications ({len(qres.clarifications)}) :")
        for cl in qres.clarifications:
            print(f"  [{cl.severity.value}] {cl.related_field} : {cl.agent_question[:150]}")
        print()


if __name__ == "__main__":
    page_set = {int(p) for p in sys.argv[1].split(",")} if len(sys.argv) == 2 else None
    asyncio.run(main(page_set))
