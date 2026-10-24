"""
Sonde pour Contestation_Verification_Agent — premier test réel, Cas A
(CONTENT) uniquement. Scénario synthétique construit à partir de données
RÉELLES déjà obtenues (step7, copie1.jpg) : le bloc 4 de la copie étudiant
contient "...une valeur maximale d'environ 29 kN pour P." — alors que les
blocs 5 et 6 de la MÊME copie concluent "P = 28 kN" / "Pmax = 28 kN". Ce
n'est PAS une invention : c'est une incohérence numérique réelle et
observable dans le document, un candidat plausible et honnête pour une
contestation "l'OCR a mal lu mon chiffre" (l'étudiant prétend avoir écrit
28, pas 29) — sans savoir à l'avance si l'écriture manuscrite dit vraiment
28 ou 29, ce que seule une vraie relecture OCR2 en pleine résolution peut
trancher.

Réutilise directement la vraie classe ContestationVerificationAgent
(inchangée par ce script — le fix du 2026-08-18, sortie structurée pour les
Cas B/C, est dans le fichier agent lui-même) sur la vraie image copie1.jpg
et le vrai bounding_box du bloc 4 (cf. copie1_raw_blocks_dump.json, produit
par step7). Deux monkeypatches, jamais un fichier app/ modifié :
invoke_llm_with_fallback -> Gemini, storage_service.upload -> no-op (pas de
vrai upload Azure du crop pleine résolution).

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step8_test_contestation_verification_probe_gemini.py
"""
import asyncio
import json
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

import app.agents.Contestation_Verification_Agent as cva_module
from app.agents.context import AgentExecutionContext
from app.agents.Contestation_Verification_Agent import (
    ContestationCaseInput,
    ContestationVerificationAgent,
    ExtractionCorrectionSnapshot,
)
from app.domain.models.assessment.extraction_correction import ContestationType, ExtractionContentType
from app.domain.schemas.contestation_schemas import ContestExtractionRequest
from app.observability.langfuse import AgentTraceSpan

GEMINI_MODEL_NAME = "gemini-flash-lite-latest"
MAX_RPM = 12

COPIE_PATH = Path(__file__).resolve().parent.parent / "copie1.jpg"
DUMP_PATH = Path(__file__).resolve().parent / "copie1_raw_blocks_dump.json"

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
    """Cf. step7 — réplique ModelProvider (str + .value) pour f"{spec.provider}:..." ET spec.provider.value."""
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


async def _noop_upload(container, blob_path, data, content_type=None, overwrite=True):
    return blob_path


cva_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
cva_module.storage_service.upload = _noop_upload


async def main() -> None:
    if not COPIE_PATH.exists():
        print(f"{COPIE_PATH} introuvable — arrêt.")
        sys.exit(1)
    if not DUMP_PATH.exists():
        print(f"{DUMP_PATH} introuvable — relancer step7 d'abord.")
        sys.exit(1)

    payload = json.loads(DUMP_PATH.read_text(encoding="utf-8"))
    block4 = next(b for b in payload["blocks"] if b["block_order_index"] == 4)
    print(f"--- Bloc contesté (réel, bloc 4 de copie1.jpg) ---\n{block4['prediction_ocr']!r}\n")

    ocr1_text = block4["prediction_ocr"]
    claimed_text = ocr1_text.replace("29 kN", "28 kN")
    print(f"--- Réclamation étudiante (hypothèse à vérifier) ---\n{claimed_text!r}\n")

    contested = ExtractionCorrectionSnapshot(
        id=uuid.uuid4(),
        submission_id=uuid.uuid4(),
        image_crop_path=block4["image_crop_path"],
        content_type=ExtractionContentType(block4["content_type"]),
        prediction_ocr=ocr1_text,
        bounding_box=block4["bounding_box"],
        evidence_level=block4["evidence_level"],
        page_number=block4["page_number"],
    )
    request = ContestExtractionRequest(
        contestation_type=ContestationType.CONTENT,
        claimed_content=claimed_text,
    )
    case = ContestationCaseInput(
        contested=contested,
        request=request,
        document_bytes=COPIE_PATH.read_bytes(),
        document_mime_type="image/jpeg",
        reverification_attempt=1,
    )

    trace_id = str(uuid.uuid4())
    with AgentTraceSpan(
        "test_pipeline_step8", trace_id=trace_id,
        metadata={"script": "step8_test_contestation_verification_probe_gemini"},
    ):
        context = AgentExecutionContext(
            trace_id=trace_id, flow_type="student_evaluation", submission_id=contested.submission_id,
        )
        agent = ContestationVerificationAgent()
        verdict = await agent.execute(case, context)

    print("=== Verdict Contestation_Verification_Agent (Cas A — CONTENT) ===")
    print(f"  verdict           : {verdict.verdict}")
    print(f"  verified_content  : {verdict.verified_content!r}")
    print(f"  ocr2_result       : {verdict.ocr2_result!r}")
    print(f"  ocr2_confidence   : {verdict.ocr2_confidence}")
    print(f"  confidence_score  : {verdict.confidence_score}")
    print(f"  anomaly_flag      : {verdict.anomaly_flag}")
    print(f"  model_version     : {verdict.model_version}")
    print(f"  justification     : {verdict.justification}")


if __name__ == "__main__":
    asyncio.run(main())
