"""
Tests de ExtractionService.contest_extraction — repos mockés en AsyncMock
(même pattern que test_arbitration_service.py). Couvre §2 étapes 3/8/9 du
doc de référence Contestation_Verification_Agent.
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    SubmissionNotFoundError,
    ValidationError,
)
from app.domain.models.assessment.extraction_correction import (
    ContestationStatus,
    ContestationType,
    ExtractionContentType,
    ExtractionCorrection,
    ExtractionEvidenceLevel,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.schemas.contestation_schemas import ContestExtractionRequest
from app.services.extraction_service import (
    ExtractionNotOwnedByStudentError,
    ExtractionService,
)


def _make_storage_service() -> MagicMock:
    """
    generate_read_url() est SYNCHRONE (cf. docstring StorageService) — un
    AsyncMock ici renverrait une coroutine jamais awaitée à Pydantic
    (ExtractionCorrectionRead.image_url: str), échec de validation
    silencieux/confus plutôt qu'un vrai test du comportement.
    """
    storage = MagicMock()
    storage.generate_read_url.return_value = "https://fake.blob.core.windows.net/submissions/crop.png?sas=1"
    return storage


def _make_submission(submission_id, student_id) -> Submission:
    return Submission(
        id=submission_id, exercise_id=uuid.uuid4(), student_id=student_id,
        attempt_number=1, status=SubmissionStatus.PENDING_STUDENT_VERIFICATION,
    )


def _make_correction(
    correction_id, submission_id, contestation_status=None, prediction_ocr="texte extrait",
) -> ExtractionCorrection:
    return ExtractionCorrection(
        id=correction_id,
        submission_id=submission_id,
        question_id=uuid.uuid4(),
        image_crop_path="submissions/test/crop.png",
        page_number=1,
        content_type=ExtractionContentType.TEXT,
        prediction_ocr=prediction_ocr,
        confidence_score=Decimal("0.400"),
        bounding_box={"x": 0, "y": 0, "width": 100, "height": 50},
        evidence_level=ExtractionEvidenceLevel.AMBIGU,
        contestation_status=contestation_status,
    )


def _make_service(
    extraction_repo=None, submission_repo=None, arbitration_repo=None, storage_service=None,
) -> ExtractionService:
    return ExtractionService(
        extraction_repository=extraction_repo or AsyncMock(),
        submission_repository=submission_repo or AsyncMock(),
        correction_arbitration_repository=arbitration_repo or AsyncMock(),
        storage_service=storage_service or _make_storage_service(),
    )


def _content_request(claimed="version de l'étudiant") -> ContestExtractionRequest:
    return ContestExtractionRequest(contestation_type=ContestationType.CONTENT, claimed_content=claimed)


@pytest.mark.anyio
class TestContestExtractionIDOR:
    async def test_not_owned_raises(self):
        submission_id, correction_id = uuid.uuid4(), uuid.uuid4()
        other_student_id, requesting_student_id = uuid.uuid4(), uuid.uuid4()

        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(correction_id, submission_id)
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, other_student_id)

        service = _make_service(extraction_repo=extraction_repo, submission_repo=submission_repo)

        with pytest.raises(ExtractionNotOwnedByStudentError):
            await service.contest_extraction(
                submission_id=submission_id, correction_id=correction_id,
                student_id=requesting_student_id, request=_content_request(),
            )

    async def test_submission_id_mismatch_raises(self):
        """La correction appartient bien à l'étudiant, mais sur une AUTRE soumission que l'URL."""
        real_submission_id, url_submission_id, correction_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        student_id = uuid.uuid4()

        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(correction_id, real_submission_id)
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(real_submission_id, student_id)

        service = _make_service(extraction_repo=extraction_repo, submission_repo=submission_repo)

        with pytest.raises(ExtractionNotOwnedByStudentError):
            await service.contest_extraction(
                submission_id=url_submission_id, correction_id=correction_id,
                student_id=student_id, request=_content_request(),
            )


@pytest.mark.anyio
class TestContestExtractionTrivialGuard:
    async def test_identical_content_rejected(self):
        submission_id, correction_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(
            correction_id, submission_id, prediction_ocr="Le résultat est 42"
        )
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)

        service = _make_service(extraction_repo=extraction_repo, submission_repo=submission_repo)

        with pytest.raises(ValidationError):
            await service.contest_extraction(
                submission_id=submission_id, correction_id=correction_id, student_id=student_id,
                request=_content_request(claimed="  le   résultat EST 42  "),
            )

    async def test_empty_content_rejected(self):
        submission_id, correction_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(correction_id, submission_id)
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)

        service = _make_service(extraction_repo=extraction_repo, submission_repo=submission_repo)

        with pytest.raises(ValidationError):
            await service.contest_extraction(
                submission_id=submission_id, correction_id=correction_id, student_id=student_id,
                request=_content_request(claimed="   "),
            )


@pytest.mark.anyio
class TestContestExtractionNormalIntake:
    async def test_dispatches_celery_task_and_files_contestation(self):
        submission_id, correction_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(correction_id, submission_id)
        extraction_repo.file_contestation.return_value = _make_correction(
            correction_id, submission_id, contestation_status=ContestationStatus.PENDING_VERIFICATION,
        )
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)

        service = _make_service(extraction_repo=extraction_repo, submission_repo=submission_repo)

        with patch("app.services.extraction_service.process_contestation_verification") as mock_task:
            await service.contest_extraction(
                submission_id=submission_id, correction_id=correction_id, student_id=student_id,
                request=_content_request(claimed="ma vraie réponse"),
            )
            mock_task.delay.assert_called_once_with(submission_id=str(submission_id))

        extraction_repo.file_contestation.assert_awaited_once_with(
            correction_id=correction_id,
            contestation_type=ContestationType.CONTENT,
            claimed_content="ma vraie réponse",
            contested_element_id=None,
            claimed_question_id=None,
            claimed_section_id=None,
        )


@pytest.mark.anyio
class TestContestExtractionStatusGuards:
    @pytest.mark.parametrize("status", [ContestationStatus.IMPLAUSIBLE, ContestationStatus.PLAUSIBLE])
    async def test_already_decided_escalates_to_arbitration(self, status):
        submission_id, correction_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(
            correction_id, submission_id, contestation_status=status,
        )
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)
        arbitration_repo = AsyncMock()

        service = _make_service(
            extraction_repo=extraction_repo, submission_repo=submission_repo,
            arbitration_repo=arbitration_repo,
        )

        with patch("app.services.extraction_service.process_contestation_verification") as mock_task:
            await service.contest_extraction(
                submission_id=submission_id, correction_id=correction_id, student_id=student_id,
                request=_content_request(claimed="nouvelle justification"),
            )
            mock_task.delay.assert_not_called()

        extraction_repo.apply_contestation_verdict.assert_awaited_once()
        assert (
            extraction_repo.apply_contestation_verdict.call_args.kwargs["contestation_status"]
            == ContestationStatus.AMBIGU
        )
        arbitration_repo.create_pending.assert_awaited_once_with(correction_id)
        submission_repo.update_status.assert_awaited_once_with(
            submission_id, SubmissionStatus.PENDING_ARBITRATION
        )
        extraction_repo.file_contestation.assert_not_awaited()

    @pytest.mark.parametrize(
        "status", [ContestationStatus.PENDING_VERIFICATION, ContestationStatus.AMBIGU],
    )
    async def test_already_in_progress_conflicts(self, status):
        submission_id, correction_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(
            correction_id, submission_id, contestation_status=status,
        )
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)
        service = _make_service(extraction_repo=extraction_repo, submission_repo=submission_repo)

        with pytest.raises(ConflictError):
            await service.contest_extraction(
                submission_id=submission_id, correction_id=correction_id, student_id=student_id,
                request=_content_request(),
            )

    async def test_resolved_block_forbidden(self):
        submission_id, correction_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(
            correction_id, submission_id, contestation_status=ContestationStatus.RESOLVED,
        )
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)
        service = _make_service(extraction_repo=extraction_repo, submission_repo=submission_repo)

        with pytest.raises(ForbiddenError):
            await service.contest_extraction(
                submission_id=submission_id, correction_id=correction_id, student_id=student_id,
                request=_content_request(),
            )


@pytest.mark.anyio
class TestToReadResolvesImageUrl:
    """Bug corrigé : image_url renvoyait image_crop_path brut, jamais résolu en URL SAS."""

    async def test_contest_extraction_returns_resolved_url(self):
        submission_id, correction_id, student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        extraction_repo = AsyncMock()
        extraction_repo.get_by_id.return_value = _make_correction(correction_id, submission_id)
        extraction_repo.file_contestation.return_value = _make_correction(
            correction_id, submission_id, contestation_status=ContestationStatus.PENDING_VERIFICATION,
        )
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)
        storage = _make_storage_service()

        service = _make_service(
            extraction_repo=extraction_repo, submission_repo=submission_repo, storage_service=storage,
        )

        with patch("app.services.extraction_service.process_contestation_verification"):
            result = await service.contest_extraction(
                submission_id=submission_id, correction_id=correction_id, student_id=student_id,
                request=_content_request(claimed="ma vraie réponse"),
            )

        assert result.image_url == "https://fake.blob.core.windows.net/submissions/crop.png?sas=1"
        storage.generate_read_url.assert_called_once()
        from app.infra_services.storage_service import StorageContainer
        assert storage.generate_read_url.call_args.args[0] == StorageContainer.SUBMISSIONS
        assert storage.generate_read_url.call_args.args[1] == "submissions/test/crop.png"


@pytest.mark.anyio
class TestListCorrectionsForSubmission:
    async def test_owner_gets_resolved_corrections(self):
        submission_id, student_id = uuid.uuid4(), uuid.uuid4()
        correction = _make_correction(uuid.uuid4(), submission_id)
        extraction_repo = AsyncMock()
        extraction_repo.get_by_submission_id.return_value = [correction]
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)

        service = _make_service(extraction_repo=extraction_repo, submission_repo=submission_repo)

        result = await service.list_corrections_for_submission(submission_id, student_id)

        assert len(result) == 1
        assert result[0].id == correction.id
        assert result[0].image_url.startswith("https://")

    async def test_not_owner_forbidden(self):
        submission_id, student_id, other_student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)
        service = _make_service(submission_repo=submission_repo)

        with pytest.raises(ForbiddenError):
            await service.list_corrections_for_submission(submission_id, other_student_id)

    async def test_submission_not_found(self):
        submission_id, student_id = uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = None
        service = _make_service(submission_repo=submission_repo)

        with pytest.raises(SubmissionNotFoundError):
            await service.list_corrections_for_submission(submission_id, student_id)


@pytest.mark.anyio
class TestConfirmSubmission:
    """
    Couvre le gap fermé (job_tasks.py annonçait ce "futur endpoint" sans
    jamais le construire) : seul déclencheur manquant de la reprise du
    thread LangGraph en pause à await_student_verification_node.
    """

    async def test_pending_verification_dispatches_resume(self):
        submission_id, student_id = uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)
        extraction_repo = AsyncMock()
        extraction_repo.get_by_submission_id.return_value = []
        service = _make_service(submission_repo=submission_repo, extraction_repo=extraction_repo)

        with patch("app.services.extraction_service.process_job_resumed") as mock_task:
            result = await service.confirm_submission(submission_id, student_id)
            mock_task.delay.assert_called_once_with(
                thread_id=str(submission_id), resume_value="confirmed",
            )

        assert result.submission_id == submission_id
        assert result.status == SubmissionStatus.PENDING_STUDENT_VERIFICATION

    @pytest.mark.parametrize(
        "status", [ContestationStatus.PENDING_VERIFICATION, ContestationStatus.AMBIGU],
    )
    async def test_pending_contestation_conflicts(self, status):
        submission_id, student_id = uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)
        extraction_repo = AsyncMock()
        extraction_repo.get_by_submission_id.return_value = [
            _make_correction(uuid.uuid4(), submission_id, contestation_status=status),
        ]
        service = _make_service(submission_repo=submission_repo, extraction_repo=extraction_repo)

        with patch("app.services.extraction_service.process_job_resumed") as mock_task:
            with pytest.raises(ConflictError):
                await service.confirm_submission(submission_id, student_id)
            mock_task.delay.assert_not_called()

    async def test_not_owner_forbidden(self):
        submission_id, student_id, other_student_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = _make_submission(submission_id, student_id)
        service = _make_service(submission_repo=submission_repo)

        with pytest.raises(ForbiddenError):
            await service.confirm_submission(submission_id, other_student_id)

    async def test_submission_not_found(self):
        submission_id, student_id = uuid.uuid4(), uuid.uuid4()
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = None
        service = _make_service(submission_repo=submission_repo)

        with pytest.raises(SubmissionNotFoundError):
            await service.confirm_submission(submission_id, student_id)

    @pytest.mark.parametrize(
        "status",
        [
            SubmissionStatus.EVALUATED,
            SubmissionStatus.PENDING_OCR,
            SubmissionStatus.PENDING_ARBITRATION,
        ],
    )
    async def test_wrong_status_conflicts(self, status):
        submission_id, student_id = uuid.uuid4(), uuid.uuid4()
        submission = _make_submission(submission_id, student_id)
        submission.status = status
        submission_repo = AsyncMock()
        submission_repo.get_by_id.return_value = submission
        service = _make_service(submission_repo=submission_repo)

        with patch("app.services.extraction_service.process_job_resumed") as mock_task:
            with pytest.raises(ConflictError):
                await service.confirm_submission(submission_id, student_id)
            mock_task.delay.assert_not_called()
