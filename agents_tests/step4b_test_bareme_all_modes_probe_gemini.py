"""
Sonde dédiée — vérifie qu'un barème "parfait" (rédigé pour porter toute
l'information structurée dont chaque correction_mode a besoin, cf.
discussion de session sur le formulaire guidé) est bien extrait à 100% par
Extraction_Verification_Agent, SANS aucune ClarificationRequest — les 7
correction_mode d'un coup, chacun avec ses champs propres :
  - solution_worked   : méthode + résultat déterminé (dans le texte de correction).
  - criteria_based    : verifiable_conditions.
  - binary_checklist  : item factuel + disqualifying=true (protocole de sécurité).
  - multiple_distinct_answers : plusieurs méthodes explicitement valides.
  - rubric_levels     : rubric_levels (grille complète, ordonnée).
  - procedural_sequence : expected_steps (ordonnés).
  - test_case_based   : test_cases (input/expected_output/visibility).
  + general_rules (règle non rattachée à un critère précis).

Contrairement à step4/step4_gemini, ce script NE PASSE PAS par
Document_Structuring_Agent (pas d'OCR à simuler) : QuestionInput/
CorrectionBlockInput sont construits directement à la main, à partir du
texte de barème rédigé pour cette sonde (question + correction combinées en
un seul bloc TEXT, comme le ferait _combine_block_text sur un vrai document
où tout est dans une seule section).

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step4b_test_bareme_all_modes_probe_gemini.py
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

import app.agents.Extraction_Verification_Agent as eva_module
from app.agents.context import AgentExecutionContext
from app.agents.Extraction_Verification_Agent import (
    CorrectionBlockInput,
    ExtractionVerificationAgent,
    QuestionInput,
)
from app.domain.models.assessment.exercise import ExerciseStatus
from app.domain.models.assessment.extraction_correction import ExtractionContentType

GEMINI_MODEL_NAME = "gemini-flash-lite-latest"
MAX_RPM = 12

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
        model=GEMINI_MODEL_NAME, google_api_key=os.environ["GOOGLE_API_KEY"], temperature=0.1,
    )
    if response_schema is not None:
        llm = llm.with_structured_output(response_schema)
    result = await llm.ainvoke(messages)
    fake_spec = SimpleNamespace(provider="gemini", model_name=GEMINI_MODEL_NAME)
    return result, fake_spec, False, {}


eva_module.invoke_llm_with_fallback = _gemini_invoke_llm_with_fallback


QUESTION_STATEMENT = (
    "Une poutre en acier est soumise aux charges indiquées sur le schéma joint. "
    "Calculez la contrainte maximale dans la poutre et vérifiez si le dimensionnement "
    "respecte la limite admissible de 235 MPa. Écrivez également une fonction qui "
    "automatise ce calcul de vérification."
)

CORRECTION_TEXT = """CORRECTION ATTENDUE :
On calcule les réactions d'appui, on trace le diagramme du moment fléchissant, on
identifie le moment maximal M_max, on calcule la contrainte associée sigma_max =
M_max * v / I, puis on conclut sur la validité du dimensionnement par comparaison
à la limite admissible de 235 MPa.

BARÈME (10 points)

Critère 1 — Résolution du problème (3 points)
Calcul complet du moment fléchissant maximal et de la contrainte associée, selon
la méthode des sections vue en cours. Le résultat final attendu est sigma_max
<= 235 MPa, avec conclusion explicite sur la validité du dimensionnement.

Critère 2 — Conditions à respecter (2 points)
La copie doit satisfaire les éléments suivants, chacun vérifiable indépendamment :
- mention explicite du moment fléchissant maximal calculé,
- mention explicite de la contrainte admissible du matériau utilisé,
- conclusion claire sur la validité ou non du dimensionnement.

Critère 3 — Présence du schéma de la structure (0,5 point)
La copie doit contenir un schéma de la poutre avec les charges et appuis
représentés. Toute violation du protocole de sécurité décrit en annexe annule
la totalité des points de la question, peu importe le reste.

Critère 4 — Méthode de résolution alternative (1 point)
Plusieurs méthodes sont acceptées pour arriver au résultat (méthode des sections,
méthode énergétique, ou utilisation directe des formulaires de RDM) : toute
méthode correcte menant au bon résultat est valable, il n'y a pas de démonstration
unique imposée.

Critère 5 — Qualité de la rédaction (1,5 point)
Grille de niveaux :
- Excellent : rédaction claire, structurée, chaque étape justifiée, notations
  cohérentes de bout en bout.
- Satisfaisant : rédaction compréhensible mais avec des étapes peu justifiées ou
  des notations incohérentes par endroits.
- Insuffisant : rédaction confuse, étapes manquantes ou non justifiées, notations
  incohérentes.

Critère 6 — Respect du protocole de vérification (1 point)
Les étapes suivantes doivent apparaître dans cet ordre :
1) Identifier les charges appliquées et les appuis.
2) Calculer les réactions d'appui.
3) Tracer le diagramme du moment fléchissant.
4) Identifier le moment maximal et calculer la contrainte associée.

Critère 7 — Fonction de vérification (code) (1 point)
Écrire une fonction contrainte_max(M, I, v) qui retourne la contrainte maximale.
Cas de test :
- Entrée M=5000, I=0.0002, v=0.05 -> sortie attendue 1250000 (cas visible).
- Entrée M=8000, I=0.00025, v=0.06 -> sortie attendue 1920000 (cas caché).
Aucun code de référence n'est fourni, uniquement ces cas de test.

RÈGLES GÉNÉRALES
Toutes les contraintes doivent être exprimées en MPa, sans unité intermédiaire
non convertie.
"""


async def main() -> None:
    context = AgentExecutionContext(
        trace_id=str(uuid.uuid4()), flow_type="exercise_setup", exercise_id=uuid.uuid4(),
    )
    question_id = uuid.uuid4()
    question = QuestionInput(question_id=question_id, order=1, statement=QUESTION_STATEMENT, section_order=1)
    block = CorrectionBlockInput(
        block_id=uuid.uuid4(), content_type=ExtractionContentType.TEXT, raw_text=CORRECTION_TEXT,
    )

    agent = ExtractionVerificationAgent()
    report = await agent.execute(
        questions=[question],
        blocks_by_question={question_id: [block]},
        exercise_status=ExerciseStatus.DRAFT,
        context=context,
    )

    qres = report.questions[0]
    print(f"decomposition_error : {qres.decomposition_error}")
    print(f"bareme_error : {qres.bareme_error}")
    if qres.bareme is None:
        print("Aucun barème extrait — échec du test.")
        return

    print(f"\nBarème : case={qres.bareme.case} status={qres.bareme.status} total={qres.bareme.total_points}\n")
    for crit in qres.bareme.criteria:
        print(f"- {crit.label} ({crit.points} pts) mode={crit.correction_mode.value} disqualifying={crit.disqualifying}")
        if crit.verifiable_conditions:
            print(f"    verifiable_conditions ({len(crit.verifiable_conditions)}) : {crit.verifiable_conditions}")
        if crit.rubric_levels:
            print(f"    rubric_levels ({len(crit.rubric_levels)}) : {crit.rubric_levels}")
        if crit.expected_steps:
            print(f"    expected_steps ({len(crit.expected_steps)}) : {crit.expected_steps}")
        if crit.test_cases:
            print(f"    test_cases ({len(crit.test_cases)}) : {crit.test_cases}")
        if crit.reference_code is not None:
            print(f"    reference_code : {crit.reference_code!r}")
        if crit.expected_complexity is not None:
            print(f"    expected_complexity : {crit.expected_complexity!r}")

    print(f"\ngeneral_rules ({len(qres.general_rules)}) : {qres.general_rules}")

    print(f"\nClarifications sur le barème ({len(qres.clarifications)}) :")
    bareme_clarifications = [c for c in qres.clarifications if "bareme" in c.related_field]
    for cl in qres.clarifications:
        print(f"  [{cl.severity.value}] {cl.related_field} : {cl.agent_question[:150]}")

    # --- Résumé PASS/FAIL, un critère par mode attendu ---
    print("\n=== Résumé ===")
    modes_found = {crit.correction_mode.value for crit in qres.bareme.criteria}
    expected_modes = {
        "solution_worked", "criteria_based", "binary_checklist",
        "multiple_distinct_answers", "rubric_levels", "procedural_sequence", "test_case_based",
    }
    print(f"Modes attendus tous présents : {expected_modes <= modes_found} (trouvés: {sorted(modes_found)})")
    print(f"Total points == 10 : {qres.bareme.total_points == 10}")
    rubric_crit = next((c for c in qres.bareme.criteria if c.correction_mode.value == "rubric_levels"), None)
    print(f"rubric_levels non vide : {bool(rubric_crit and rubric_crit.rubric_levels)}")
    proc_crit = next((c for c in qres.bareme.criteria if c.correction_mode.value == "procedural_sequence"), None)
    print(f"expected_steps non vide : {bool(proc_crit and proc_crit.expected_steps)}")
    test_crit = next((c for c in qres.bareme.criteria if c.correction_mode.value == "test_case_based"), None)
    print(f"test_cases non vide : {bool(test_crit and test_crit.test_cases)}")
    print(f"un critère disqualifying=true : {any(c.disqualifying for c in qres.bareme.criteria)}")
    print(f"general_rules non vide : {bool(qres.general_rules)}")
    print(f"aucune clarification BLOCKING sur le barème : {not any(c.severity.value == 'blocking' for c in bareme_clarifications)}")


if __name__ == "__main__":
    asyncio.run(main())
