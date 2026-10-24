"""
Sonde Niveau 3 (arbitrage LLM) pour Question_Attachment_Agent (Agent 2) —
teste les 2 cas restés ambigus après step2_test_embeddings_probe.py (delta
cosinus < TEST_COSINE_THRESHOLD=0.05) en appelant DIRECTEMENT la vraie
méthode privée `QuestionAttachmentAgent._llm_arbitration` (jamais dupliquée
ni modifiée) — donc le vrai prompt (QUESTION_ATTACHMENT_SYSTEM_PROMPT), le
vrai parsing JSON, et un vrai appel LLM via invoke_llm_with_fallback
(TaskType.DOCUMENT_STRUCTURING : Groq llama-3.3-70b-versatile -> OpenAI
gpt-4o-mini, texte seul, aucun override de registre nécessaire ici
contrairement aux sondes OCR — ces deux fournisseurs sont déjà enregistrés).

Réutilise les mêmes 7 "questions" (pseudo-découpage du même document en
sous-étapes) et les 2 blocs ambigus identifiés par step2_test_embeddings_
probe.py : "réponse manuscrite p.15" (delta=0.000, mal classé par
embeddings) et "réponse p.11 (généralisation)" (delta=0.038, bien classé
mais sous le seuil). Aucun fichier de app/ modifié.

Prérequis : les mêmes que step2_test_embeddings_probe.py (GOOGLE_API_KEY
pour re-calculer les embeddings de ranking) + GROQ_API_KEY déjà en place
dans .env (déjà utilisée pour Agent 1).

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step2_test_llm_arbitration_probe.py
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

from app.agents.context import AgentExecutionContext
from app.agents.Question_Attachment_Agent import QuestionAttachmentAgent, QuestionRef, _cosine_similarity
from app.domain.models.assessment.extraction_correction import ExtractionContentType
from step2_test_embeddings_probe import EMBEDDING_MODEL_NAME, QUESTIONS, TEST_BLOCKS

# Les 2 cas restés ambigus au seuil 0.05 (cf. sortie de step2_test_embeddings_probe.py) :
AMBIGUOUS_BLOCK_LABELS = ["réponse manuscrite p.15", "réponse p.11 (généralisation)"]


async def main() -> None:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    google_key = os.environ.get("GOOGLE_API_KEY")
    if not google_key:
        print("GOOGLE_API_KEY absente — nécessaire pour recalculer le ranking par embeddings.")
        sys.exit(1)

    # --- Reconstruction des vraies QuestionRef (dataclass réel de l'agent) ---
    dummy_exercise_id = uuid.uuid4()
    questions = [
        QuestionRef(
            question_id=uuid.uuid4(),
            exercise_id=dummy_exercise_id,
            order=i + 1,
            statement=q["label"],
            section_order=None,
            reference_content=q["reference_content"],
            reference_summary=q["reference_content"][:150],
            position_in_section=None,
        )
        for i, q in enumerate(QUESTIONS)
    ]

    embedder = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, google_api_key=google_key)
    ref_embeddings = await embedder.aembed_documents([q["reference_content"] for q in QUESTIONS])

    ambiguous_blocks = [b for b in TEST_BLOCKS if b["label"] in AMBIGUOUS_BLOCK_LABELS]
    block_embeddings = await embedder.aembed_documents([b["text"] for b in ambiguous_blocks])

    agent = QuestionAttachmentAgent()
    context = AgentExecutionContext(trace_id=str(uuid.uuid4()), flow_type="student_evaluation")

    print(f"--- Arbitrage LLM (Niveau 3) sur {len(ambiguous_blocks)} bloc(s) ambigu(s) ---\n")

    for block_idx, (block, block_emb) in enumerate(zip(ambiguous_blocks, block_embeddings)):
        similarities = [_cosine_similarity(block_emb, ref_emb) for ref_emb in ref_embeddings]
        top_indices = sorted(range(len(similarities)), key=lambda i: similarities[i], reverse=True)[:3]

        fake_block = SimpleNamespace(
            content_type=ExtractionContentType.TEXT,
            prediction_ocr=block["text"],
            student_label=None,
        )

        verdict = await agent._llm_arbitration(
            block=fake_block,
            block_idx=block_idx,
            questions=questions,
            top_indices=top_indices,
            similarities=similarities,
            context=context,
        )

        chosen_label = next(
            (q.statement for q in questions if q.question_id == verdict.question_id), None,
        )
        is_correct = chosen_label == block["expected_label"]
        mark = "OK" if is_correct else ("AMBIGU/ORPHELIN" if verdict.question_id is None else "FAUX")

        print(f"[{mark}] {block['label']}")
        print(f"    attendu     : {block['expected_label']}")
        print(f"    verdict LLM : evidence_level={verdict.evidence_level.value} question={chosen_label}")
        print(f"    confiance   : {verdict.confidence_score:.2f} — modèle : {verdict.model_used}")
        print(f"    justification : {verdict.justification}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
