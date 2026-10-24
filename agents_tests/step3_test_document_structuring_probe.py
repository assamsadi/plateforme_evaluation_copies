"""
Sonde pour Document_Structuring_Agent (Agent 3) — appelle DIRECTEMENT la
vraie classe de production `DocumentStructuringAgent` (import réel, jamais
dupliquée) avec de vrais RawExtractedBlock reconstruits à partir du dump
JSON produit par step1_test_ocr_gemini_probe.py (agents_tests/gemini_ocr_
dump.json) — donc les VRAIS 17 pages du VRAI OCR Gemini de ce document,
sans rappeler l'API vision (gratuit, instantané).

Contrairement aux agents 1 et 2, aucun contournement de registre n'est
nécessaire ici : le LLM de classification (TaskType.DOCUMENT_STRUCTURING,
texte seul, Groq llama-3.3-70b-versatile -> OpenAI gpt-4o-mini) utilise des
fournisseurs déjà enregistrés dans app/model_registry/*. Aucun fichier de
app/ modifié.

document.pdf est un document PROFESSEUR (énoncé + correction dans le même
fichier) — exactement le cas d'usage prévu pour cet agent (contrairement à
Agent 2, testé avec des données simulées faute de vraies Questions en base).

Prérequis :
    - agents_tests/gemini_ocr_dump.json doit exister (relancer
      step1_test_ocr_gemini_probe.py si absent ou périmé)
    - GROQ_API_KEY dans .env (déjà utilisée pour Agent 1/2)

Lancer depuis la racine du projet (document entier, 147 blocs — risque de
dépasser le quota journalier Groq gratuit, ~100 000 TPD) :

    .venv/Scripts/python.exe agents_tests/step3_test_document_structuring_probe.py

Ou limité à des pages précises (liste séparée par des virgules, reste sous
le quota) — ex. les 2 pages concernées par le bug de schéma STRUCTURE
(page 2 = MULTI_COLUMN_LIST, page 13 = TABLE) :

    .venv/Scripts/python.exe agents_tests/step3_test_document_structuring_probe.py 2,13
"""
import asyncio
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.agents.context import AgentExecutionContext
from app.agents.Document_Structuring_Agent import DocumentStructuringAgent
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionEvidenceLevel
from app.domain.schemas.submission_schemas import RawExtractedBlock

DUMP_JSON_PATH = Path(__file__).resolve().parent / "gemini_ocr_dump.json"


def _normalize_structure_content(content: dict | str | None) -> dict | str | None:
    """
    Contournement de TEST UNIQUEMENT (rien dans app/ n'est modifié) : Gemini ne respecte
    pas toujours le schéma imposé par le prompt pour les sous-éléments de STRUCTURE (cf.
    app/prompts/ocr_extraction_prompt.py, section "Schémas structured_content pour
    STRUCTURE") — il produit parfois des chaînes brutes là où rows/cells, columns et
    fields attendent des listes de dicts avec is_struck_through. Sans ça,
    filter_structure_elements_struck_only (app/agents/ocr_block_utils.py) plante avec
    AttributeError dès qu'il rencontre une cellule/colonne non conforme (constaté sur la
    page 2 "columns" et la page 13 "rows"/"cells" de ce document).

    Ne corrige PAS le comportement de Gemini ni le code de production — reformate juste
    les données ici pour pouvoir observer le reste du comportement de Document_
    Structuring_Agent sur les blocs sains.
    """
    if not isinstance(content, dict):
        return content
    content = dict(content)

    def _as_item(x: object) -> dict:
        return x if isinstance(x, dict) else {"content": str(x), "origin": "PRINTED", "is_struck_through": False}

    if "rows" in content:
        content["rows"] = [
            {"cells": [_as_item(c) for c in row.get("cells", [])]}
            for row in content["rows"]
        ]

    if "columns" in content:
        norm_columns = []
        for col in content["columns"]:
            if isinstance(col, list):
                norm_columns.append([_as_item(item) for item in col])
            elif isinstance(col, str):
                # Colonne entière regroupée en une seule string par Gemini (schéma non
                # respecté) — découpage en items séparés pour rester exploitable.
                parts = [p.strip("• \n\t") for p in col.split("\n") if p.strip("• \n\t")]
                norm_columns.append([_as_item(p) for p in parts] or [_as_item(col)])
            else:
                norm_columns.append([_as_item(col)])
        content["columns"] = norm_columns

    if "fields" in content:
        content["fields"] = [_as_item(f) for f in content["fields"]]

    return content


def _load_raw_blocks(pages: set[int] | None = None) -> list[RawExtractedBlock]:
    """
    Reconstruction fidèle à OCRExtractionAgent.execute() (mêmes règles de mapping, cf. son code).

    pages : si fourni, ne garde que ces numéros de page précis — utile pour rester sous un
    quota fournisseur (ex. TPD Groq) en réduisant le volume de blocs à classifier plutôt que
    de tout envoyer d'un coup, tout en ciblant les pages les plus utiles à tester.
    """
    if not DUMP_JSON_PATH.exists():
        print(f"{DUMP_JSON_PATH} introuvable — relancer step1_test_ocr_gemini_probe.py d'abord.")
        sys.exit(1)

    payload = json.loads(DUMP_JSON_PATH.read_text(encoding="utf-8"))
    blocks: list[RawExtractedBlock] = []
    for page in payload["pages"]:
        if page.get("error"):
            continue
        if pages is not None and page["page_num"] not in pages:
            continue
        for i, b in enumerate(page["blocks"]):
            structured_output = b.get("structured_content")
            if b["content_type"] == "STRUCTURE":
                structured_output = _normalize_structure_content(structured_output)
            blocks.append(RawExtractedBlock(
                image_crop_path=f"test/page{page['page_num']}/block{i}.png",
                content_type=b["content_type"],
                structure_type=b.get("structure_type"),
                prediction_ocr=b["raw_text"] or "",
                structured_output=structured_output,
                confidence_score=Decimal(str(b.get("model_self_confidence", 0.9))),
                reconstruction_confidence=(
                    Decimal(str(b["reconstruction_confidence"]))
                    if b.get("reconstruction_confidence") is not None
                    else None
                ),
                bounding_box=b.get("bounding_box") or {},
                page_number=page["page_num"],
                block_order_index=i,
                student_label=b.get("student_label"),
                origin=b.get("origin"),
                is_struck_through=b.get("is_struck_through", False),
                evidence_level=(
                    ExtractionEvidenceLevel.LABEL_EXPLICITE
                    if b.get("student_label")
                    else ExtractionEvidenceLevel.AMBIGU
                ),
            ))
    return blocks


async def main(pages: set[int] | None) -> None:
    raw_blocks = _load_raw_blocks(pages=pages)
    scope = f"pages {sorted(pages)}" if pages is not None else "toutes les pages"
    print(f"--- {len(raw_blocks)} bloc(s) reconstruit(s) depuis {DUMP_JSON_PATH.name} ({scope}) ---\n")

    agent = DocumentStructuringAgent()
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
    for c in report.correction_blocks_created[:10]:
        preview = (c["raw_text"] or "")[:80].replace("\n", " ")
        print(f"  - question_order={c['question_order']} evidence={c['evidence_level'].value} : {preview}")
    if len(report.correction_blocks_created) > 10:
        print(f"  ... (+{len(report.correction_blocks_created) - 10} autres)")

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
    page_set = {int(p) for p in sys.argv[1].split(",")} if len(sys.argv) == 2 else None
    asyncio.run(main(page_set))
