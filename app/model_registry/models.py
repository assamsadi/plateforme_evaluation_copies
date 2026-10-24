"""
Définitions des types de tâches AI et des spécifications de modèles LLM.
"""
from enum import StrEnum
from pydantic import BaseModel


class TaskType(StrEnum):
    OCR_VISION = "ocr_vision"
    # 2026-08-29 (backlog_bugs_c2pct.md, couche 4) — OCR du document de
    # RÉFÉRENCE du professeur (flow_type="exercise_setup"), jamais des
    # copies étudiantes (flow_type="student_evaluation", qui restent sur
    # OCR_VISION). Volume structurellement faible (un document par exercice,
    # pas un par étudiant) et impact d'une erreur maximal (une perte ici se
    # propage à TOUS les étudiants de l'exercice, contrairement à une copie
    # individuelle) — justifie un palier de modèle supérieur à OCR_VISION
    # (cf. registry.py), jamais partagé. Sélectionné par OCR_Extraction_Agent
    # selon context.flow_type, jamais par l'appelant directement.
    OCR_VISION_REFERENCE = "ocr_vision_reference"
    DOCUMENT_STRUCTURING = "document_structuring"
    QUESTION_ATTACHMENT = "question_attachment"
    SOLUTION_VARIANT_GENERATION = "solution_variant_generation"
    REASONING_GRAPH = "reasoning_graph"
    COMPARATIVE_EVALUATION = "comparative_evaluation"
    PEDAGOGICAL_EVALUATION = "pedagogical_evaluation"
    COMPETENCY_ASSESSMENT = "competency_assessment"
    FEEDBACK_GENERATION = "feedback_generation"
    CONTESTATION_VERIFICATION = "contestation_verification"
    EXTRACTION_VERIFICATION = "extraction_verification"


class ModelProvider(StrEnum):
    GROQ = "groq"
    OPENAI = "openai"
    AZURE_OPENAI = "azure_openai"
    OLLAMA = "ollama"
    GEMINI = "gemini"
    # 2e compte Google, credential GOOGLE_API_KEY_2 — jamais le même compte
    # que GEMINI. Sert de repli automatique dans la chaîne (cf. registry.py)
    # quand le 1er compte Gemini tape un mur de quota (par minute ou par
    # jour, palier gratuit) — jamais un vrai fournisseur distinct, juste un
    # 2e jeu de crédentials pour le même SDK/modèle.
    GEMINI_2 = "gemini_2"
    # 3e/4e comptes Google, credentials GOOGLE_API_KEY_3/_4 — dédiés
    # exclusivement à TaskType.DOCUMENT_STRUCTURING (cf. registry.py), jamais
    # partagés avec OCR_VISION. Motif (constaté en test réel, document C2PCT
    # 36 pages) : sans ça, l'OCR (36+ appels vision) et la classification
    # bloc par bloc (~125 appels texte) consomment le MÊME quota journalier
    # Gemini partagé — épuiser ce quota pendant l'OCR privait l'appel de
    # regroupement en questions (le plus critique, décide de TOUTE la
    # structure) de toute chance de réussir, quel que soit le plafond
    # interne MAX_LLM_CALLS_PER_THREAD. Isoler la structuration sur ses
    # propres comptes garantit qu'un épuisement côté OCR ne bloque jamais
    # le regroupement, et inversement.
    GEMINI_3 = "gemini_3"
    GEMINI_4 = "gemini_4"
    # 5e/6e/7e comptes Google, credentials GOOGLE_API_KEY_5/_6/_7 — ajoutés
    # 2026-09-11 pour la même raison que GEMINI_3/_4 : renforcer la chaîne de
    # TaskType.DOCUMENT_STRUCTURING (cf. registry.py), seul point du pipeline
    # observé bloqué par le quota gratuit sur les 4 comptes précédents en
    # conditions réelles (429 RESOURCE_EXHAUSTED sur GEMINI_3 ET GEMINI_4 le
    # même jour). Mêmes modèles/prompts, seul le jeu de crédentials change.
    GEMINI_5 = "gemini_5"
    GEMINI_6 = "gemini_6"
    GEMINI_7 = "gemini_7"
    OPENROUTER = "openrouter"


class ModelSpec(BaseModel):
    provider: ModelProvider
    model_name: str
    temperature: float = 0.1
    max_tokens: int | None = None
    supports_vision: bool = False
    # Timeout explicite par appel (audit "garanties transverses", Plan C) —
    # jusqu'ici absent : le timeout effectif était celui, non configuré,
    # des clients LangChain/httpx sous-jacents. Un dépassement devient une
    # exception de plus, absorbée par la chaîne de fallback déjà en place
    # (invoke_llm_with_fallback) — ne change rien au comportement de retry/
    # fallback existant, juste une garde-fou supplémentaire par tâche.
    timeout_seconds: int = 60
