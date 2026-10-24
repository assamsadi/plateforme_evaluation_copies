"""
Tests de scan_quality_control_node — contrôle qualité déterministe commun
aux deux flows, avant tout appel à OCR_Extraction_Agent (audit "garanties
transverses"). storage_service.download mocké (seul point Azure) ; le
contrôle qualité lui-même (OpenCV) tourne réellement, jamais mocké — c'est
précisément ce qu'on veut prouver ici.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest

from app.core.exceptions import DocumentQualityError
from app.graph.nodes.scan_quality_control_node import scan_quality_control_node
from app.graph.state import PipelineState
from app.infra_services.storage_service import StorageContainer


def _make_sharp_png_bytes() -> bytes:
    arr = np.full((400, 400, 3), 255, dtype=np.uint8)
    cv2.putText(arr, "Enonce net et contraste", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
    cv2.rectangle(arr, (10, 10), (390, 390), (0, 0, 0), 2)
    _, buffer = cv2.imencode(".png", arr)
    return buffer.tobytes()


def _make_blurry_png_bytes() -> bytes:
    arr = np.full((300, 300, 3), 120, dtype=np.uint8)
    _, buffer = cv2.imencode(".png", arr)
    return buffer.tobytes()


def _make_state(*, flow_type: str, raw_file_path: str = "doc.png") -> PipelineState:
    now = datetime.now(timezone.utc)
    thread_id = str(uuid.uuid4())
    kwargs = dict(
        thread_id=thread_id,
        flow_type=flow_type,
        trace_id=thread_id,
        module_id=str(uuid.uuid4()),
        raw_file_path=raw_file_path,
        mime_type="image/png",
        created_at=now,
        updated_at=now,
    )
    if flow_type == "exercise_setup":
        kwargs["exercise_id"] = thread_id
        kwargs["professor_id"] = str(uuid.uuid4())
    else:
        kwargs["exercise_id"] = str(uuid.uuid4())
        kwargs["submission_id"] = thread_id
        kwargs["student_id"] = str(uuid.uuid4())
    return PipelineState(**kwargs)


@pytest.mark.anyio
async def test_scan_quality_control_uses_exercises_container_for_exercise_setup():
    state = _make_state(flow_type="exercise_setup")

    with patch(
        "app.graph.nodes.scan_quality_control_node.storage_service.download",
        new_callable=AsyncMock,
        return_value=_make_sharp_png_bytes(),
    ) as mock_download:
        result = await scan_quality_control_node(state)

    mock_download.assert_awaited_once_with(StorageContainer.EXERCISES, state.raw_file_path)
    assert result.status == "RUNNING"


@pytest.mark.anyio
async def test_scan_quality_control_uses_submissions_container_for_student_evaluation():
    state = _make_state(flow_type="student_evaluation")

    with patch(
        "app.graph.nodes.scan_quality_control_node.storage_service.download",
        new_callable=AsyncMock,
        return_value=_make_sharp_png_bytes(),
    ) as mock_download:
        result = await scan_quality_control_node(state)

    mock_download.assert_awaited_once_with(StorageContainer.SUBMISSIONS, state.raw_file_path)
    assert result.status == "RUNNING"


@pytest.mark.anyio
async def test_scan_quality_control_raises_on_blurry_document_without_reaching_ocr():
    state = _make_state(flow_type="student_evaluation")

    with patch(
        "app.graph.nodes.scan_quality_control_node.storage_service.download",
        new_callable=AsyncMock,
        return_value=_make_blurry_png_bytes(),
    ):
        with pytest.raises(DocumentQualityError):
            await scan_quality_control_node(state)
