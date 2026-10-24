"""
Test d'intégration RÉEL — NotebookLMService contre le vrai service
NotebookLM (§7, "Feedback Intelligent" — Partie 1/2). Exécute une vraie
opération réseau contre un compte Google authentifié (session cookies),
via une bibliothèque non officielle sur des points d'accès non documentés
— explicitement marqué, même convention que test_storage_service.py pour
Azure : ce test peut échouer pour des raisons hors de notre contrôle
(session expirée, endpoint Google changé) sans que ce soit une régression
de notre code.

Sauté proprement (pas un échec) si NOTEBOOKLM_STORAGE_PATH n'est pas
configuré dans cet environnement — jamais un prérequis pour le reste de
la suite de tests.
"""
import uuid

import pytest

from app.core.config import get_settings
from app.services.notebooklm_service import NotebookHandle, NotebookLMService

pytestmark = [pytest.mark.notebooklm_integration, pytest.mark.anyio]


@pytest.fixture(autouse=True)
def _skip_if_not_configured():
    if not get_settings().NOTEBOOKLM_STORAGE_PATH:
        pytest.skip("NOTEBOOKLM_STORAGE_PATH non configuré dans cet environnement.")


@pytest.mark.anyio
async def test_real_notebook_created_with_real_source_and_cleaned_up():
    """
    Preuve de bout en bout contre le vrai service : création réelle d'un
    notebook + source texte, puis suppression immédiate (le test ne laisse
    aucune trace dans le compte NotebookLM réel).
    """
    import notebooklm

    service = NotebookLMService()
    student_id = uuid.uuid4()

    handle = await service.create_notebook_for_feedback(
        student_id=student_id,
        competency_lines=[{
            "competency": "algorithmic_structuring",
            "mastery_level": "22.00",
            "confidence_level": "0.40",
            "is_persistent_weakness": True,
            "identified_difficulties": ["Confond boucle for/while sur les cas limites."],
            "weaknesses": ["3.1 (Boucles)"],
            "strengths": [],
        }],
        recommendations=[{
            "exercise_title": "TEST INTEGRATION - a ignorer",
            "competency_code": "algorithmic_structuring",
            "category": "remediation",
            "reason": "Faiblesse persistante en algorithmic_structuring — priorité de remédiation.",
            "difficulty_level": "facile",
        }],
    )

    try:
        assert handle is not None, (
            "Échec réel de création (session expirée / endpoint changé / réseau) — "
            "voir les logs WARNING du service pour la cause exacte."
        )
        assert isinstance(handle, NotebookHandle)
        assert handle.notebook_id

        async with notebooklm.NotebookLMClient.from_storage() as client:
            sources = await client.sources.list(handle.notebook_id)
            assert len(sources) == 1
            assert sources[0].title == "Profil de compétences et recommandations"
    finally:
        if handle is not None:
            async with notebooklm.NotebookLMClient.from_storage() as client:
                await client.notebooks.delete(handle.notebook_id)
