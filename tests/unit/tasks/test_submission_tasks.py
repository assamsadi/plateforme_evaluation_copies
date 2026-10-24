"""
Tests unitaires pour process_submission_created (Celery task).

Réécrits pour le câblage LangGraph (submission_tasks.py invoque désormais
pipeline_graph.py au lieu d'appeler SubmissionOCRPipelineService
directement, cf. conversation "diagnostic + plan pipeline_graph") — les
anciens tests mockaient SubmissionOCRPipelineService, qui n'est plus
importé par ce module.
"""
import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import DocumentQualityError
from app.tasks.submission_tasks import process_submission_created


def _run_task(**overrides):
    payload = {
        "submission_id": str(uuid.uuid4()),
        "exercise_id": str(uuid.uuid4()),
        "student_id": str(uuid.uuid4()),
        "attempt_number": 1,
        "document_path": "submissions/x/original.pdf",
        "mime_type": "application/pdf",
    }
    payload.update(overrides)
    process_submission_created.run(**payload)


def _run_asyncio_run_side_effect(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_exercise():
    exercise = MagicMock()
    exercise.module_id = uuid.uuid4()
    return exercise


@patch("app.tasks.submission_tasks.sync_job_after_graph_run", new_callable=AsyncMock)
@patch("app.tasks.submission_tasks.compile_pipeline_graph")
@patch("app.tasks.submission_tasks.get_checkpointer")
@patch("app.tasks.submission_tasks.asyncio.run")
@patch("app.tasks.submission_tasks.get_db_context")
@patch("app.tasks.submission_tasks.SQLAlchemyExerciseRepository")
def test_process_submission_created_invokes_pipeline_graph(
    mock_exercise_repo_cls, mock_db_ctx, mock_asyncio_run,
    mock_get_checkpointer, mock_compile_graph, mock_sync_job,
):
    mock_db = MagicMock()
    mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_exercise_repo_cls.return_value.get_by_id = AsyncMock(return_value=_mock_exercise())

    mock_checkpointer = MagicMock()
    mock_get_checkpointer.return_value.__aenter__ = AsyncMock(return_value=mock_checkpointer)
    mock_get_checkpointer.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value={"status": "RUNNING"})  # pas d'__interrupt__
    mock_state_snapshot = MagicMock(next=())
    mock_graph.aget_state = AsyncMock(return_value=mock_state_snapshot)
    mock_compile_graph.return_value = mock_graph

    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect

    submission_id = str(uuid.uuid4())
    _run_task(submission_id=submission_id)

    mock_graph.ainvoke.assert_awaited_once()
    call_args = mock_graph.ainvoke.await_args
    initial_state = call_args.args[0]
    assert initial_state.submission_id == submission_id
    assert initial_state.thread_id == submission_id
    assert initial_state.flow_type == "student_evaluation"
    assert call_args.kwargs["config"] == {"configurable": {"thread_id": submission_id}}
    mock_sync_job.assert_awaited_once()


@patch("app.tasks.submission_tasks.sync_job_after_graph_run", new_callable=AsyncMock)
@patch("app.tasks.submission_tasks.compile_pipeline_graph")
@patch("app.tasks.submission_tasks.get_checkpointer")
@patch("app.tasks.submission_tasks.asyncio.run")
@patch("app.tasks.submission_tasks.get_db_context")
@patch("app.tasks.submission_tasks.SQLAlchemyExerciseRepository")
def test_process_submission_created_swallows_document_quality_error(
    mock_exercise_repo_cls, mock_db_ctx, mock_asyncio_run,
    mock_get_checkpointer, mock_compile_graph, mock_sync_job,
):
    mock_db = MagicMock()
    mock_db_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
    mock_exercise_repo_cls.return_value.get_by_id = AsyncMock(return_value=_mock_exercise())

    mock_checkpointer = MagicMock()
    mock_get_checkpointer.return_value.__aenter__ = AsyncMock(return_value=mock_checkpointer)
    mock_get_checkpointer.return_value.__aexit__ = AsyncMock(return_value=False)

    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(side_effect=DocumentQualityError("Image trop floue"))
    mock_compile_graph.return_value = mock_graph

    mock_asyncio_run.side_effect = _run_asyncio_run_side_effect

    # Ne doit lever aucune exception (état terminal avalé, cf. dont_autoretry_for).
    _run_task()

    mock_graph.ainvoke.assert_awaited_once()
    mock_sync_job.assert_not_awaited()  # jamais atteint : l'exception coupe avant
