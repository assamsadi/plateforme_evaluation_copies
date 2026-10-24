"""
Variante de step3_test_document_structuring_probe.py — bascule l'appel LLM
interne d'Agent 3 (_classify_block, TaskType.DOCUMENT_STRUCTURING) sur
OpenRouter au lieu de Groq/OpenAI (Groq : TPM/TPD à répétition ; OpenAI :
credit_balance_exhausted). Sert aussi à vérifier si le bug JSON malformé
trouvé avec Groq (`Expecting property name enclosed in double quotes`,
3 blocs sur 15 de la page 13) est spécifique à l'hébergement Groq de
llama-3.3-70b, ou plus général — modèle testé ici : le même llama-3.3-70b
mais hébergé par OpenRouter (meta-llama/llama-3.3-70b-instruct).

OpenRouter expose une API compatible OpenAI (base_url différente) — pas
besoin de nouveau package, ChatOpenAI (déjà utilisé par providers.py)
suffit avec un base_url custom. TaskType.DOCUMENT_STRUCTURING n'ayant pas
OpenRouter comme ModelProvider enregistré (cf. app/model_registry/models.py),
ce script monkeypatch UNIQUEMENT la référence `invoke_llm_with_fallback`
importée dans le module app.agents.Document_Structuring_Agent (jamais le
fichier lui-même) pour rediriger CE task_type précis — même mécanisme que
step3_test_document_structuring_probe_gemini.py.

Prérequis : OPENROUTER_API_KEY dans .env, agents_tests/gemini_ocr_dump.json
déjà généré.

Lancer depuis la racine du projet (page 13 par défaut, celle du test Groq
précédent, pour comparaison directe) :

    .venv/Scripts/python.exe agents_tests/step3_test_document_structuring_probe_openrouter.py

Ou une autre page :

    .venv/Scripts/python.exe agents_tests/step3_test_document_structuring_probe_openrouter.py 2
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
from app.agents.context import AgentExecutionContext
from app.domain.models.assessment.exercise import ExerciseStatus
from app.model_registry.models import TaskType
from step3_test_document_structuring_probe import _load_raw_blocks

OPENROUTER_MODEL_NAME = "meta-llama/llama-3.3-70b-instruct"  # même famille que Groq, pour comparer l'hébergement
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


async def _openrouter_invoke_llm_with_fallback(task_type, messages, response_schema, context):
    if task_type != TaskType.DOCUMENT_STRUCTURING:
        raise RuntimeError(f"Sonde limitée à DOCUMENT_STRUCTURING, reçu {task_type}")

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=OPENROUTER_MODEL_NAME,
        api_key=os.environ["OPENROUTER_API_KEY"],
        base_url=OPENROUTER_BASE_URL,
        temperature=0.1,
    )
    # Depuis le fix de _classify_block (sortie structurée au lieu du regex JSON), response_schema
    # n'est plus None — il FAUT le brancher ici aussi, sinon on reçoit un AIMessage brut au lieu
    # d'un BlockClassificationResult (constaté : 'AIMessage' object has no attribute 'classification').
    if response_schema is not None:
        llm = llm.with_structured_output(response_schema)
    result = await llm.ainvoke(messages)
    fake_spec = SimpleNamespace(provider="openrouter", model_name=OPENROUTER_MODEL_NAME)
    return result, fake_spec, False, {}


# Monkeypatch de la référence importée dans le module de l'agent — jamais le fichier source.
dsa_module.invoke_llm_with_fallback = _openrouter_invoke_llm_with_fallback


async def main(pages: set[int] | None) -> None:
    raw_blocks = _load_raw_blocks(pages=pages)
    scope = f"pages {sorted(pages)}" if pages is not None else "toutes les pages"
    print(f"--- {len(raw_blocks)} bloc(s) — classification via OpenRouter ({OPENROUTER_MODEL_NAME}) ({scope}) ---\n")

    agent = dsa_module.DocumentStructuringAgent()
    context = AgentExecutionContext(
        trace_id=str(uuid.uuid4()),
        flow_type="exercise_setup",
        exercise_id=uuid.uuid4(),
    )

    report = await agent.execute(
        raw_blocks=raw_blocks,
        exercise_status=ExerciseStatus.DRAFT,
        context=context,
    )

    print(f"Statut : {report.status}\n")

    print(f"Sections créées ({len(report.sections_created)}) :")
    for s in report.sections_created:
        print(f"  - order={s['order']} title={s['title']!r}")

    print(f"\nQuestions créées ({len(report.questions_created)}) :")
    for q in report.questions_created:
        preview = (q["statement"] or "")[:100].replace("\n", " ")
        print(f"  - order={q['order']} label={q['question_label']!r} section={q['section_order']} "
              f"corrections={q['correction_count']}")
        print(f"      statement : {preview}")

    print(f"\nBlocs de correction rattachés ({len(report.correction_blocks_created)}) :")
    for c in report.correction_blocks_created[:15]:
        preview = (c["raw_text"] or "")[:80].replace("\n", " ")
        print(f"  - question_order={c['question_order']} evidence={c['evidence_level'].value} : {preview}")
    if len(report.correction_blocks_created) > 15:
        print(f"  ... (+{len(report.correction_blocks_created) - 15} autres)")

    print("\nCompteurs de complétude :")
    print(f"  unresolved_block_count            = {report.unresolved_block_count}")
    print(f"  questions_without_correction_count = {report.questions_without_correction_count}")
    print(f"  label_conflict_count              = {report.label_conflict_count}")
    print(f"  empty_section_count               = {report.empty_section_count}")
    print(f"  unlabelled_statement_block_count  = {report.unlabelled_statement_block_count}")
    print(f"  correction_label_conflict_count   = {report.correction_label_conflict_count}")

    if report.empty_sections_detail:
        print(f"\nSections vides : {report.empty_sections_detail}")
    if report.label_conflicts_detail:
        print(f"\nConflits de label (énoncé) : {report.label_conflicts_detail}")
    if report.correction_label_conflicts_detail:
        print(f"\nConflits de label (correction) : {report.correction_label_conflicts_detail}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        page_set = {13}
    elif sys.argv[1] == "all":
        page_set = None
    else:
        page_set = {int(p) for p in sys.argv[1].split(",")}
    asyncio.run(main(page_set))
