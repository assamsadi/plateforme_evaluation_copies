"""Tests unitaires pour storage_paths."""
import uuid

from app.infra_services.storage_paths import (
    exercise_ocr_crop_path,
    mime_to_extension,
    submission_ocr_crop_path,
    submission_original_path,
)


def test_submission_original_path():
    sid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert submission_original_path(sid, "pdf") == f"submissions/{sid}/original.pdf"
    assert submission_original_path(sid, ".png") == f"submissions/{sid}/original.png"


def test_submission_ocr_crop_path():
    sid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert (
        submission_ocr_crop_path(sid, 2, 5)
        == f"submissions/{sid}/ocr_crops/page_2_block_5.png"
    )


def test_exercise_ocr_crop_path():
    eid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert (
        exercise_ocr_crop_path(eid, 1, 3)
        == f"exercises/{eid}/ocr_crops/page_1_block_3.png"
    )


def test_mime_to_extension():
    assert mime_to_extension("application/pdf") == "pdf"
    assert mime_to_extension("image/png") == "png"
    assert mime_to_extension("image/jpeg; charset=binary") == "jpg"
    assert mime_to_extension("application/octet-stream") == "bin"
