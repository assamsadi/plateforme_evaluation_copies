"""
Variante de step1_test_ocr.py pour tester OCR_Extraction_Agent avec un
modèle Ollama cloud (ex. gemma4:cloud) SANS toucher au registre de
production (app/model_registry/*) ni à step1_test_ocr.py.

Fonctionnement : pousse directement une surcharge dans le dict en mémoire
registry._overrides (le même mécanisme que l'API admin PUT /admin/config/
models/{task_type}, mais sans DB ni serveur) juste avant d'appeler
step1_test_ocr.main(). Purement additif — supprimer ce fichier annule
totalement l'expérimentation.

Prérequis : le serveur Ollama local doit tourner et proxier vers le modèle
cloud (`ollama run gemma4:cloud` au moins une fois, ou service Ollama actif
avec le modèle cloud accessible en local sur OLLAMA_BASE_URL, cf.
app/core/config.py — défaut http://localhost:11434).

Lancer depuis la racine du projet (là où se trouve .env) :

    .venv/Scripts/python.exe agents_tests/step1_test_ocr_ollama_override.py agents_tests/document.pdf

Pour tester un autre modèle Ollama, changer OLLAMA_MODEL_NAME ci-dessous.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.model_registry.models import ModelProvider, TaskType
from app.model_registry.registry import registry

OLLAMA_MODEL_NAME = "gemma4:cloud"
OLLAMA_TIMEOUT_SECONDS = 180  # généreux : premier appel = souvent un cold start côté modèle cloud Ollama

# Même mécanisme que ModelConfigAdminService.update_model_config, sans DB :
# seuls provider/model_name/timeout_seconds sont lus par
# ModelRegistry._apply_override (temperature/max_tokens/supports_vision
# restent hérités de l'entrée GROQ d'origine, cf. registry.py).
registry._overrides[TaskType.OCR_VISION] = SimpleNamespace(
    provider=ModelProvider.OLLAMA,
    model_name=OLLAMA_MODEL_NAME,
    timeout_seconds=OLLAMA_TIMEOUT_SECONDS,
)
# Marque le cache comme frais pour éviter que refresh_cache_if_stale()
# (appelé par invoke_llm_with_fallback à chaque appel LLM) n'essaie de
# recharger depuis la DB et écrase potentiellement cette surcharge tant que
# le TTL (30s par défaut) n'est pas écoulé.
registry._cache_loaded_at = datetime.now(timezone.utc)

from step1_test_ocr import main  # noqa: E402 (import après la surcharge, volontaire)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python step1_test_ocr_ollama_override.py <chemin_vers_le_pdf>")
        sys.exit(1)
    print(f"--- Surcharge active : OCR_VISION -> Ollama / {OLLAMA_MODEL_NAME} ---")
    asyncio.run(main(sys.argv[1]))
