"""
Fabrique des instances ChatModel LangChain pour les différents fournisseurs (Groq, OpenAI, Ollama).
"""
import logging
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.provider_credentials import get_effective_credential
from app.model_registry.models import ModelProvider, ModelSpec

logger = logging.getLogger(__name__)


def create_llm_from_spec(spec: ModelSpec) -> tuple[BaseChatModel, httpx.AsyncClient | None]:
    """
    Instancie un modèle LangChain à partir d'une ModelSpec.

    Construit et retourne explicitement le httpx.AsyncClient sous-jacent
    (jamais laissé le SDK provider le construire implicitement) : sans ça,
    chaque appel (get_llm_chain est rappelé à chaque invoke_llm_with_fallback,
    aucune mise en cache) créait un httpx.AsyncClient jamais fermé, lié à
    l'event loop actif à ce moment — diagnostiqué comme la cause du
    RuntimeError('Event loop is closed') intermittent en tests (event loop
    scopé par test, anyio_backend function-scoped). L'appelant DOIT fermer
    ce client (cf. app/llm/client.py::invoke_llm_with_fallback).

    Toute validation (clé API présente) DOIT précéder la construction du
    client HTTP, jamais l'inverse : un ValueError levé après construction
    laisserait ce client orphelin (jamais retourné, donc jamais fermable
    par l'appelant) — constaté avec la branche OPENAI/AZURE_OPENAI, qui ne
    validait rien avant de construire ChatOpenAI (le SDK openai échoue sur
    OPENAI_API_KEY absente, mais APRÈS la construction du client HTTP).

    Exception : OLLAMA et GEMINI retournent un httpx.AsyncClient de None.
    Le SDK ollama (ollama.AsyncClient, utilisé sous le capot par ChatOllama)
    ne prend en paramètre que des kwargs (async_client_kwargs) et construit
    lui-même son httpx.AsyncClient interne. ChatGoogleGenerativeAI passe
    par le SDK google-genai (gRPC/HTTP interne au SDK), pas par un client
    httpx injectable non plus. Dans les deux cas, aucun point d'injection
    pour leur passer une instance déjà construite comme pour ChatGroq/
    ChatOpenAI (http_async_client=...) — rien à fermer côté appelant ; le
    finally d'invoke_llm_with_fallback gère déjà ce cas (`if remaining_
    client is not None`).
    """
    # Les 7 variantes Gemini partagent le même SDK/modèle, seul le jeu de
    # crédentials change — cf. docstrings ModelProvider.GEMINI_2/_3/_4/_5/_6/_7
    # (models.py) pour le rôle de chacune (repli quota vs isolation OCR/
    # structuration).
    _GEMINI_CREDENTIAL_ENV_VAR = {
        ModelProvider.GEMINI: "GOOGLE_API_KEY",
        ModelProvider.GEMINI_2: "GOOGLE_API_KEY_2",
        ModelProvider.GEMINI_3: "GOOGLE_API_KEY_3",
        ModelProvider.GEMINI_4: "GOOGLE_API_KEY_4",
        ModelProvider.GEMINI_5: "GOOGLE_API_KEY_5",
        ModelProvider.GEMINI_6: "GOOGLE_API_KEY_6",
        ModelProvider.GEMINI_7: "GOOGLE_API_KEY_7",
    }

    if spec.provider not in (
        ModelProvider.GROQ, ModelProvider.OPENAI, ModelProvider.AZURE_OPENAI,
        ModelProvider.OLLAMA, ModelProvider.OPENROUTER,
        *_GEMINI_CREDENTIAL_ENV_VAR,
    ):
        raise ValueError(f"Fournisseur LLM inconnu : {spec.provider}")

    # Chantier "Configuration des modèles IA" (admin) — surcharge DB des
    # clés API (cache TTL, cf. app/core/provider_credentials.py), repli
    # sur Settings/.env si aucune surcharge n'est configurée. Lu ici (pas
    # au-dessus, dans le dispatcher) pour que la validation ET la
    # construction du client utilisent EXACTEMENT la même valeur — jamais
    # un TOCTOU entre une validation faite sur .env et un client construit
    # avec une valeur DB différente si le cache change entre-temps.
    groq_api_key = get_effective_credential("GROQ_API_KEY")
    openai_api_key = get_effective_credential("OPENAI_API_KEY")
    openrouter_api_key = get_effective_credential("OPENROUTER_API_KEY")

    if spec.provider == ModelProvider.GROQ and not groq_api_key:
        raise ValueError("GROQ_API_KEY non configurée")
    if spec.provider in (ModelProvider.OPENAI, ModelProvider.AZURE_OPENAI) and not openai_api_key:
        raise ValueError("OPENAI_API_KEY non configurée")
    if spec.provider == ModelProvider.OPENROUTER and not openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY non configurée")

    if spec.provider in _GEMINI_CREDENTIAL_ENV_VAR:
        env_var = _GEMINI_CREDENTIAL_ENV_VAR[spec.provider]
        google_api_key = get_effective_credential(env_var)
        if not google_api_key:
            raise ValueError(f"{env_var} non configurée")
        llm = ChatGoogleGenerativeAI(
            model=spec.model_name,
            google_api_key=google_api_key,
            temperature=spec.temperature,
        )
        return llm, None

    if spec.provider == ModelProvider.OLLAMA:
        llm = ChatOllama(
            model=spec.model_name,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=spec.temperature,
            num_predict=spec.max_tokens,
            async_client_kwargs={"timeout": spec.timeout_seconds},
        )
        return llm, None

    async_http_client = httpx.AsyncClient(timeout=spec.timeout_seconds)

    if spec.provider == ModelProvider.GROQ:
        llm = ChatGroq(
            api_key=groq_api_key,
            model=spec.model_name,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            timeout=spec.timeout_seconds,
            http_async_client=async_http_client,
        )

    elif spec.provider == ModelProvider.OPENROUTER:
        # OpenRouter expose une API compatible OpenAI (même client ChatOpenAI,
        # juste un base_url différent) — aucun SDK dédié nécessaire.
        llm = ChatOpenAI(
            api_key=openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            model=spec.model_name,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            timeout=spec.timeout_seconds,
            http_async_client=async_http_client,
        )

    else:  # OPENAI / AZURE_OPENAI, seuls fournisseurs restants après la validation ci-dessus
        llm = ChatOpenAI(
            api_key=openai_api_key,
            model=spec.model_name,
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            timeout=spec.timeout_seconds,
            http_async_client=async_http_client,
        )

    return llm, async_http_client
