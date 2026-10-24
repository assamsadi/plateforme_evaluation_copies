"""
Tests unitaires — NotebookLMService (intégration NotebookLM, Partie 1/2).

Couvre le contrat central du chantier : cette intégration est best-effort,
elle ne doit JAMAIS lever d'exception vers l'appelant, quelle que soit la
cause d'échec (non configurée, bibliothèque absente, appel réseau réel qui
échoue).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.services.notebooklm_service import NotebookHandle, NotebookLMService


def _competency_line(competency="algorithmic_structuring", weaknesses=None, difficulties=None, strengths=None):
    return {
        "competency": competency,
        "mastery_level": "25.00",
        "confidence_level": "0.60",
        "is_persistent_weakness": True,
        "identified_difficulties": difficulties or [],
        "weaknesses": weaknesses or [],
        "strengths": strengths or [],
    }


def _recommendation(title="Exo bibliotheque"):
    return {
        "exercise_title": title,
        "competency_code": "algorithmic_structuring",
        "category": "remediation",
        "reason": "Faiblesse persistante — priorité de remédiation.",
        "difficulty_level": "facile",
    }


@pytest.mark.anyio
async def test_returns_none_when_not_configured():
    """NOTEBOOKLM_STORAGE_PATH absent -> intégration désactivée, jamais une exception."""
    service = NotebookLMService(storage_path=None)

    result = await service.create_notebook_for_feedback(
        student_id=uuid.uuid4(), competency_lines=[_competency_line()], recommendations=[_recommendation()],
    )

    assert result is None


@pytest.mark.anyio
async def test_reads_storage_path_from_settings_when_not_passed_explicitly():
    settings = Settings.model_construct(NOTEBOOKLM_STORAGE_PATH=None)
    service = NotebookLMService(settings=settings)

    assert service._is_configured() is False


@pytest.mark.anyio
async def test_client_failure_never_propagates_and_returns_none():
    """Broker/API NotebookLM indisponible ou en échec (mocké) -> best-effort, aucune exception ne remonte."""
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")

    with patch.object(
        notebooklm.NotebookLMClient, "from_storage",
        side_effect=RuntimeError("NotebookLM indisponible (simulé)"),
    ):
        result = await service.create_notebook_for_feedback(
            student_id=uuid.uuid4(), competency_lines=[_competency_line()], recommendations=[_recommendation()],
        )

    assert result is None


@pytest.mark.anyio
async def test_success_path_returns_notebook_handle():
    import notebooklm

    student_id = uuid.uuid4()
    service = NotebookLMService(storage_path="/fake/storage_state.json")

    mock_notebook = MagicMock(id="nb-123", title=f"Recommandations — étudiant {student_id}")
    mock_client = AsyncMock()
    mock_client.notebooks.create = AsyncMock(return_value=mock_notebook)
    mock_client.sources.add_text = AsyncMock(return_value=MagicMock(id="src-1"))

    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    with patch.object(notebooklm.NotebookLMClient, "from_storage", return_value=mock_context):
        result = await service.create_notebook_for_feedback(
            student_id=student_id,
            competency_lines=[_competency_line(weaknesses=["3.1 (Boucles)"])],
            recommendations=[_recommendation()],
        )

    assert result == NotebookHandle(notebook_id="nb-123", title=mock_notebook.title)
    mock_client.notebooks.create.assert_awaited_once()
    mock_client.sources.add_text.assert_awaited_once()
    call_kwargs = mock_client.sources.add_text.await_args.kwargs
    assert call_kwargs["notebook_id"] == "nb-123"
    assert "algorithmic_structuring" in call_kwargs["content"]
    assert "Boucles" in call_kwargs["content"]
    assert "Exo bibliotheque" in call_kwargs["content"]


@pytest.mark.anyio
async def test_feedback_text_used_as_primary_source_when_provided():
    """
    Chantier Feedback_Agent (§7) — feedback_text réel devient la source
    PRINCIPALE du notebook, jamais _build_source_content quand il est
    fourni (cf. docstring service).
    """
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")
    mock_notebook = MagicMock(id="nb-456", title="Recommandations")
    mock_client = AsyncMock()
    mock_client.notebooks.create = AsyncMock(return_value=mock_notebook)
    mock_client.sources.add_text = AsyncMock(return_value=MagicMock(id="src-1"))
    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    socratic_text = "Relis ta boucle : à quel moment vérifies-tu la condition d'arrêt ?"

    with patch.object(notebooklm.NotebookLMClient, "from_storage", return_value=mock_context):
        result = await service.create_notebook_for_feedback(
            student_id=uuid.uuid4(),
            competency_lines=[_competency_line(weaknesses=["3.1 (Boucles)"])],
            recommendations=[_recommendation()],
            feedback_text=socratic_text,
        )

    assert result is not None
    call_kwargs = mock_client.sources.add_text.await_args.kwargs
    assert call_kwargs["content"] == socratic_text
    # Jamais le texte déterministe du contournement historique quand feedback_text est fourni.
    assert "Profil de compétences de l'étudiant" not in call_kwargs["content"]


@pytest.mark.anyio
async def test_falls_back_to_build_source_content_when_feedback_text_absent():
    """Comportement best-effort préservé (Partie 1/2) — aucun appelant qui ne fournirait pas feedback_text n'est cassé."""
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")
    mock_notebook = MagicMock(id="nb-789", title="Recommandations")
    mock_client = AsyncMock()
    mock_client.notebooks.create = AsyncMock(return_value=mock_notebook)
    mock_client.sources.add_text = AsyncMock(return_value=MagicMock(id="src-1"))
    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_context.__aexit__ = AsyncMock(return_value=False)

    with patch.object(notebooklm.NotebookLMClient, "from_storage", return_value=mock_context):
        result = await service.create_notebook_for_feedback(
            student_id=uuid.uuid4(),
            competency_lines=[_competency_line(weaknesses=["3.1 (Boucles)"])],
            recommendations=[_recommendation()],
        )

    assert result is not None
    call_kwargs = mock_client.sources.add_text.await_args.kwargs
    assert "Profil de compétences de l'étudiant" in call_kwargs["content"]


def test_build_source_content_is_deterministic_and_includes_real_fields_only():
    content = NotebookLMService._build_source_content(
        competency_lines=[_competency_line(
            weaknesses=["3.1 (Boucles)"], difficulties=["Confond boucle for/while"], strengths=["Bonne décomposition"],
        )],
        recommendations=[_recommendation()],
    )

    assert "algorithmic_structuring" in content
    assert "Confond boucle for/while" in content
    assert "Boucles" in content
    assert "Bonne décomposition" in content
    assert "Exo bibliotheque" in content
    assert "faiblesse persistante" in content.lower() or "Faiblesse persistante" in content


def test_build_source_content_never_invents_a_feedback_text():
    """Aucun champ 'feedback_text' n'existe dans cette intégration — jamais halluciné, cf. docstring service."""
    content = NotebookLMService._build_source_content(competency_lines=[], recommendations=[])

    assert "feedback_text" not in content.lower()


# ---------------------------------------------------------------------------
# Partie 2/2 — formats de sortie (audio/flashcards/vidéo), best-effort
# individuellement, jamais une exception.
# ---------------------------------------------------------------------------

def _make_artifact_client(download_writes: bytes = b"fake-artifact-bytes"):
    """Client mocké dont chaque download_* écrit réellement un fichier local (le service le relit ensuite)."""
    import notebooklm

    async def _write_file(notebook_id, local_path):
        with open(local_path, "wb") as f:
            f.write(download_writes)
        return local_path

    mock_client = AsyncMock()
    mock_client.artifacts.generate_audio = AsyncMock(return_value=MagicMock(task_id="task-audio"))
    mock_client.artifacts.generate_flashcards = AsyncMock(return_value=MagicMock(task_id="task-flash"))
    mock_client.artifacts.generate_video = AsyncMock(return_value=MagicMock(task_id="task-video"))
    mock_client.artifacts.wait_for_completion = AsyncMock(
        return_value=MagicMock(status=notebooklm.GenerationState.COMPLETED, error=None)
    )
    mock_client.artifacts.download_audio = AsyncMock(side_effect=_write_file)
    mock_client.artifacts.download_flashcards = AsyncMock(side_effect=_write_file)
    mock_client.artifacts.download_video = AsyncMock(side_effect=_write_file)
    mock_client.chat.ask = AsyncMock(return_value=MagicMock(answer="Réponse du notebook."))

    mock_context = AsyncMock()
    mock_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_context.__aexit__ = AsyncMock(return_value=False)
    return mock_client, mock_context


@pytest.mark.anyio
async def test_generate_audio_overview_success_uploads_to_storage():
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")
    mock_client, mock_context = _make_artifact_client()

    with (
        patch.object(notebooklm.NotebookLMClient, "from_storage", return_value=mock_context),
        patch(
            "app.infra_services.storage_service.storage_service.upload",
            new_callable=AsyncMock, return_value="notebooklm/audio/nb-1.mp3",
        ) as mock_upload,
    ):
        result = await service.generate_audio_overview("nb-1", "notebooklm/audio/nb-1.mp3")

    assert result == "notebooklm/audio/nb-1.mp3"
    mock_client.artifacts.generate_audio.assert_awaited_once_with("nb-1")
    mock_client.artifacts.download_audio.assert_awaited_once()
    mock_upload.assert_awaited_once()
    assert mock_upload.await_args.kwargs["data"] == b"fake-artifact-bytes"


@pytest.mark.anyio
async def test_generate_flashcards_success_uploads_to_storage():
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")
    mock_client, mock_context = _make_artifact_client()

    with (
        patch.object(notebooklm.NotebookLMClient, "from_storage", return_value=mock_context),
        patch(
            "app.infra_services.storage_service.storage_service.upload",
            new_callable=AsyncMock, return_value="notebooklm/flashcards/nb-1.json",
        ),
    ):
        result = await service.generate_flashcards("nb-1", "notebooklm/flashcards/nb-1.json")

    assert result == "notebooklm/flashcards/nb-1.json"
    mock_client.artifacts.generate_flashcards.assert_awaited_once_with("nb-1")


@pytest.mark.anyio
async def test_generate_video_overview_success_uploads_to_storage():
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")
    mock_client, mock_context = _make_artifact_client()

    with (
        patch.object(notebooklm.NotebookLMClient, "from_storage", return_value=mock_context),
        patch(
            "app.infra_services.storage_service.storage_service.upload",
            new_callable=AsyncMock, return_value="notebooklm/video/nb-1.mp4",
        ),
    ):
        result = await service.generate_video_overview("nb-1", "notebooklm/video/nb-1.mp4")

    assert result == "notebooklm/video/nb-1.mp4"
    mock_client.artifacts.generate_video.assert_awaited_once_with("nb-1")


@pytest.mark.anyio
async def test_generate_audio_overview_failure_isolated_never_raises():
    """Échec d'UN format (audio) — jamais une exception, jamais d'impact sur les autres formats (isolation vérifiée par appel indépendant)."""
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")
    mock_client, mock_context = _make_artifact_client()
    mock_client.artifacts.wait_for_completion = AsyncMock(
        return_value=MagicMock(status=notebooklm.GenerationState.FAILED, error="quota dépassé")
    )

    with patch.object(notebooklm.NotebookLMClient, "from_storage", return_value=mock_context):
        result = await service.generate_audio_overview("nb-1", "notebooklm/audio/nb-1.mp3")

    assert result is None


@pytest.mark.anyio
async def test_generate_flashcards_client_exception_never_propagates():
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")

    with patch.object(
        notebooklm.NotebookLMClient, "from_storage",
        side_effect=RuntimeError("NotebookLM indisponible (simulé)"),
    ):
        result = await service.generate_flashcards("nb-1", "notebooklm/flashcards/nb-1.json")

    assert result is None


@pytest.mark.anyio
async def test_generate_video_overview_not_configured_returns_none():
    service = NotebookLMService(storage_path=None)

    result = await service.generate_video_overview("nb-1", "notebooklm/video/nb-1.mp4")

    assert result is None


@pytest.mark.anyio
async def test_ask_chat_success_returns_answer_text():
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")
    mock_client, mock_context = _make_artifact_client()

    with patch.object(notebooklm.NotebookLMClient, "from_storage", return_value=mock_context):
        result = await service.ask_chat("nb-1", "Pourquoi ma maîtrise est-elle faible ?")

    assert result == "Réponse du notebook."
    mock_client.chat.ask.assert_awaited_once_with("nb-1", "Pourquoi ma maîtrise est-elle faible ?")


@pytest.mark.anyio
async def test_ask_chat_failure_returns_none_never_raises():
    import notebooklm

    service = NotebookLMService(storage_path="/fake/storage_state.json")

    with patch.object(
        notebooklm.NotebookLMClient, "from_storage",
        side_effect=RuntimeError("NotebookLM indisponible (simulé)"),
    ):
        result = await service.ask_chat("nb-1", "Question ?")

    assert result is None
