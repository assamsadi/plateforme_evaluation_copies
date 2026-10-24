"""
Tests StatisticsService — couvre :
- get_exercise_stats (correctif : evaluation_repo.list_by_exercise() +
  Evaluation.score, plus evaluation_repo.list_by_exercise()/.grade
  inexistants avant correctif)
- get_student_stats (même correctif, câblée sur GET /students/me/stats)
- get_platform_stats (nouveau)
"""
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.domain.models.assessment.evaluation import Evaluation
from app.services.statistics_service import StatisticsService


def _make_evaluation(score: Decimal) -> Evaluation:
    return Evaluation(
        id=uuid.uuid4(),
        submission_id=uuid.uuid4(),
        question_id=uuid.uuid4(),
        score=score,
        classic_criteria_observed=[],
    )


@pytest.mark.anyio
class TestGetExerciseStats:
    async def test_no_evaluations(self):
        eval_repo = AsyncMock()
        eval_repo.list_by_exercise.return_value = []
        service = StatisticsService(eval_repo, AsyncMock(), AsyncMock(), AsyncMock())

        result = await service.get_exercise_stats(uuid.uuid4())

        assert result["total_evaluations"] == 0
        assert result["average_score"] is None
        eval_repo.list_by_exercise.assert_awaited_once()

    async def test_nominal_uses_score_field(self):
        """Preuve directe du correctif : Evaluation N'A PAS d'attribut .grade — si le service y accédait encore, ceci lèverait AttributeError."""
        exercise_id = uuid.uuid4()
        eval_repo = AsyncMock()
        eval_repo.list_by_exercise.return_value = [
            _make_evaluation(Decimal("10.00")),
            _make_evaluation(Decimal("15.00")),
            _make_evaluation(Decimal("20.00")),
        ]
        service = StatisticsService(eval_repo, AsyncMock(), AsyncMock(), AsyncMock())

        result = await service.get_exercise_stats(exercise_id)

        assert result["exercise_id"] == str(exercise_id)
        assert result["total_evaluations"] == 3
        assert result["average_score"] == 15.0
        assert result["min_score"] == 10.0
        assert result["max_score"] == 20.0
        eval_repo.list_by_exercise.assert_awaited_once_with(exercise_id)


@pytest.mark.anyio
class TestGetStudentStats:
    async def test_no_data(self):
        student_id = uuid.uuid4()
        eval_repo = AsyncMock()
        eval_repo.list_by_student.return_value = []
        sub_repo = AsyncMock()
        sub_repo.count_by_student.return_value = 0
        service = StatisticsService(eval_repo, AsyncMock(), sub_repo, AsyncMock())

        result = await service.get_student_stats(student_id)

        assert result["total_submissions"] == 0
        assert result["total_evaluations"] == 0
        assert result["average_score"] is None

    async def test_nominal_uses_score_field(self):
        """Même preuve que test_nominal_uses_score_field ci-dessus, pour get_student_stats — bug identique, câblée sur GET /students/me/stats."""
        student_id = uuid.uuid4()
        eval_repo = AsyncMock()
        eval_repo.list_by_student.return_value = [
            _make_evaluation(Decimal("8.00")),
            _make_evaluation(Decimal("12.00")),
        ]
        sub_repo = AsyncMock()
        sub_repo.count_by_student.return_value = 3
        service = StatisticsService(eval_repo, AsyncMock(), sub_repo, AsyncMock())

        result = await service.get_student_stats(student_id)

        assert result["student_id"] == str(student_id)
        assert result["total_submissions"] == 3
        assert result["total_evaluations"] == 2
        assert result["average_score"] == 10.0
        eval_repo.list_by_student.assert_awaited_once_with(student_id)
        sub_repo.count_by_student.assert_awaited_once_with(student_id)

    async def test_total_submissions_not_capped_by_page_size(self):
        """
        Bug corrigé : total_submissions comptait len(list_by_student(...)
        .items) (paginée, DEFAULT_PAGE_SIZE=50) — un étudiant avec plus de
        50 soumissions aurait vu un total plafonné à 50. count_by_student
        renvoie un vrai COUNT, jamais affecté par la pagination.
        """
        student_id = uuid.uuid4()
        eval_repo = AsyncMock()
        eval_repo.list_by_student.return_value = []
        sub_repo = AsyncMock()
        sub_repo.count_by_student.return_value = 67
        service = StatisticsService(eval_repo, AsyncMock(), sub_repo, AsyncMock())

        result = await service.get_student_stats(student_id)

        assert result["total_submissions"] == 67


@pytest.mark.anyio
class TestGetPlatformStats:
    async def test_nominal(self):
        user_repo = AsyncMock()
        user_repo.count_by_role.return_value = {"student": 42, "professor": 5}
        exercise_repo = AsyncMock()
        exercise_repo.count_by_status.return_value = {"draft": 3, "published_as_exam": 7}
        submission_repo = AsyncMock()
        submission_repo.count_by_status.return_value = {"evaluated": 20, "pending_ocr": 4}
        eval_repo = AsyncMock()
        eval_repo.get_average_score_platform.return_value = Decimal("13.456")

        service = StatisticsService(eval_repo, exercise_repo, submission_repo, user_repo)
        result = await service.get_platform_stats()

        assert result["total_users"] == 47  # 42 + 5 + 0 admin (rôle absent complété à 0)
        assert result["users_by_role"] == {"student": 42, "professor": 5, "admin": 0}
        assert result["total_exercises"] == 10  # 3 + 7 + 0 pour les 2 autres statuts
        assert result["exercises_by_status"]["draft"] == 3
        assert result["exercises_by_status"]["published_as_exam"] == 7
        assert result["exercises_by_status"]["published_as_homework"] == 0
        assert result["exercises_by_status"]["archived_in_library"] == 0
        assert result["total_submissions"] == 24
        assert result["submissions_by_status"]["evaluated"] == 20
        assert result["submissions_by_status"]["pending_ocr"] == 4
        assert result["submissions_by_status"]["absent"] == 0
        assert result["average_score"] == 13.46

    async def test_no_data_at_all(self):
        user_repo = AsyncMock()
        user_repo.count_by_role.return_value = {}
        exercise_repo = AsyncMock()
        exercise_repo.count_by_status.return_value = {}
        submission_repo = AsyncMock()
        submission_repo.count_by_status.return_value = {}
        eval_repo = AsyncMock()
        eval_repo.get_average_score_platform.return_value = None

        service = StatisticsService(eval_repo, exercise_repo, submission_repo, user_repo)
        result = await service.get_platform_stats()

        assert result["total_users"] == 0
        assert result["total_exercises"] == 0
        assert result["total_submissions"] == 0
        assert result["average_score"] is None
        # Toutes les clés d'enum connues restent présentes, même à 0 — jamais un dict incomplet.
        assert set(result["users_by_role"].keys()) == {"student", "professor", "admin"}
