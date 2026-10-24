"""
Sonde embeddings pour Question_Attachment_Agent (Agent 2) — teste UNIQUEMENT
si un VRAI système d'embeddings (Gemini, `gemini-embedding-001`) sépare
correctement des contenus appartenant à des sous-tâches différentes du même
exercice, en remplacement de `_embed_text` dans
app/agents/Question_Attachment_Agent.py qui est actuellement une fonction
FACTICE déterministe (cf. son docstring : "override en prod par API
embedding" — jamais réellement branchée).

SANS modifier Question_Attachment_Agent.py : ce script réutilise juste
`_cosine_similarity` (import direct, code identique à celui réellement
utilisé au Niveau 2) et Settings.QUESTION_ATTACHMENT_COSINE_THRESHOLD /
_ORPHAN_SIMILARITY_THRESHOLD pour juger si un match "passerait" tel quel
dans le vrai agent.

Données de test : le document.pdf déjà utilisé pour Agent 1 n'a qu'UNE
question globale (le problème du treillis), donc ce script simule 7
"questions" à partir de ses 7 sous-étapes (1° REFORMULAR LA TAREA ... 7°
RETROALIMENTACIÓN, cf. agents_tests/gemini_ocr_dump.txt) : chaque
reference_content ci-dessous est un condensé fidèle du contenu RÉELLEMENT
extrait par le test Gemini OCR (pas inventé). Les blocs de test sont
d'autres extraits réels du même document (reformulations différentes,
notamment le flowchart de la page 10), pour éviter de tester une
correspondance mot-pour-mot triviale.

Prérequis (déjà en place après le test OCR Gemini) :
    - langchain_google_genai installé
    - GOOGLE_API_KEY dans .env

Lancer depuis la racine du projet :

    .venv/Scripts/python.exe agents_tests/step2_test_embeddings_probe.py
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.agents.Question_Attachment_Agent import _cosine_similarity
from app.core.config import settings

EMBEDDING_MODEL_NAME = "models/gemini-embedding-001"

# Seuil de test — settings.QUESTION_ATTACHMENT_COSINE_THRESHOLD (0.15 en prod) a été
# calibré pour _embed_text (fonction factice à base de hash d'octets), pas pour des
# embeddings sémantiques réels : sur le 1er passage de ce script, les deltas obtenus
# (0.038 à 0.115) ne dépassaient JAMAIS 0.15, donc tout tombait en Niveau 3. 0.05 est une
# valeur provisoire à valider, pas une valeur finale (5 échantillons, un seul document).
TEST_COSINE_THRESHOLD = 0.05

# --- 7 "questions" simulées à partir des 7 sous-étapes réelles du document ---
# NB : chaque reference_content doit contenir un niveau de détail/vocabulaire
# comparable aux autres (ce que serait un vrai SolutionVariant.content en
# prod) — une référence trop maigre (juste la consigne, sans vocabulaire de
# raisonnement) biaise mécaniquement le classement vers les références plus
# riches, indépendamment du sujet réel. Constaté sur Q6 : voir "réponse
# manuscrite p.15" dans TEST_BLOCKS, mal classée avec la version courte de
# la référence, correctement classée (1er, delta=0.056) une fois enrichie.
QUESTIONS = [
    {
        "label": "1° REFORMULAR LA TAREA",
        "reference_content": (
            "Analiza la pregunta: ¿qué se te pregunta en el ejercicio? El valor máximo de P "
            "que puede soportar la cercha. A partir de la información presentada en el "
            "ejercicio, ¿cuál es la información importante y necesaria para responder a la "
            "pregunta? Las dimensiones de la cercha. Los valores de los axiles."
        ),
    },
    {
        "label": "2° SUBTAREAS",
        "reference_content": (
            "¿Necesitas datos adicionales que no se le hayan facilitado? Valor de la σ_adm. "
            "Tablas de pandeo. Esbeltez de las barras con distinta longitud de la 3. Longitud "
            "de las barras 5 y 7. ¿Se puede dividir la tarea en varias mini tareas? Calcular "
            "los esfuerzos por nudos. Calcular las tensiones de las barras."
        ),
    },
    {
        "label": "3° RESOLVER SUBTAREAS",
        "reference_content": (
            "Observar cómo son las cargas y la estructura. Al ser una cercha con cargas cuya "
            "resultante cae sobre el apoyo fijo, toda la carga se la lleva este apoyo y el "
            "otro nada. Por tanto, las barras del apoyo móvil (3 y 4) no tendrán ningún "
            "esfuerzo. El resto de estructura es simétrica, por lo que las barras 5 y 7, así "
            "como 1 y 2, tendrán el mismo valor. Por último, la barra 6 soporta la carga P "
            "directamente. Para finalizar, haríamos uso de la tensión admisible del material "
            "para calcular P ya que conocemos el axil que va en función de esta variable."
        ),
    },
    {
        "label": "4° DONDE SE PODRÍA USAR LA SOLUCIÓN",
        "reference_content": (
            "¿Qué otro tipo de problema podrías resolver con la solución que has dado? "
            "Cualquier problema que involucre una cercha ya sea para calculo de esfuerzos en "
            "las barras como para cálculos de esbeltez, diámetro mínimo, etc."
        ),
    },
    {
        "label": "5° SOLUCIÓN",
        "reference_content": (
            "Acero S275, σ_max = 275 MPa. Comprobación a compresión: σ_max = σ = N/A · ω = "
            "6P·10³/(π·30²/4) · 1,1, P = 29KN. Comprobación a tracción: σ_max = σ = N/A, "
            "σ5 = 3P√5·10³/(π·30²/4), P = 28KN. Finalmente, el esfuerzo que limita la carga "
            "P es el de la barra 5."
        ),
    },
    {
        "label": "6° EVALUAR SOLUCIÓN",
        "reference_content": (
            "¿Tiene sentido el resultado obtenido? Vuelve a Q1.2, ¿es ésta la respuesta a la "
            "pregunta? ¿Es tu solución la mejor, o puedes sugerir una mejor? Justifica evaluando "
            "si el razonamiento aplicado -identificar la simetría de la cercha, el comportamiento "
            "de los apoyos fijo y móvil, y la distribución de las cargas entre las barras- "
            "permitió reducir el número de incógnitas del problema de forma eficiente."
        ),
    },
    {
        "label": "7° RETROALIMENTACIÓN",
        "reference_content": (
            "¿Has tenido alguna dificultad para entender lo que se te pedía en este "
            "ejercicio? ¿Te ha resultado útil seguir esta estructura para resolver el "
            "problema?"
        ),
    },
]

# --- blocs de test : reformulations/extraits réels différents du texte de référence ---
TEST_BLOCKS = [
    {
        "label": "flowchart p.10 (paraphrase schématique de la résolution)",
        "text": (
            "Apoyo fijo se lleva toda la carga. Apoyo móvil sin reacción. Axil en 3 y 4 igual "
            "a 0. Cercha simétrica. Axil en 5 y 7 y en 1 y 2 iguales. Axil en 6 igual a la "
            "carga P."
        ),
        "expected_label": "3° RESOLVER SUBTAREAS",
    },
    {
        "label": "réponse manuscrite p.15",
        "text": (
            "Si, ya que nos hemos quitado el mayor numero de incógnitas razonando el "
            "comportamiento de la cercha ante la distribución de las cargas."
        ),
        "expected_label": "6° EVALUAR SOLUCIÓN",
    },
    {
        "label": "réponses p.16-17",
        "text": (
            "¿Has tenido alguna dificultad para entender lo que se te pedía en este "
            "ejercicio? No. ¿Te ha resultado útil seguir esta estructura para resolver el "
            "problema? Si."
        ),
        "expected_label": "7° RETROALIMENTACIÓN",
    },
    {
        "label": "réponse p.11 (généralisation)",
        "text": (
            "Cualquier problema que involucre una cercha ya sea para calculo de esfuerzos en "
            "las barras como para cálculos de esbeltez, diámetro mínimo, etc... Si la carga "
            "es simétrica y las barras también, se pueden usar los mismos pasos que antes."
        ),
        "expected_label": "4° DONDE SE PODRÍA USAR LA SOLUCIÓN",
    },
    {
        "label": "bloc table+équations p.13",
        "text": (
            "Valores de ω para Coeficiente de imperfección tipo c. Comprobación a "
            "compresión. σ1 = 6P·10³/(π·30²/4)·1,1. P = 29KN. Comprobación a tracción. "
            "σ5 = 3P√5·10³/(π·30²/4). P = 28KN."
        ),
        "expected_label": "5° SOLUCIÓN",
    },
]


async def main() -> None:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY absente de l'environnement / .env — arrêt.")
        sys.exit(1)

    embedder = GoogleGenerativeAIEmbeddings(model=EMBEDDING_MODEL_NAME, google_api_key=api_key)

    print(f"--- Embedding de {len(QUESTIONS)} référence(s) et {len(TEST_BLOCKS)} bloc(s) de test avec {EMBEDDING_MODEL_NAME} ---\n")

    ref_embeddings = await embedder.aembed_documents([q["reference_content"] for q in QUESTIONS])
    block_embeddings = await embedder.aembed_documents([b["text"] for b in TEST_BLOCKS])

    correct = 0
    for block, block_emb in zip(TEST_BLOCKS, block_embeddings):
        similarities = [_cosine_similarity(block_emb, ref_emb) for ref_emb in ref_embeddings]
        ranked = sorted(range(len(similarities)), key=lambda i: similarities[i], reverse=True)
        best_idx, second_idx = ranked[0], ranked[1]
        best_sim, second_sim = similarities[best_idx], similarities[second_idx]
        delta = best_sim - second_sim
        best_label = QUESTIONS[best_idx]["label"]
        is_correct = best_label == block["expected_label"]
        correct += is_correct

        if best_sim < settings.QUESTION_ATTACHMENT_ORPHAN_SIMILARITY_THRESHOLD:
            level = "NIVEAU 4 (orphelin)"
        elif delta >= TEST_COSINE_THRESHOLD:
            level = "NIVEAU 2 (accepté direct)"
        else:
            level = "NIVEAU 3 (ambigu -> arbitrage LLM)"

        mark = "OK" if is_correct else "FAUX"
        print(f"[{mark}] {block['label']}")
        print(f"    attendu   : {block['expected_label']}")
        print(f"    meilleur  : {best_label} (sim={best_sim:.3f})")
        print(f"    2e        : {QUESTIONS[second_idx]['label']} (sim={second_sim:.3f}, delta={delta:.3f})")
        print(f"    seuil testé : {TEST_COSINE_THRESHOLD} (prod actuel : {settings.QUESTION_ATTACHMENT_COSINE_THRESHOLD})")
        print(f"    verdict simulé : {level}")
        print()

    print(f"--- {correct}/{len(TEST_BLOCKS)} bloc(s) correctement classés en meilleur candidat ---")


if __name__ == "__main__":
    asyncio.run(main())
