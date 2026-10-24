import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import FeedbackNotFoundError
from app.domain.models.assessment.feedback_version import FeedbackAuthorType, FeedbackVersion
from app.services.feedback_service import FeedbackService


def _make_feedback_version(
    version_id: uuid.UUID,
    feedback_id: uuid.UUID,
    version_number: int,
    content: str,
    author_type: FeedbackAuthorType,
    author_user_id: uuid.UUID | None = None,
) -> FeedbackVersion:
    now = datetime.now(timezone.utc)
    return FeedbackVersion(
        id=version_id,
        feedback_id=feedback_id,
        version_number=version_number,
        content=content,
        author_type=author_type,
        author_user_id=author_user_id,
        created_at=now,
        updated_at=now,
    )


def _make_feedback(feedback_id: uuid.UUID) -> MagicMock:
    f = MagicMock()
    f.id = feedback_id
    return f


def _make_professor(professor_id: uuid.UUID) -> MagicMock:
    p = MagicMock()
    p.id = professor_id
    p.first_name = "Alice"
    p.last_name = "Dupont"
    return p


def _make_service(feedback_repo=None, user_repo=None) -> FeedbackService:
    return FeedbackService(
        feedback_repo or AsyncMock(),
        user_repo or AsyncMock(),
    )


@pytest.mark.anyio
async def test_generate_ai_feedback_success():
    fid = uuid.uuid4()
    vid = uuid.uuid4()
    sid = uuid.uuid4()
    qid = uuid.uuid4()
    feedback = _make_feedback(fid)
    version = _make_feedback_version(vid, fid, 1, "Feedback IA", FeedbackAuthorType.AI)

    feedback_repo = AsyncMock()
    feedback_repo.get_or_create.return_value = feedback
    feedback_repo.add_version.return_value = version

    service = _make_service(feedback_repo=feedback_repo)
    result = await service.generate_ai_feedback(sid, qid, "Feedback IA")

    assert result.id == vid
    assert result.feedback_id == fid
    assert result.version_number == 1
    assert result.content == "Feedback IA"
    assert result.author_type == FeedbackAuthorType.AI
    assert result.author_full_name is None
    feedback_repo.get_or_create.assert_awaited_once_with(submission_id=sid, question_id=qid)
    feedback_repo.add_version.assert_awaited_once_with(
        feedback_id=fid,
        content="Feedback IA",
        author_type=FeedbackAuthorType.AI,
        author_user_id=None,
    )


@pytest.mark.anyio
async def test_edit_feedback_success():
    fid = uuid.uuid4()
    vid = uuid.uuid4()
    pid = uuid.uuid4()
    latest = _make_feedback_version(vid, fid, 1, "Ancien", FeedbackAuthorType.AI)
    new_version = _make_feedback_version(
        uuid.uuid4(), fid, 2, "Corrigé", FeedbackAuthorType.TEACHER, author_user_id=pid
    )

    feedback_repo = AsyncMock()
    feedback_repo.get_latest_version.return_value = latest
    feedback_repo.add_version.return_value = new_version

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(feedback_repo=feedback_repo, user_repo=user_repo)
    result = await service.edit_feedback(fid, pid, "Corrigé")

    assert result.version_number == 2
    assert result.author_type == FeedbackAuthorType.TEACHER
    assert result.author_full_name == "Alice Dupont"
    feedback_repo.add_version.assert_awaited_once_with(
        feedback_id=fid,
        content="Corrigé",
        author_type=FeedbackAuthorType.TEACHER,
        author_user_id=pid,
    )


@pytest.mark.anyio
async def test_edit_feedback_not_found():
    fid = uuid.uuid4()
    feedback_repo = AsyncMock()
    feedback_repo.get_latest_version.return_value = None

    service = _make_service(feedback_repo=feedback_repo)
    with pytest.raises(FeedbackNotFoundError):
        await service.edit_feedback(fid, uuid.uuid4(), "Corrigé")
    feedback_repo.add_version.assert_not_awaited()


@pytest.mark.anyio
async def test_get_latest_ai_author_full_name_none():
    fid = uuid.uuid4()
    vid = uuid.uuid4()
    version = _make_feedback_version(vid, fid, 1, "Feedback IA", FeedbackAuthorType.AI)

    feedback_repo = AsyncMock()
    feedback_repo.get_latest_version.return_value = version

    service = _make_service(feedback_repo=feedback_repo)
    result = await service.get_latest(fid)

    assert result.author_full_name is None
    assert result.version_number == 1


@pytest.mark.anyio
async def test_get_latest_teacher_enriches_full_name():
    fid = uuid.uuid4()
    vid = uuid.uuid4()
    pid = uuid.uuid4()
    version = _make_feedback_version(
        vid, fid, 2, "Corrigé", FeedbackAuthorType.TEACHER, author_user_id=pid
    )

    feedback_repo = AsyncMock()
    feedback_repo.get_latest_version.return_value = version

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(feedback_repo=feedback_repo, user_repo=user_repo)
    result = await service.get_latest(fid)

    assert result.author_full_name == "Alice Dupont"
    user_repo.get_by_id.assert_awaited_once_with(pid)


@pytest.mark.anyio
async def test_get_latest_not_found():
    fid = uuid.uuid4()
    feedback_repo = AsyncMock()
    feedback_repo.get_latest_version.return_value = None

    service = _make_service(feedback_repo=feedback_repo)
    with pytest.raises(FeedbackNotFoundError):
        await service.get_latest(fid)


@pytest.mark.anyio
async def test_get_history_mixed_authors():
    fid = uuid.uuid4()
    pid = uuid.uuid4()
    ai_v = _make_feedback_version(uuid.uuid4(), fid, 1, "IA", FeedbackAuthorType.AI)
    teacher_v = _make_feedback_version(
        uuid.uuid4(), fid, 2, "Prof", FeedbackAuthorType.TEACHER, author_user_id=pid
    )

    feedback_repo = AsyncMock()
    feedback_repo.list_versions.return_value = [ai_v, teacher_v]

    user_repo = AsyncMock()
    user_repo.get_by_id.return_value = _make_professor(pid)

    service = _make_service(feedback_repo=feedback_repo, user_repo=user_repo)
    result = await service.get_history(fid)

    assert len(result) == 2
    assert result[0].author_full_name is None
    assert result[1].author_full_name == "Alice Dupont"
    feedback_repo.list_versions.assert_awaited_once_with(fid)