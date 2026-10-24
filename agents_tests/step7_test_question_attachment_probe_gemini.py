"""
Sonde pour Question_Attachment_Agent (Agent 2) — PREMIER test réel du
branchement sur de vrais embeddings (app/core/embeddings.py, sentence-
transformers/all-MiniLM-L6-v2, fix du 2026-08-18 : _embed_text était un
hash factice jamais branché depuis sa création). Chaîne complète, réelle :

  1. OCR Gemini de agents_tests/document.pdf (professeur, DÉJÀ mis en cache
     par step1_test_ocr_gemini_probe.py -> gemini_ocr_dump.json, jamais
     rappelé ici) -> Document_Structuring_Agent -> Extraction_Verification_
     Agent, pour obtenir de VRAIES Question avec un VRAI reference_content
     (réplique exacte de step6, mêmes étapes 1-2, inchangées).
  2. OCR de copie1.jpg (étudiant) via le VRAI OCRExtractionAgent.
     execute() (v2, 2026-08-18 — pas un appel LLM brut simplifié comme la
     v1 de ce script) : contrôle qualité, redressement, lecture vision,
     validation de schéma, relecture ciblée — tout le pipeline réel, pas
     seulement l'appel Gemini. Deux monkeypatches, jamais un fichier app/
     modifié : invoke_llm_with_fallback -> Gemini (même technique que les
     3 autres agents ci-dessous, OCR_Extraction_Agent l'utilise à
     l'identique) ; storage_service.upload -> no-op (l'agent tente un VRAI
     upload Azure des crops dès que context.submission_id est renseigné —
     ce script utilise un submission_id fictif, jamais un vrai upload
     cloud). Résultat mis en cache dans son propre dump JSON (jamais
     gemini_ocr_dump.json, qui appartient au document professeur et est
     réutilisé par step3/step6).
  3. QuestionAttachmentAgent.execute(), RÉEL et INCHANGÉ dans ce script (le
     fix est dans app/agents/Question_Attachment_Agent.py lui-même, pas ici)
     — rattache les blocs de la copie étudiant aux Questions réelles.

Ce que ce test doit révéler, pour la première fois avec un vrai signal
sémantique (jusqu'ici toujours un hash sans queue ni tête) :
  - Le Niveau 2 (similarité cosinus) résout-il quoi que ce soit correctement,
    ou tout part-il systématiquement au Niveau 3 (LLM) / Niveau 4 (orphelin) ?
  - QUESTION_ATTACHMENT_COSINE_THRESHOLD=0.05 (recalibré ce jour) est-il
    seulement un point de départ raisonnable, ou faut-il l'ajuster encore
    pour CE modèle (sentence-transformers, 384 dim) ?

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step7_test_question_attachment_probe_gemini.py
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

import app.agents.Document_Structuring_Agent as dsa_module
import app.agents.Extraction_Verification_Agent as eva_module
import app.agents.OCR_Extraction_Agent as ocr_module
import app.agents.Question_Attachment_Agent as qaa_module
from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import CorrectionBlockInput, QuestionInput
from app.agents.OCR_Extraction_Agent import OCRExtractionAgent
from app.agents.Question_Attachment_Agent import QuestionAttachmentAgent, QuestionRef
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from app.domain.schemas.submission_schemas import RawExtractedBlock
from app.observability.langfuse import AgentTraceSpan
from step3_test_document_structuring_probe import _load_raw_blocks

GEMINI_MODEL_NAME = "gemini-flash-lite-latest"
MAX_RPM = 12  # marge sous les ~15 RPM annoncés pour la famille flash-lite

SOUMISSION_PDF_PATH = Path(__file__).resolve().parent.parent / "copie1.jpg"
SOUMISSION_MIME_TYPE = "image/jpeg"
SOUMISSION_DUMP_PATH = Path(__file__).resolve().parent / "copie1_raw_blocks_dump.json"

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
    """
    Réplique le comportement de ModelProvider (StrEnum réel, cf.
    app/model_registry/models.py) que ce script simule sans provider Gemini
    enregistré : une chaîne normale (str(spec.provider) marche partout où le
    reste du code interpole juste en texte, ex. Document_Structuring_Agent/
    Question_Attachment_Agent) ET porte .value (StrEnum le fait toujours) —
    nécessaire pour OCR_Extraction_Agent.py:145, le SEUL endroit du projet
    qui appelle spec.provider.value directement (trouvé en le cassant : un
    SimpleNamespace(provider="gemini", ...) n'a pas de .value sur une str
    nue, jamais un problème avant ce script car aucun autre agent testé
    cette session n'accède à .value, seulement via f-string).
    """
    @property
    def value(self) -> str:
        return str(self)


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
    fake_spec = SimpleNamespace(provider=_FakeProvider("gemini"), model_name=GEMINI_MODEL_NAME)
    return result, fake_spec, False, {}


async def _noop_upload(container, blob_path, data, content_type=None, overwrite=True):
    """
    Neutralise storage_service.upload (JAMAIS de vrai upload Azure depuis ce
    script) — OCR_Extraction_Agent._upload_block_crops appelle ceci dès que
    context.submission_id est renseigné (flux étudiant), avec un
    submission_id fictif ici. Le retour n'est pas utilisé par l'agent
    (image_crop_path vient de path_builder, pas de la valeur de retour).
    """
    return blob_path


# Monkeypatch des références importées dans CHAQUE module d'agent — jamais les fichiers source.
dsa_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
eva_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
qaa_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
ocr_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback
ocr_module.storage_service.upload = _noop_upload


def _combine_block_text(blocks: list[CorrectionBlockInput]) -> str:
    """Réplique exacte de ExtractionVerificationService._combine_block_text."""
    return "\n".join(b.raw_text for b in blocks if b.raw_text)


async def _ocr_soumission_via_gemini(trace_id: str) -> list[RawExtractedBlock]:
    """
    OCR RÉEL via le VRAI OCRExtractionAgent.execute() (v2, 2026-08-18) — cf.
    docstring module pour les deux monkeypatches (LLM + storage no-op).
    Réutilise le dump JSON s'il existe déjà (évite un appel Gemini payant/
    lent à chaque relance de ce script pendant l'itération sur Question_
    Attachment_Agent, qui lui n'a besoin d'aucun nouvel appel OCR).
    """
    if SOUMISSION_DUMP_PATH.exists():
        print(f"--- OCR étudiant déjà en cache ({SOUMISSION_DUMP_PATH.name}), aucun appel Gemini ---\n")
        payload = json.loads(SOUMISSION_DUMP_PATH.read_text(encoding="utf-8"))
        return [RawExtractedBlock.model_validate(b) for b in payload["blocks"]]

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY absente de l'environnement / .env — arrêt.")
        sys.exit(1)
    if not SOUMISSION_PDF_PATH.exists():
        print(f"{SOUMISSION_PDF_PATH} introuvable — arrêt.")
        sys.exit(1)

    print(
        f"--- OCR RÉEL (vrai OCRExtractionAgent, pipeline complet) de "
        f"{SOUMISSION_PDF_PATH.name} via {GEMINI_MODEL_NAME} ---\n"
    )
    document_bytes = SOUMISSION_PDF_PATH.read_bytes()
    ocr_context = AgentExecutionContext(
        trace_id=trace_id, flow_type="student_evaluation", submission_id=uuid.uuid4(),
    )
    ocr_agent = OCRExtractionAgent()
    blocks = await ocr_agent.execute(
        document_bytes=document_bytes, mime_type=SOUMISSION_MIME_TYPE, context=ocr_context,
    )
    print(
        f"--- {len(blocks)} bloc(s) réel(s) extrait(s) (contrôle qualité + redressement + "
        f"validation de schéma + relecture ciblée) ---\n"
    )

    SOUMISSION_DUMP_PATH.write_text(
        json.dumps({"blocks": [b.model_dump(mode="json") for b in blocks]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"--- Dump étudiant écrit dans {SOUMISSION_DUMP_PATH.name} ---\n")
    return blocks


async def main() -> None:
    """
    Ouvre UN SEUL span racine englobant toute la chaîne d'agents (cf.
    mémoire de session, fix Langfuse 2026-08-17/18) : sans lui, chaque agent
    (OCR_Extraction_Agent, Document_Structuring_Agent, Extraction_
    Verification_Agent, Question_Attachment_Agent) ferme son propre span
    avant que l'agent suivant démarre, donc le contexte ambiant est vide à
    chaque fois — chacun devient sa propre racine Langfuse déconnectée
    malgré un trace_id applicatif partagé. Absent de la première version de
    ce script (step6 l'avait, step7 non — oubli corrigé ici).
    """
    trace_id = str(uuid.uuid4())
    with AgentTraceSpan(
        "test_pipeline_step7", trace_id=trace_id,
        metadata={"script": "step7_test_question_attachment_probe_gemini"},
    ):
        await _run_pipeline(trace_id=trace_id)


async def _run_pipeline(trace_id: str) -> None:
    # --- Étape 1 (en premier, sur demande utilisateur) : OCR RÉEL de la
    # copie étudiant (vrai OCRExtractionAgent) — aucune dépendance envers
    # les étapes professeur ci-dessous, l'ordre entre les deux ne change
    # rien au résultat, seulement à ce qui apparaît en premier à l'écran. ---
    student_blocks = await _ocr_soumission_via_gemini(trace_id)
    print(f"--- {len(student_blocks)} bloc(s) OCR étudiant ({SOUMISSION_PDF_PATH.name}) ---\n")
    for b in student_blocks:
        print(f"    [{b.content_type}] label={b.student_label!r} texte={b.prediction_ocr[:80]!r}")
    print()

    # --- Étapes 2-3 (déjà validées, réplique exacte de step6) : reconstruire
    # de VRAIES Questions avec un VRAI reference_content depuis document.pdf ---
    raw_blocks = _load_raw_blocks(pages=None)
    print(f"--- {len(raw_blocks)} bloc(s) OCR professeur (document.pdf, en cache) ---\n")

    context_teacher = AgentExecutionContext(
        trace_id=trace_id, flow_type="exercise_setup", exercise_id=uuid.uuid4(),
    )
    structuring_agent = dsa_module.DocumentStructuringAgent()
    structuring_report = await structuring_agent.execute(
        raw_blocks=raw_blocks, exercise_status=ExerciseStatus.DRAFT, context=context_teacher,
    )
    if not structuring_report.questions_created:
        print("Aucune question créée côté professeur — impossible de continuer.")
        return

    order_to_id = {q["order"]: uuid.uuid4() for q in structuring_report.questions_created}
    statement_by_id = {order_to_id[q["order"]]: q["statement"] for q in structuring_report.questions_created}
    section_by_id = {order_to_id[q["order"]]: q["section_order"] for q in structuring_report.questions_created}
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
        exercise_status=ExerciseStatus.DRAFT, context=context_teacher,
    )

    exercise_id = uuid.uuid4()
    question_refs: list[QuestionRef] = []
    for qres in verif_report.questions:
        qid = qres.question_id
        question_refs.append(QuestionRef(
            question_id=qid,
            exercise_id=exercise_id,
            order=next(q.order for q in questions if q.question_id == qid),
            statement=statement_by_id[qid],
            section_order=section_by_id[qid],
            reference_content=_combine_block_text(blocks_by_question.get(qid, [])),
            reference_summary=None,
        ))
    print(f"--- {len(question_refs)} Question(s) de référence reconstruite(s) (professeur) ---")
    for qr in question_refs:
        print(f"    Q{qr.order} — reference_content ({len(qr.reference_content)} car.) : {qr.reference_content[:120]!r}...")
    print()

    # --- Étape 4 (le vrai objet de ce test) : Question_Attachment_Agent RÉEL
    # avec les embeddings RÉELS (fix du 2026-08-18) ---
    context_student = AgentExecutionContext(
        trace_id=trace_id, flow_type="student_evaluation", exercise_id=exercise_id,
        submission_id=uuid.uuid4(),
    )
    attachment_agent = QuestionAttachmentAgent()
    result = await attachment_agent.execute(
        raw_blocks=student_blocks, questions=question_refs, context=context_student,
    )

    print(f"=== Question_Attachment_Agent : {len(result.decisions)} décision(s) ===\n")
    level_labels = {1: "Label", 2: "Embeddings cosinus", 3: "Arbitrage LLM", 4: "Orphelin"}
    for d in result.decisions:
        order = next((qr.order for qr in question_refs if qr.question_id == d.question_id), None)
        print(
            f"  [Niveau {d.level_used} — {level_labels.get(d.level_used, '?')}] "
            f"-> Q{order if order is not None else '—'} "
            f"(evidence_level={d.evidence_level}, confiance={d.confidence_score:.3f})"
        )
        print(f"      {d.justification[:220]}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
