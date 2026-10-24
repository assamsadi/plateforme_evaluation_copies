"""
Tests du timeout explicite par TaskType (audit "garanties transverses",
Plan C) — jusqu'ici absent : aucun champ timeout sur ModelSpec, rien passé
aux constructeurs ChatGroq/ChatOpenAI.
"""
import asyncio
import time

import pytest
from langchain_openai import ChatOpenAI

from app.model_registry.models import ModelProvider, ModelSpec, TaskType
from app.model_registry.providers import create_llm_from_spec
from app.model_registry.registry import ModelRegistry, registry


def test_model_spec_has_default_timeout():
    spec = ModelSpec(provider=ModelProvider.GROQ, model_name="llama-3.3-70b-versatile")
    assert spec.timeout_seconds == 60


def test_vision_tasks_get_longer_timeout_than_text_tasks():
    vision_specs = registry.get_specs_for_task(TaskType.OCR_VISION)
    text_specs = registry.get_specs_for_task(TaskType.DOCUMENT_STRUCTURING)

    assert all(s.timeout_seconds == 90 for s in vision_specs)
    assert all(s.timeout_seconds == 45 for s in text_specs)
    assert vision_specs[0].timeout_seconds > text_specs[0].timeout_seconds


def test_contestation_verification_uses_vision_timeout():
    """Chaîne vision (Cas A/C relisent une image), même timeout qu'OCR_VISION."""
    specs = registry.get_specs_for_task(TaskType.CONTESTATION_VERIFICATION)
    assert all(s.timeout_seconds == 90 for s in specs)


def test_unregistered_task_falls_back_to_text_timeout():
    unregistered_registry = ModelRegistry(config={})
    specs = unregistered_registry.get_specs_for_task(TaskType.FEEDBACK_GENERATION)
    assert all(s.timeout_seconds == 45 for s in specs)


def test_create_llm_from_spec_passes_timeout_to_groq(monkeypatch):
    monkeypatch.setattr("app.model_registry.providers.settings.GROQ_API_KEY", "dummy-key")
    spec = ModelSpec(
        provider=ModelProvider.GROQ, model_name="llama-3.3-70b-versatile", timeout_seconds=45,
    )
    llm, http_client = create_llm_from_spec(spec)
    assert llm.request_timeout == 45.0
    assert http_client.timeout.read == 45.0


def test_create_llm_from_spec_passes_timeout_to_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    spec = ModelSpec(
        provider=ModelProvider.OPENAI, model_name="gpt-4o-mini", timeout_seconds=90,
    )
    llm, http_client = create_llm_from_spec(spec)
    assert llm.request_timeout == 90.0
    assert http_client.timeout.read == 90.0


async def _start_slow_server(
    delay_seconds: float,
) -> tuple[asyncio.AbstractServer, int, list[float]]:
    """
    Serveur TCP local qui accepte la connexion mais ne répond qu'après
    delay_seconds — jamais un mock au niveau transport (httpx.MockTransport
    contourne le mécanisme de timeout réel, constaté : un handler qui fait
    juste `await asyncio.sleep()` dans un MockTransport n'est PAS coupé par
    le timeout du client, le timeout httpx s'applique aux vraies opérations
    socket, pas à un transport de test). Ce serveur, lui, exerce le vrai
    chemin réseau localhost.

    Enregistre aussi l'horodatage de CHAQUE tentative de connexion reçue
    (attempt_times) — nécessaire pour isoler la durée d'une tentative
    individuelle du total agrégé (retries + backoff inclus).
    """
    attempt_times: list[float] = []

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        attempt_times.append(time.monotonic())
        await reader.read(4096)
        await asyncio.sleep(delay_seconds)
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port, attempt_times


@pytest.mark.anyio
async def test_timeout_is_actually_enforced_at_execution_not_just_passed():
    """
    Preuve d'exécution, pas seulement de transmission au constructeur (audit
    "garanties transverses", Plan C, suite) : un serveur local délibérément
    lent (8s) avec create_llm_from_spec configuré à timeout_seconds=1 (le
    vrai chemin de production, pas une reconstruction ad hoc) doit lever une
    exception de timeout nettement AVANT la fin des 8s simulées — sinon
    timeout_seconds ne serait qu'une valeur inerte, jamais réellement
    appliquée par le client HTTP sous-jacent.
    """
    server, port, _attempt_times = await _start_slow_server(delay_seconds=8.0)
    try:
        import os
        original_key = os.environ.get("OPENAI_API_KEY")
        original_base_url = os.environ.get("OPENAI_BASE_URL")
        os.environ["OPENAI_API_KEY"] = "dummy-key"
        os.environ["OPENAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
        try:
            spec = ModelSpec(
                provider=ModelProvider.OPENAI, model_name="gpt-4o-mini", timeout_seconds=1,
            )
            llm, http_client = create_llm_from_spec(spec)

            start = time.monotonic()
            try:
                with pytest.raises(Exception):
                    await llm.ainvoke("Bonjour")
            finally:
                await http_client.aclose()
            elapsed = time.monotonic() - start
        finally:
            for key, value in (("OPENAI_API_KEY", original_key), ("OPENAI_BASE_URL", original_base_url)):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    finally:
        server.close()
        await server.wait_closed()

    # Coupé bien avant les 8s simulées (marge large pour absorber les
    # tentatives de retry internes au SDK, observées ~4.5s en pratique avec
    # timeout_seconds=1) — la preuve recherchée : timeout_seconds a
    # réellement interrompu l'attente, pas seulement été stocké.
    #
    # Ce test seul ne prouve QUE l'agrégat (retries + backoff inclus) reste
    # raisonnable — il ne dit rien sur la durée d'UNE tentative individuelle
    # (celle-ci pourrait en théorie dépasser largement timeout_seconds si le
    # total agrégé restait par ailleurs sous la marge). Isolation d'une
    # tentative unique : cf. test_single_attempt_is_cut_at_configured_
    # timeout_not_just_the_aggregate ci-dessous.
    assert elapsed < 6.5


@pytest.mark.anyio
async def test_single_attempt_is_cut_at_configured_timeout_not_just_the_aggregate():
    """
    Isole la durée d'UNE SEULE tentative (avant tout retry), pour prouver
    que timeout_seconds est respecté à ce niveau précis — pas seulement que
    le total agrégé (retries + backoff) reste sous une marge large (déjà
    couvert par test_timeout_is_actually_enforced_at_execution_not_just_
    passed, mais insuffisant seul : un total raisonnable pourrait en théorie
    masquer une tentative individuelle largement hors budget si peu de
    retries avaient lieu).

    max_retries=0 est passé À LA CONSTRUCTION (pas en mutant l'attribut
    après coup sur l'objet retourné par create_llm_from_spec — vérifié :
    ça ne suffit PAS, le client HTTP interne est déjà construit avec le
    max_retries par défaut du SDK openai à ce moment-là, la mutation
    post-construction ne s'y propage pas, constaté empiriquement : 3
    tentatives malgré `llm.max_retries = 0` après coup). Cette construction
    manuelle reste fidèle au timeout réellement configuré par Plan C
    (spec.timeout_seconds), seul max_retries diffère, nécessairement, pour
    isoler une tentative unique.
    """
    server, port, attempt_times = await _start_slow_server(delay_seconds=8.0)
    try:
        spec = ModelSpec(
            provider=ModelProvider.OPENAI, model_name="gpt-4o-mini", timeout_seconds=1,
        )
        llm = ChatOpenAI(
            api_key="dummy-key",
            base_url=f"http://127.0.0.1:{port}/v1",
            model=spec.model_name,
            timeout=spec.timeout_seconds,
            max_retries=0,
        )

        start = time.monotonic()
        with pytest.raises(Exception):
            await llm.ainvoke("Bonjour")
        elapsed = time.monotonic() - start
    finally:
        server.close()
        await server.wait_closed()

    # Exactement une tentative — la mesure ci-dessous porte bien sur UNE
    # tentative isolée, pas un agrégat de plusieurs.
    assert len(attempt_times) == 1

    # La tentative unique est coupée près de timeout_seconds=1 (observé
    # ~1.14s en pratique — connexion + traitement inclus), jamais laissée
    # dériver vers les 8s simulées : preuve que le paramètre configuré est
    # respecté au niveau d'UNE tentative précise, pas seulement en moyenne.
    assert elapsed < 4.0

