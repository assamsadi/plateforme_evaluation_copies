"""
Tests du RecommendedExerciseRepository — couvre toutes les méthodes publiques :
- create (nominal)
- get_by_id (nominal, non trouvé)
- list_by_submission (nominal, vide, tri par relevance_score desc)
- list_active_by_student (nominal, student_id direct depuis le chantier
  Recommendation_Agent — plus un JOIN via Submission — filtre RÉELLEMENT
  status=ACTIVE désormais)
- list_active_by_student_module_competency / supersede (dédoublonnage)
"""
import uuid
from decimal import Decimal

import pytest

from app.domain.models.assessment.recommended_exercise import (
    RecommendationCategory,
    RecommendationStatus,
)
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.identity.user import Student, Professor, UserRole, AcademicStatus
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.group_repository import SQLAlchemyGroupRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.program_repository import SQLAlchemyProgramRepository
from app.domain.repositories.recommended_exercise_repository import (
    SQLAlchemyRecommendedExerciseRepository,
)
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository

DAP = C2PCTSkillCode.DATA_AND_PLANNING
AS = C2PCTSkillCode.ALGORITHMIC_STRUCTURING


@pytest.fixture
async def program(db_session):
    repo = SQLAlchemyProgramRepository(db_session)
    return await repo.create(name=f"Test Program {uuid.uuid4().hex[:8]}", code=f"TP{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def module(db_session, program):
    repo = SQLAlchemyModuleRepository(db_session)
    return await repo.create(program_id=program.id, name=f"Test Module {uuid.uuid4().hex[:8]}", code=f"TM{uuid.uuid4().hex[:6]}")


@pytest.fixture
async def group(db_session, program):
    repo = SQLAlchemyGroupRepository(db_session)
    return await repo.create(program_id=program.id, label=f"G{uuid.uuid4().hex[:6]}", academic_year="2025-2026")


@pytest.fixture
async def professor(db_session):
    prof = Professor(
        id=uuid.uuid4(),
        role=UserRole.PROFESSOR,
        first_name="Bob",
        last_name="Martin",
        email=f"prof_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
        department="Informatique",
        title="Dr",
        employee_number=f"EMP{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prof)
    await db_session.flush()
    return prof


@pytest.fixture
async def student(db_session, group):
    s = Student(
        id=uuid.uuid4(),
        role=UserRole.STUDENT,
        first_name="Alice",
        last_name="Dupont",
        email=f"student_{uuid.uuid4().hex[:8]}@test.edu",
        hashed_password="hashed_pw",
        student_number=f"STU{uuid.uuid4().hex[:6]}",
        group_id=group.id,
        enrollment_year=2025,
        academic_status=AcademicStatus.ACTIVE,
        level="L3",
    )
    db_session.add(s)
    await db_session.flush()
    return s


@pytest.fixture
async def exercise(db_session, module, professor):
    repo = SQLAlchemyExerciseRepository(db_session)
    return await repo.create_with_questions(
        module_id=module.id,
        created_by_professor_id=professor.id,
        title="Test Exercise",
        description=None,
        questions_data=[
            {"order": 1, "statement": "Q1", "bareme": {"points": Decimal("5.00"), "criteria": []}},
        ],
    )


@pytest.fixture
async def recommended_exercise(db_session, exercise, student, module):
    """Crée un exercice recommandé + une soumission pour le lier."""
    sub_repo = SQLAlchemySubmissionRepository(db_session)
    submission = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

    rec_repo = SQLAlchemyRecommendedExerciseRepository(db_session)
    return await rec_repo.create(
        student_id=student.id,
        module_id=module.id,
        competency_code=DAP,
        category=RecommendationCategory.REMEDIATION,
        submission_id=submission.id,
        exercise_id=exercise.id,
        reason="Réviser les bases",
        relevance_score=Decimal("0.850"),
    )


@pytest.mark.anyio
class TestRecommendedExerciseRepositoryCreate:
    """Tests de la méthode create()."""

    async def test_create_nominal(self, db_session, exercise, student, module):
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        submission = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        rec = await repo.create(
            student_id=student.id,
            module_id=module.id,
            competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            submission_id=submission.id,
            exercise_id=exercise.id,
            reason="Besoin de pratique",
            relevance_score=Decimal("0.750"),
        )

        assert rec.id is not None
        assert rec.student_id == student.id
        assert rec.module_id == module.id
        assert rec.competency_code == DAP
        assert rec.category == RecommendationCategory.REMEDIATION
        assert rec.status == RecommendationStatus.ACTIVE  # défaut, jamais forcé par l'appelant
        assert rec.submission_id == submission.id
        assert rec.exercise_id == exercise.id
        assert rec.reason == "Besoin de pratique"
        assert rec.relevance_score == Decimal("0.750")

    async def test_create_without_submission_id(self, db_session, exercise, student, module):
        """submission_id nullable (chantier Recommendation_Agent) — une génération peut ne pas être liée à UNE soumission précise."""
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        rec = await repo.create(
            student_id=student.id,
            module_id=module.id,
            competency_code=AS,
            category=RecommendationCategory.VERIFICATION,
            exercise_id=exercise.id,
            reason="Confirmer la maîtrise",
            relevance_score=Decimal("0.300"),
        )

        assert rec.submission_id is None
        assert rec.category == RecommendationCategory.VERIFICATION


@pytest.mark.anyio
class TestRecommendedExerciseRepositoryGetById:
    """Tests de la méthode get_by_id()."""

    async def test_get_by_id_found(self, db_session, recommended_exercise):
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)

        found = await repo.get_by_id(recommended_exercise.id)

        assert found is not None
        assert found.id == recommended_exercise.id
        assert found.reason == "Réviser les bases"

    async def test_get_by_id_not_found_returns_none(self, db_session):
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)

        found = await repo.get_by_id(uuid.uuid4())

        assert found is None


@pytest.mark.anyio
class TestRecommendedExerciseRepositoryListBySubmission:
    """Tests de la méthode list_by_submission()."""

    async def test_empty(self, db_session, exercise, student):
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        submission = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        result = await repo.list_by_submission(submission.id)

        assert result == []

    async def test_nominal(self, db_session, exercise, student, module):
        sub_repo = SQLAlchemySubmissionRepository(db_session)
        submission = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        r1 = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION, submission_id=submission.id,
            exercise_id=exercise.id, reason="R1", relevance_score=Decimal("0.900"),
        )
        r2 = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION, submission_id=submission.id,
            exercise_id=exercise.id, reason="R2", relevance_score=Decimal("0.500"),
        )

        result = await repo.list_by_submission(submission.id)

        assert len(result) == 2
        # Tri par relevance_score décroissant
        assert result[0].relevance_score >= result[1].relevance_score
        assert result[0].id == r1.id
        assert result[1].id == r2.id


@pytest.mark.anyio
class TestRecommendedExerciseRepositoryListActiveByStudent:
    """Tests de la méthode list_active_by_student() (student_id direct, filtre status=ACTIVE réellement)."""

    async def test_empty(self, db_session, student):
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)

        result = await repo.list_active_by_student(student.id)

        assert result == []

    async def test_nominal(self, db_session, exercise, student, module):
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="R1", relevance_score=Decimal("0.950"),
        )
        await repo.create(
            student_id=student.id, module_id=module.id, competency_code=AS,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="R2", relevance_score=Decimal("0.700"),
        )

        result = await repo.list_active_by_student(student.id)

        assert len(result) == 2
        # Tri par relevance_score décroissant
        assert result[0].relevance_score >= result[1].relevance_score

    async def test_excludes_superseded(self, db_session, exercise, student, module):
        """Correctif — avant ce chantier, list_active_by_student ne filtrait rien malgré son nom."""
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        superseded = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Ancienne", relevance_score=Decimal("0.900"),
        )
        await repo.supersede([superseded.id])
        await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Nouvelle", relevance_score=Decimal("0.800"),
        )

        result = await repo.list_active_by_student(student.id)

        assert len(result) == 1
        assert result[0].reason == "Nouvelle"

    async def test_excludes_other_student(self, db_session, exercise, student, module, group):
        """Ne retourne pas les recommandations d'un autre étudiant."""
        other_student = Student(
            id=uuid.uuid4(),
            role=UserRole.STUDENT,
            first_name="Bob",
            last_name="Martin",
            email=f"other_{uuid.uuid4().hex[:8]}@test.edu",
            hashed_password="hashed_pw",
            student_number=f"STU{uuid.uuid4().hex[:6]}",
            group_id=group.id,
            enrollment_year=2025,
            academic_status=AcademicStatus.ACTIVE,
            level="L3",
        )
        db_session.add(other_student)
        await db_session.flush()

        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        await repo.create(
            student_id=other_student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Other", relevance_score=Decimal("0.900"),
        )
        await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Mine", relevance_score=Decimal("0.800"),
        )

        result = await repo.list_active_by_student(student.id)

        assert len(result) == 1
        assert result[0].reason == "Mine"


@pytest.mark.anyio
class TestRecommendedExerciseRepositoryListActiveByStudentAndModule:
    """Vue professeur (clôture chantier Recommendation_Agent) — scopée à UN module, filtre status=ACTIVE réel."""

    async def test_empty(self, db_session, student, module):
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)

        result = await repo.list_active_by_student_and_module(student.id, module.id)

        assert result == []

    async def test_excludes_other_module(self, db_session, exercise, student, module, program):
        from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
        other_module = await SQLAlchemyModuleRepository(db_session).create(
            program_id=program.id, name=f"Autre module {uuid.uuid4().hex[:8]}", code=f"OM{uuid.uuid4().hex[:6]}",
        )

        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        await repo.create(
            student_id=student.id, module_id=other_module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Autre module", relevance_score=Decimal("0.900"),
        )
        matching = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Bon module", relevance_score=Decimal("0.800"),
        )

        result = await repo.list_active_by_student_and_module(student.id, module.id)

        assert len(result) == 1
        assert result[0].id == matching.id

    async def test_excludes_superseded(self, db_session, exercise, student, module):
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        superseded = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Ancienne", relevance_score=Decimal("0.900"),
        )
        await repo.supersede([superseded.id])
        active = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=AS,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Nouvelle", relevance_score=Decimal("0.700"),
        )

        result = await repo.list_active_by_student_and_module(student.id, module.id)

        assert len(result) == 1
        assert result[0].id == active.id


@pytest.mark.anyio
class TestRecommendedExerciseRepositoryDedup:
    """Tests de list_active_by_student_module_competency() / supersede() — dédoublonnage."""

    async def test_list_active_by_student_module_competency_scoped_correctly(self, db_session, exercise, student, module):
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        matching = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Match", relevance_score=Decimal("0.800"),
        )
        # Autre compétence, même étudiant/module -> jamais retournée.
        await repo.create(
            student_id=student.id, module_id=module.id, competency_code=AS,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Autre competence", relevance_score=Decimal("0.800"),
        )

        result = await repo.list_active_by_student_module_competency(student.id, module.id, DAP)

        assert len(result) == 1
        assert result[0].id == matching.id

    async def test_supersede_marks_status_and_excludes_from_active_lookup(self, db_session, exercise, student, module):
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        rec = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="A superseder", relevance_score=Decimal("0.800"),
        )

        await repo.supersede([rec.id])
        await db_session.flush()

        refreshed = await repo.get_by_id(rec.id)
        assert refreshed.status == RecommendationStatus.SUPERSEDED
        active = await repo.list_active_by_student_module_competency(student.id, module.id, DAP)
        assert active == []

    async def test_supersede_empty_list_is_a_noop(self, db_session, exercise, student, module):
        """Jamais un UPDATE sans WHERE réel qui toucherait toute la table."""
        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        rec = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Intact", relevance_score=Decimal("0.800"),
        )

        await repo.supersede([])

        refreshed = await repo.get_by_id(rec.id)
        assert refreshed.status == RecommendationStatus.ACTIVE


@pytest.mark.anyio
class TestRecommendedExerciseRepositoryLinkToNotebook:
    """Câblage NotebookLM (§7, Partie 2/2) — rattachement après coup au StudentNotebook."""

    async def test_link_to_notebook_nominal(self, db_session, exercise, student, module):
        from app.domain.repositories.student_notebook_repository import (
            SQLAlchemyStudentNotebookRepository,
        )

        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        rec = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="A rattacher", relevance_score=Decimal("0.800"),
        )
        notebook_repo = SQLAlchemyStudentNotebookRepository(db_session)
        notebook = await notebook_repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        await repo.link_to_notebook(
            student_id=student.id, module_id=module.id, submission_id=None, student_notebook_id=notebook.id,
        )

        refreshed = await repo.get_by_id(rec.id)
        assert refreshed.student_notebook_id == notebook.id

    async def test_link_to_notebook_never_overwrites_existing_link(self, db_session, exercise, student, module):
        from app.domain.repositories.student_notebook_repository import (
            SQLAlchemyStudentNotebookRepository,
        )

        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        rec = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION,
            exercise_id=exercise.id, reason="Deja rattache", relevance_score=Decimal("0.800"),
        )
        notebook_repo = SQLAlchemyStudentNotebookRepository(db_session)
        first_notebook = await notebook_repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-first")
        second_notebook = await notebook_repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-second")

        await repo.link_to_notebook(
            student_id=student.id, module_id=module.id, submission_id=None, student_notebook_id=first_notebook.id,
        )
        await repo.link_to_notebook(
            student_id=student.id, module_id=module.id, submission_id=None, student_notebook_id=second_notebook.id,
        )

        refreshed = await repo.get_by_id(rec.id)
        assert refreshed.student_notebook_id == first_notebook.id

    async def test_link_to_notebook_scoped_by_submission_id(self, db_session, exercise, student, module):
        """submission_id=None ne doit jamais rattacher une ligne dont submission_id est réellement renseigné."""
        from app.domain.repositories.student_notebook_repository import (
            SQLAlchemyStudentNotebookRepository,
        )
        from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository

        sub_repo = SQLAlchemySubmissionRepository(db_session)
        submission = await sub_repo.create(exercise_id=exercise.id, student_id=student.id, attempt_number=1)

        repo = SQLAlchemyRecommendedExerciseRepository(db_session)
        rec_with_submission = await repo.create(
            student_id=student.id, module_id=module.id, competency_code=DAP,
            category=RecommendationCategory.REMEDIATION, submission_id=submission.id,
            exercise_id=exercise.id, reason="Avec soumission", relevance_score=Decimal("0.800"),
        )

        notebook_repo = SQLAlchemyStudentNotebookRepository(db_session)
        notebook = await notebook_repo.create(student_id=student.id, module_id=module.id, notebook_id="nb-1")

        await repo.link_to_notebook(
            student_id=student.id, module_id=module.id, submission_id=None, student_notebook_id=notebook.id,
        )

        refreshed = await repo.get_by_id(rec_with_submission.id)
        assert refreshed.student_notebook_id is None
