"""
Étape 1 — teste OCR_Extraction_Agent tout seul, sur un vrai PDF (énoncé +
corrigé dans le même fichier). AUCUNE base de données, AUCUN serveur :
appelle l'agent directement.

Lancer depuis la racine du projet (là où se trouve .env) :

    .venv/Scripts/python.exe agents_tests/step1_test_ocr.py agents_tests/document.pdf

Ça fait un VRAI appel LLM vision (Groq/OpenAI) — pas gratuit, pas instantané.
"""
import asyncio
import sys
import uuid
from pathlib import Path

# Rend le package "app" importable même quand ce script est lancé comme
# fichier direct (python agents_tests/step1_test_ocr.py) — dans ce cas
# Python n'ajoute que le dossier du script à sys.path, jamais la racine du
# projet où vit le package "app".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.context import AgentExecutionContext
from app.agents.OCR_Extraction_Agent import OCRExtractionAgent


async def main(pdf_path: str) -> None:
    with open(pdf_path, "rb") as f:
        document_bytes = f.read()

    context = AgentExecutionContext(
        trace_id=str(uuid.uuid4()),
        flow_type="exercise_setup",  # "student_evaluation" pour une copie d'étudiant
    )

    agent = OCRExtractionAgent()
    print(f"--- Lancement OCR sur {pdf_path} ({len(document_bytes)} octets) ---")
    blocks = await agent.execute(document_bytes, "application/pdf", context)

    print(f"\n{len(blocks)} bloc(s) extrait(s) :\n")
    for i, b in enumerate(blocks):
        print(f"[{i}] page={b.page_number} type={b.content_type.value} confiance={b.confidence_score}")
        print(f"    origin={b.origin.value if b.origin else None} raturé={b.is_struck_through}")
        text_preview = (b.prediction_ocr or "")[:200].replace("\n", " ")
        print(f"    texte : {text_preview}")
        if b.structured_output:
            print(f"    structured_output : {str(b.structured_output)[:200]}")
        print()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python step1_test_ocr.py <chemin_vers_le_pdf>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
