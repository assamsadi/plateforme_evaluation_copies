"""
Tests JobSupervisionService — get_overview() (comptage complet 7 statuts +
jobs récents + jobs problématiques) et get_job_detail() (404 via
JobNotFoundError si absent).
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import JobNotFoundError
from app.domain.models.system_infrastructure.job import JobStatus
from app.domain.repositories.pagination import CursorPage
from app.services.job_supervision_service import JobSupervisionService


def _fake_job(status=JobStatus.PENDING):
    return MagicMock(id=uuid.uuid4(), status=status)


@pytest.mark.anyio
class TestGetOverview:
    async def test_fills_all_seven_statuses_even_when_absent(self):
        job_repo = AsyncMock()
        job_repo.count_by_status.return_value = {"pending": 2, "failed": 1}
        job_repo.list_recent.return_value = []
        job_repo.list_by_status.return_value = CursorPage(items=[], next_cursor=None, has_more=False)
        service = JobSupervisionService(job_repo)

        result = await service.get_overview()

        assert set(result["counts_by_status"].keys()) == {s.value for s in JobStatus}
        assert result["counts_by_status"]["pending"] == 2
        assert result["counts_by_status"]["failed"] == 1
        assert result["counts_by_status"]["completed"] == 0

    async def test_recent_jobs_delegates_to_repository(self):
        job_repo = AsyncMock()
        job_repo.count_by_status.return_value = {}
        fake_recent = [_fake_job(), _fake_job()]
        job_repo.list_recent.return_value = fake_recent
        job_repo.list_by_status.return_value = CursorPage(items=[], next_cursor=None, has_more=False)
        service = JobSupervisionService(job_repo)

        result = await service.get_overview(recent_limit=10)

        assert result["recent_jobs"] == fake_recent
        job_repo.list_recent.assert_awaited_once_with(limit=10)

    async def test_problematic_jobs_covers_interrupted_failed_retrying_only(self):
        job_repo = AsyncMock()
        job_repo.count_by_status.return_value = {}
        job_repo.list_recent.return_value = []

        interrupted_job = _fake_job(JobStatus.INTERRUPTED)
        failed_job = _fake_job(JobStatus.FAILED)
        retrying_job = _fake_job(JobStatus.RETRYING)

        def fake_list_by_status(status, limit=None, cursor=None):
            mapping = {
                JobStatus.INTERRUPTED: [interrupted_job],
                JobStatus.FAILED: [failed_job],
                JobStatus.RETRYING: [retrying_job],
            }
            return CursorPage(items=mapping.get(status, []), next_cursor=None, has_more=False)

        job_repo.list_by_status.side_effect = fake_list_by_status
        service = JobSupervisionService(job_repo)

        result = await service.get_overview()

        problematic_ids = {j.id for j in result["problematic_jobs"]}
        assert problematic_ids == {interrupted_job.id, failed_job.id, retrying_job.id}
        called_statuses = {call.args[0] for call in job_repo.list_by_status.call_args_list}
        assert called_statuses == {JobStatus.INTERRUPTED, JobStatus.FAILED, JobStatus.RETRYING}
        # RUNNING/PENDING (normaux) et COMPLETED/CANCELLED (terminaux non problématiques) jamais interrogés.
        assert JobStatus.RUNNING not in called_statuses
        assert JobStatus.COMPLETED not in called_statuses


@pytest.mark.anyio
class TestGetJobDetail:
    async def test_found_returns_job(self):
        job_repo = AsyncMock()
        fake_job = _fake_job()
        job_repo.get_by_id.return_value = fake_job
        service = JobSupervisionService(job_repo)

        result = await service.get_job_detail(fake_job.id)

        assert result is fake_job

    async def test_not_found_raises_job_not_found_error(self):
        job_repo = AsyncMock()
        job_repo.get_by_id.return_value = None
        service = JobSupervisionService(job_repo)

        with pytest.raises(JobNotFoundError):
            await service.get_job_detail(uuid.uuid4())
