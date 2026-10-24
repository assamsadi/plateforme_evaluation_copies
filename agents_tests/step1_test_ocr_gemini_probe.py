"""
Sonde Gemini pour OCR_VISION — teste UNIQUEMENT si ChatGoogleGenerativeAI
tient le schéma structuré PageExtractionResult sur une image de page réelle,
SANS passer par le registre (Gemini n'est pas un ModelProvider reconnu par
app/model_registry/*, donc le coup de l'override en mémoire ne marche pas
ici comme pour Ollama) et SANS modifier un seul fichier de app/.

Court-circuite volontairement le pipeline complet (pas de contrôle qualité,
pas de deskew, pas de validation LaTeX/JSON, pas d'upload de crops, pas de
relecture ciblée) : ce n'est PAS un test de bout en bout de OCRExtractionAgent,
juste un smoke-test "est-ce que Gemini répond correctement à CE schéma sur
CETTE image" avec le VRAI prompt système et le VRAI schéma de production
(importés tels quels, jamais dupliqués à la main).

Traite TOUTES les pages du PDF par défaut (nb_pages optionnel pour limiter,
ex. un essai rapide sur 5 pages). Pour rester sous les quotas gratuits
Gemini (RPM ~15 pour la famille flash-lite), les pages sont envoyées par
LOTS de BATCH_SIZE en parallèle, avec une pause de BATCH_COOLDOWN_SECONDS
entre chaque lot (fenêtre RPM qui se réinitialise) — jamais tout le document
d'un coup comme le ferait le vrai agent (OK pour 5 pages < RPM, plus pour 17).

Prérequis (aucun fichier app/ modifié, seulement l'environnement local) :
    1. pip install langchain-google-genai
    2. Ajouter dans .env : GOOGLE_API_KEY="..."

Lancer depuis la racine du projet (document entier) :

    .venv/Scripts/python.exe agents_tests/step1_test_ocr_gemini_probe.py agents_tests/document.pdf

Ou limité aux 5 premières pages :

    .venv/Scripts/python.exe agents_tests/step1_test_ocr_gemini_probe.py agents_tests/document.pdf 5

Pour changer de modèle (ex. gemini-2.5-flash-lite si le RPM de
gemini-2.5-flash est trop juste), modifier GEMINI_MODEL_NAME ci-dessous.

Écrit aussi un dump texte COMPLET (raw_text intégral, pas la preview 100
caractères affichée en console) dans agents_tests/gemini_ocr_dump.txt,
pages remises dans l'ordre du document (les lots tournent en concurrence,
donc l'ordre d'arrivée console != ordre des pages) — pour comparer
manuellement avec le PDF, page par page.
"""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz
from dotenv import load_dotenv

load_dotenv()

from app.agents.OCR_Extraction_Agent import PageExtractionResult
from app.agents.ocr_quality import convert_document_to_images
from app.prompts.ocr_extraction_prompt import OCR_EXTRACTION_SYSTEM_PROMPT

GEMINI_MODEL_NAME = "gemini-flash-lite-latest"  # gemini-2.5-flash(-lite) renvoient 404 "no longer available to
# new users" sur cette clé (vérifié en direct) — cet alias pointe vers le modèle lite recommandé actuel, jamais
# un ID daté qui peut être déprécié du jour au lendemain. Alternative pinnée équivalente au moment du test :
# "gemini-3.5-flash-lite".

BATCH_SIZE = 10  # marge sous le RPM annoncé (15) pour la famille flash-lite
BATCH_COOLDOWN_SECONDS = 65  # > 60s pour repartir sur une fenêtre RPM fraîche entre deux lots


def _truncate_pdf(pdf_path: str, max_pages: int | None) -> bytes:
    doc = fitz.open(pdf_path)
    if max_pages is not None:
        doc.select(range(min(max_pages, doc.page_count)))
    return doc.tobytes()


def _build_messages(page_num: int, image_bytes: bytes) -> list[dict]:
    """Copie exacte de la construction de messages dans OCRExtractionAgent._extract_page_blocks."""
    return [
        {"role": "system", "content": OCR_EXTRACTION_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Extrais tous les blocs de la page {page_num}."},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"},
                },
            ],
        },
    ]


async def _probe_page(llm, page_num: int, image_bytes: bytes) -> dict:
    messages = _build_messages(page_num, image_bytes)
    try:
        result: PageExtractionResult = await llm.ainvoke(messages)
        print(f"[page {page_num}] OK — {len(result.blocks)} bloc(s)")
        for b in result.blocks[:3]:
            preview = (b.raw_text or "")[:100].replace("\n", " ")
            print(f"    - {b.content_type.value} : {preview}")
        if len(result.blocks) > 3:
            print(f"    ... (+{len(result.blocks) - 3} autres)")
        return {"page_num": page_num, "blocks": [b.model_dump(mode="json") for b in result.blocks], "error": None}
    except Exception as e:
        print(f"[page {page_num}] ECHEC — {type(e).__name__}: {e}")
        return {"page_num": page_num, "blocks": [], "error": f"{type(e).__name__}: {e}"}


def _write_dump(pdf_path: str, page_results: list[dict]) -> Path:
    dump_path = Path(__file__).resolve().parent / "gemini_ocr_dump.txt"
    lines = [f"Dump OCR complet — {GEMINI_MODEL_NAME} — {pdf_path}\n{'=' * 70}\n"]
    for page in sorted(page_results, key=lambda p: p["page_num"]):
        lines.append(f"\n### PAGE {page['page_num']} " + "#" * 50)
        if page["error"]:
            lines.append(f"ECHEC : {page['error']}")
            continue
        for i, b in enumerate(page["blocks"]):
            lines.append(
                f"\n[bloc {i}] content_type={b['content_type']} structure_type={b.get('structure_type')} "
                f"origin={b.get('origin')} confiance={b.get('model_self_confidence')}"
            )
            lines.append(f"bounding_box={b.get('bounding_box')}")
            lines.append(f"raw_text:\n{b.get('raw_text')}")
            if b.get("structured_content"):
                lines.append(f"structured_content:\n{b.get('structured_content')}")
    dump_path.write_text("\n".join(lines), encoding="utf-8")
    return dump_path


def _write_json_dump(page_results: list[dict]) -> Path:
    """
    Dump JSON structuré (page_num + blocks bruts model_dump(mode="json")) —
    permet à d'autres sondes d'agent (ex. step3_test_document_structuring_
    probe.py) de reconstruire de vrais RawExtractedBlock sans rappeler
    l'API Gemini ni re-parser le dump texte.
    """
    json_path = Path(__file__).resolve().parent / "gemini_ocr_dump.json"
    payload = {
        "model": GEMINI_MODEL_NAME,
        "pages": sorted(page_results, key=lambda p: p["page_num"]),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return json_path


async def main(pdf_path: str, max_pages: int | None) -> None:
    from langchain_google_genai import ChatGoogleGenerativeAI

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY absente de l'environnement / .env — arrêt.")
        sys.exit(1)

    truncated_pdf_bytes = _truncate_pdf(pdf_path, max_pages)
    page_images = convert_document_to_images(truncated_pdf_bytes, "application/pdf")
    print(f"--- {len(page_images)} page(s) à tester avec {GEMINI_MODEL_NAME} (lots de {BATCH_SIZE}) ---\n")

    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL_NAME,
        google_api_key=api_key,
        temperature=0.1,
    ).with_structured_output(PageExtractionResult)

    all_results: list[dict] = []
    for batch_start in range(0, len(page_images), BATCH_SIZE):
        batch = page_images[batch_start:batch_start + BATCH_SIZE]
        page_nums = range(batch_start + 1, batch_start + 1 + len(batch))
        print(f"--- lot pages {list(page_nums)} ---")
        batch_results = await asyncio.gather(*[
            _probe_page(llm, page_num, img_bytes)
            for page_num, img_bytes in zip(page_nums, batch)
        ])
        all_results.extend(batch_results)
        if batch_start + BATCH_SIZE < len(page_images):
            print(f"--- pause {BATCH_COOLDOWN_SECONDS}s (respect du RPM) ---\n")
            await asyncio.sleep(BATCH_COOLDOWN_SECONDS)

    dump_path = _write_dump(pdf_path, all_results)
    json_path = _write_json_dump(all_results)
    print(f"\n--- Dump complet écrit dans {dump_path} ---")
    print(f"--- Dump JSON (réutilisable par d'autres sondes) écrit dans {json_path} ---")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage : python step1_test_ocr_gemini_probe.py <chemin_vers_le_pdf> [nb_pages]")
        sys.exit(1)
    n_pages = int(sys.argv[2]) if len(sys.argv) == 3 else None
    asyncio.run(main(sys.argv[1], n_pages))
