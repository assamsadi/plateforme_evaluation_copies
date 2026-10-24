"""
Variante de step3_test_document_structuring_probe.py — bascule l'appel LLM
interne d'Agent 3 (_classify_block, TaskType.DOCUMENT_STRUCTURING) sur
Gemini au lieu de Groq/OpenAI, tous deux à sec (Groq : quota TPD journalier
épuisé ; OpenAI : credit_balance_exhausted).

IMPORTANT — ceci est un cas DIFFÉRENT du bug de schéma STRUCTURE trouvé plus
tôt (TABLE/MULTI_COLUMN_LIST mal formés par Gemini en OCR_VISION, cf.
step3_test_document_structuring_probe.py::_normalize_structure_content) :
Document_Structuring_Agent._classify_block N'UTILISE PAS with_structured_
output — il demande juste un JSON en texte libre au LLM et l'extrait par
regex (response_schema=None dans l'appel invoke_llm_with_fallback). Rien à
voir avec le schéma Pydantic complexe PageExtractionResult de l'OCR. Le bug
STRUCTURE ne s'applique donc pas à cet appel-ci.

Comme TaskType.DOCUMENT_STRUCTURING résout Groq/OpenAI dans le vrai
registre (Gemini n'y est pas enregistré, cf. app/model_registry/*), ce
script monkeypatch UNIQUEMENT la référence `invoke_llm_with_fallback`
importée dans le module app.agents.Document_Structuring_Agent (jamais le
fichier lui-même) pour rediriger CE task_type précis vers Gemini. Chaque
appel réel passe par un limiteur de débit maison (fenêtre glissante 60s)
pour rester sous le RPM du modèle — le sémaphore interne de l'agent
(DOCUMENT_STRUCTURING_MAX_CONCURRENCY=4) limite la CONCURRENCE, pas le
débit cumulé dans le temps, insuffisant seul pour 147 blocs à 15 RPM.

Prérequis : identiques aux sondes précédentes (GOOGLE_API_KEY dans .env,
agents_tests/gemini_ocr_dump.json déjà généré par step1_test_ocr_gemini_
probe.py).

Lancer depuis la racine du projet (~10-12 min pour 147 blocs à 12 RPM) :

    .venv/Scripts/python.exe agents_tests/step3_test_document_structuring_probe_gemini.py
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
from app.agents.context import AgentExecutionContext
from app.domain.models.assessment.exercise import ExerciseStatus
from app.model_registry.models import TaskType
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
    if task_type != TaskType.DOCUMENT_STRUCTURING:
        raise RuntimeError(f"Sonde limitée à DOCUMENT_STRUCTURING, reçu {task_type}")

    from langchain_google_genai import ChatGoogleGenerativeAI

    await _rate_limit()
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL_NAME,
        google_api_key=os.environ["GOOGLE_API_KEY"],
        temperature=0.1,
    )
    # Depuis le fix de _classify_block (sortie structurée au lieu du regex JSON), response_schema
    # n'est plus None — il FAUT le brancher ici aussi, sinon on reçoit un AIMessage brut au lieu
    # d'un BlockClassificationResult.
    if response_schema is not None:
        llm = llm.with_structured_output(response_schema)
    result = await llm.ainvoke(messages)
    fake_spec = SimpleNamespace(provider="gemini", model_name=GEMINI_MODEL_NAME)
    return result, fake_spec, False, {}


# Monkeypatch de la référence importée dans le module de l'agent — jamais le fichier source.
dsa_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback


async def main() -> None:
    raw_blocks = _load_raw_blocks()
    print(f"--- {len(raw_blocks)} bloc(s) — classification via Gemini ({GEMINI_MODEL_NAME}, {MAX_RPM} RPM max) ---\n")

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
    asyncio.run(main())
