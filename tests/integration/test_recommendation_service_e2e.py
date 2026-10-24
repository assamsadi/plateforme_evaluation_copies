"""
Test d'intégration — RecommendationService (chantier Recommendation_Agent,
Phase 1 : persistance + agent pur + service). Contre une vraie DB.

Couvre :
  1. generate_recommendations() bout en bout : bibliothèque réelle (2
     exercices ARCHIVED_IN_LIBRARY couvrant des compétences différentes),
     CompetencyProfileLine construites à la main (pas besoin de rejouer
     toute la chaîne Competency_Assessment_Agent ici, déjà testée
     séparément) -> RecommendedExercise persistées avec les bons champs.
  2. Dédoublonnage : une 2ème génération pour la même compétence supersède
     l'ancienne ACTIVE au lieu de s'empiler.
  3. list_active_by_student ne retourne plus que les ACTIVE (plus les
     SUPERSEDED).
  4. Un exercice PUBLISHED_AS_HOMEWORK (pas dans la Library) n'est jamais
     recommandé même s'il couvrirait la compétence.
  5. create_recommendation() (CRUD hérité) dérive bien student_id/module_id
     depuis submission_id/exercise_id.
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents.Competency_Assessment_Agent import CompetencyProfileLine
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.exercise import Exercise, ExerciseDifficulty, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.recommended_exercise import (
    RecommendationStatus,
    RecommendedExercise,
)
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.module_repository import SQLAlchemyModuleRepository
from app.domain.repositories.recommended_exercise_repository import (
    SQLAlchemyRecommendedExerciseRepository,
)
from app.domain.repositories.student_competency_observation_repository import (
    SQLAlchemyStudentCompetencyObservationRepository,
)
from app.domain.repositories.student_competency_profile_repository import (
    SQLAlchemyStudentCompetencyProfileRepository,
)
from app.domain.repositories.student_notebook_repository import (
    SQLAlchemyStudentNotebookRepository,
)
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.services.competency_assessment_service import CompetencyAssessmentService
from app.services.recommendation_service import RecommendationService

AS = C2PCTSkillCode.ALGORITHMIC_STRUCTURING
DAP = C2PCTSkillCode.DATA_AND_PLANNING


async def _seed_module_and_student(db_session):
    user_repo = SQLAlchemyUserRepository(db_session)
    prog = Program(name=f"Prog_{uuid.uuid4()}", code=f"P_{uuid.uuid4()}"[:10])
    db_session.add(prog)
    await db_session.flush()
    module = Module(program_id=prog.id, name=f"Mod_{uuid.uuid4()}", code=f"M_{uuid.uuid4()}"[:10])
    group = Group(program_id=prog.id, label="G1", academic_year="2024-2025")
    db_session.add_all([module, group])
    await db_session.flush()
    professor = await user_repo.create_professor(
        email=f"prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Prof", last_name="Reco", department="Info", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Bob", last_name="Reco", student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id, enrollment_year=2024, level="L3",
    )
    return module, professor, student


async def _seed_library_exercise(
    db_session, module, professor, covered_subquestions, title="Exo bibliotheque", difficulty_level=None,
):
    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title=title, status=ExerciseStatus.ARCHIVED_IN_LIBRARY, difficulty_level=difficulty_level,
    )
    db_session.add(exercise)
    await db_session.flush()
    question = Question(
        exercise_id=exercise.id, order=1, statement="Q1", covered_subquestions=covered_subquestions,
    )
    db_session.add(question)
    await db_session.flush()
    return exercise


def _service(db_session) -> RecommendationService:
    competency_service = CompetencyAssessmentService(
        evaluation_repo=SQLAlchemyEvaluationRepository(db_session),
        exercise_repo=SQLAlchemyExerciseRepository(db_session),
        submission_repo=SQLAlchemySubmissionRepository(db_session),
        observation_repo=SQLAlchemyStudentCompetencyObservationRepository(db_session),
        profile_repo=SQLAlchemyStudentCompetencyProfileRepository(db_session),
        module_repo=SQLAlchemyModuleRepository(db_session),
    )
    return RecommendationService(
        recommendation_repo=SQLAlchemyRecommendedExerciseRepository(db_session),
        exercise_repo=SQLAlchemyExerciseRepository(db_session),
        submission_repo=SQLAlchemySubmissionRepository(db_session),
        evaluation_repo=SQLAlchemyEvaluationRepository(db_session),
        student_notebook_repo=SQLAlchemyStudentNotebookRepository(db_session),
        profile_repo=SQLAlchemyStudentCompetencyProfileRepository(db_session),
        competency_assessment_service=competency_service,
    )


@pytest.mark.anyio
async def test_generate_recommendations_persists_matching_library_exercise(db_session):
    module, professor, student = await _seed_module_and_student(db_session)
    # 3.1/3.2 -> ALGORITHMIC_STRUCTURING (cf. c2pct_scaffold.py).
    library_exercise = await _seed_library_exercise(db_session, module, professor, ["3.1", "3.2"])
    # Exercice PUBLISHED_AS_HOMEWORK (pas la bibliothèque) couvrant la MÊME
    # compétence -> ne doit JAMAIS être recommandé (point 4 du test).
    homework = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Devoir (pas la bibliotheque)", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(homework)
    await db_session.flush()
    homework_question = Question(exercise_id=homework.id, order=1, statement="Q1", covered_subquestions=["3.1"])
    db_session.add(homework_question)
    await db_session.flush()

    lines = [
        CompetencyProfileLine(
            competency=AS, mastery_level=Decimal("25.00"), trend="DECLINING",
            evaluations_count=3, confidence_level=Decimal("0.60"), is_persistent_weakness=True,
        ),
    ]

    service = _service(db_session)
    results = await service.generate_recommendations(
        student_id=student.id, module_id=module.id, competency_lines=lines,
    )
    await db_session.flush()

    assert len(results) == 1
    assert results[0].exercise_id == library_exercise.id
    assert results[0].competency_code == "algorithmic_structuring"
    assert results[0].category == "remediation"
    assert results[0].status == "active"

    persisted = (
        await db_session.execute(select(RecommendedExercise).where(RecommendedExercise.student_id == student.id))
    ).scalars().all()
    assert len(persisted) == 1
    assert persisted[0].module_id == module.id
    assert persisted[0].exercise_id == library_exercise.id


@pytest.mark.anyio
async def test_second_generation_supersedes_previous_active_for_same_competency(db_session):
    module, professor, student = await _seed_module_and_student(db_session)
    exercise = await _seed_library_exercise(db_session, module, professor, ["3.1"])

    service = _service(db_session)
    line = CompetencyProfileLine(
        competency=AS, mastery_level=Decimal("20.00"), trend="STABLE",
        evaluations_count=1, confidence_level=Decimal("0.20"), is_persistent_weakness=False,
    )
    first = await service.generate_recommendations(student.id, module.id, [line])
    await db_session.flush()
    assert len(first) == 1
    first_id = uuid.UUID(str(first[0].id))

    # Nouvelle génération, même compétence toujours faible -> l'ancienne
    # ACTIVE doit être supersédée, pas laissée à s'empiler.
    second = await service.generate_recommendations(student.id, module.id, [line])
    await db_session.flush()
    assert len(second) == 1

    all_rows = (
        await db_session.execute(select(RecommendedExercise).where(RecommendedExercise.student_id == student.id))
    ).scalars().all()
    assert len(all_rows) == 2  # historique conservé (audit), pas supprimé
    by_id = {r.id: r for r in all_rows}
    assert by_id[first_id].status == RecommendationStatus.SUPERSEDED

    active = await SQLAlchemyRecommendedExerciseRepository(db_session).list_active_by_student(student.id)
    assert len(active) == 1
    assert active[0].id != first_id


@pytest.mark.anyio
async def test_no_recommendation_when_competency_resolved(db_session):
    """Une compétence qui n'est plus faible au 2ème passage -> aucune nouvelle recommandation générée pour elle."""
    module, professor, student = await _seed_module_and_student(db_session)
    await _seed_library_exercise(db_session, module, professor, ["3.1"])

    service = _service(db_session)
    weak_line = CompetencyProfileLine(
        competency=AS, mastery_level=Decimal("20.00"), trend="STABLE",
        evaluations_count=1, confidence_level=Decimal("0.20"), is_persistent_weakness=False,
    )
    await service.generate_recommendations(student.id, module.id, [weak_line])
    await db_session.flush()

    resolved_line = CompetencyProfileLine(
        competency=AS, mastery_level=Decimal("95.00"), trend="IMPROVING",
        evaluations_count=5, confidence_level=Decimal("0.90"), is_persistent_weakness=False,
    )
    result = await service.generate_recommendations(student.id, module.id, [resolved_line])
    await db_session.flush()

    assert result == []
    active = await SQLAlchemyRecommendedExerciseRepository(db_session).list_active_by_student(student.id)
    assert active == []  # l'ancienne recommandation n'est plus pertinente et n'a pas été renouvelée


@pytest.mark.anyio
async def test_create_recommendation_derives_student_and_module_from_submission_and_exercise(db_session):
    module, professor, student = await _seed_module_and_student(db_session)
    exercise = await _seed_library_exercise(db_session, module, professor, ["1.1"])
    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.EVALUATED, document_path="x", document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    service = _service(db_session)
    result = await service.create_recommendation(
        submission_id=submission.id, exercise_id=exercise.id, competency_code=DAP,
        reason="Recommandation manuelle du professeur.", relevance_score=Decimal("0.7"),
        requesting_professor_id=professor.id,
    )

    assert result.student_id == student.id
    assert result.module_id == module.id
    assert result.competency_code == "data_and_planning"
    assert result.category == "remediation"


@pytest.mark.anyio
async def test_create_recommendation_professor_not_teaching_module_forbidden(db_session):
    """
    Fermeture de la faille d'accès (chantier Recommendation_Agent, Phase 3)
    — preuve contre une vraie DB : un professeur n'ayant créé AUCUN exercice
    dans ce module est rejeté (ExerciseRepository.exists_professor_exercise_
    in_module, même proxy que get_report_as_professor).
    """
    from app.core.exceptions import ForbiddenError
    from app.domain.repositories.user_repository import SQLAlchemyUserRepository

    module, professor, student = await _seed_module_and_student(db_session)
    exercise = await _seed_library_exercise(db_session, module, professor, ["1.1"])
    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.EVALUATED, document_path="x", document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    user_repo = SQLAlchemyUserRepository(db_session)
    other_professor = await user_repo.create_professor(
        email=f"other_prof_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Other", last_name="Prof", department="Info", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )

    service = _service(db_session)
    with pytest.raises(ForbiddenError):
        await service.create_recommendation(
            submission_id=submission.id, exercise_id=exercise.id, competency_code=DAP,
            reason="Recommandation manuelle.", relevance_score=Decimal("0.7"),
            requesting_professor_id=other_professor.id,
        )


@pytest.mark.anyio
async def test_automatic_generation_supersedes_prior_manual_recommendation_for_same_competency(db_session):
    """
    Angle mort identifié en clôture du chantier — le dédoublonnage de
    generate_recommendations() (list_active_by_student_module_competency,
    jamais de distinction d'origine) doit superséder une recommandation
    créée MANUELLEMENT par un professeur (create_recommendation) au passage
    automatique suivant pour la même (student, module, competency), jamais
    la laisser s'empiler à côté de la nouvelle.
    """
    module, professor, student = await _seed_module_and_student(db_session)
    exercise = await _seed_library_exercise(db_session, module, professor, ["1.1"])
    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.EVALUATED, document_path="x", document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    service = _service(db_session)
    manual = await service.create_recommendation(
        submission_id=submission.id, exercise_id=exercise.id, competency_code=DAP,
        reason="Recommandation manuelle du professeur.", relevance_score=Decimal("0.7"),
        requesting_professor_id=professor.id,
    )
    await db_session.flush()
    manual_id = uuid.UUID(str(manual.id))

    weak_line = CompetencyProfileLine(
        competency=DAP, mastery_level=Decimal("20.00"), trend="STABLE",
        evaluations_count=1, confidence_level=Decimal("0.20"), is_persistent_weakness=False,
    )
    automatic = await service.generate_recommendations(student.id, module.id, [weak_line])
    await db_session.flush()

    assert len(automatic) == 1
    assert uuid.UUID(str(automatic[0].id)) != manual_id

    all_rows = (
        await db_session.execute(select(RecommendedExercise).where(RecommendedExercise.student_id == student.id))
    ).scalars().all()
    by_id = {r.id: r for r in all_rows}
    assert by_id[manual_id].status == RecommendationStatus.SUPERSEDED  # jamais laissée ACTIVE à côté de la nouvelle

    active = await SQLAlchemyRecommendedExerciseRepository(db_session).list_active_by_student(student.id)
    assert len(active) == 1
    assert active[0].id != manual_id


@pytest.mark.anyio
async def test_professor_traceability_view_scoped_to_module(db_session):
    """
    Clôture du chantier — GET /students/{id}/recommendations (vue
    professeur) : preuve contre une vraie DB que get_student_dashboard_as_
    professor() ne retourne que les recommandations ACTIVE du module ciblé,
    jamais celles d'un autre module du même étudiant.
    """
    module, professor, student = await _seed_module_and_student(db_session)
    exercise = await _seed_library_exercise(db_session, module, professor, ["1.1"])

    other_module = Module(program_id=module.program_id, name=f"Autre_{uuid.uuid4()}", code=f"OM_{uuid.uuid4()}"[:10])
    db_session.add(other_module)
    await db_session.flush()
    other_exercise = await _seed_library_exercise(db_session, other_module, professor, ["1.1"], title="Autre exo")

    service = _service(db_session)
    line = CompetencyProfileLine(
        competency=DAP, mastery_level=Decimal("20.00"), trend="STABLE",
        evaluations_count=1, confidence_level=Decimal("0.20"), is_persistent_weakness=False,
    )
    in_module = await service.generate_recommendations(student.id, module.id, [line])
    await service.generate_recommendations(student.id, other_module.id, [line])
    await db_session.flush()

    result = await service.get_student_dashboard_as_professor(
        professor_id=professor.id, student_id=student.id, module_id=module.id,
    )

    assert len(result) == 1
    assert uuid.UUID(str(result[0].id)) == uuid.UUID(str(in_module[0].id))
    assert result[0].module_id == module.id


@pytest.mark.anyio
async def test_generate_recommendations_fine_matching_and_difficulty_preference_against_real_db(db_session):
    """
    Clôture du chantier — preuve contre une vraie DB (pas seulement l'agent
    pur) que _build_library_coverage() dérive bien covered_subquestions/
    difficulty_level depuis Exercise/Question réels, et que l'agent les
    exploite : 2 exercices couvrent AS (3.1 vs 3.2), seul celui qui couvre
    la sous-question RÉELLEMENT ratée matche au niveau fin ; parmi 2
    exercices restants couvrant la même sous-question, celui à la
    difficulté cible du palier (persistant -> FACILE) est préféré.
    """
    module, professor, student = await _seed_module_and_student(db_session)
    # Ne couvre PAS la sous-question ratée (3.1) -> exclu par le matching fin.
    await _seed_library_exercise(
        db_session, module, professor, ["3.2"], title="Hors-sujet",
        difficulty_level=ExerciseDifficulty.FACILE,
    )
    # Couvre 3.1, mais AVANCE (pas la difficulté cible du palier persistant -> FACILE).
    avance_match = await _seed_library_exercise(
        db_session, module, professor, ["3.1"], title="Exo avance",
        difficulty_level=ExerciseDifficulty.AVANCE,
    )
    # Couvre 3.1 ET la difficulté cible -> seul candidat retenu au final.
    facile_match = await _seed_library_exercise(
        db_session, module, professor, ["3.1"], title="Exo facile",
        difficulty_level=ExerciseDifficulty.FACILE,
    )

    lines = [
        CompetencyProfileLine(
            competency=AS, mastery_level=Decimal("15.00"), trend="DECLINING",
            evaluations_count=4, confidence_level=Decimal("0.60"), is_persistent_weakness=True,
            weaknesses=["3.1 (Boucles)"],
        ),
    ]

    service = _service(db_session)
    results = await service.generate_recommendations(student.id, module.id, lines)

    assert len(results) == 1
    assert results[0].exercise_id == facile_match.id
    assert results[0].exercise_id != avance_match.id
    # Clôture des 2 petits trous — difficulty_level exposé comme champ
    # structuré (pas seulement dans le texte de `reason`).
    assert results[0].difficulty_level == "facile"


async def _seed_evaluated_submission(db_session, exercise, question, student, score):
    from app.domain.models.assessment.evaluation import Evaluation

    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=SubmissionStatus.EVALUATED, document_path="x", document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()
    evaluation = Evaluation(submission_id=submission.id, question_id=question.id, score=score)
    db_session.add(evaluation)
    await db_session.flush()
    return submission


async def _seed_library_exercise_with_bareme(db_session, module, professor, covered_subquestions, title, points):
    """Comme _seed_library_exercise, mais garde une référence explicite à la Question (jamais exercise.questions[0], lazy-load async-incompatible juste après flush)."""
    from app.domain.models.assessment.bareme import Bareme, BaremeValidationStatus

    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title=title, status=ExerciseStatus.ARCHIVED_IN_LIBRARY,
    )
    db_session.add(exercise)
    await db_session.flush()
    question = Question(exercise_id=exercise.id, order=1, statement="Q1", covered_subquestions=covered_subquestions)
    db_session.add(question)
    await db_session.flush()
    db_session.add(Bareme(
        question_id=question.id, points=points, criteria=[], validation_status=BaremeValidationStatus.CONFIRMED,
    ))
    await db_session.flush()
    return exercise, question


@pytest.mark.anyio
async def test_generate_recommendations_excludes_exercise_already_fully_succeeded(db_session):
    """
    Historique des soumissions (clôture) — un exercice réussi à SCORE PLEIN
    n'est plus jamais recommandé, mais un exercice réussi PARTIELLEMENT
    reste recommandable (remédiation légitime, cf. docstring service).
    """
    module, professor, student = await _seed_module_and_student(db_session)

    fully_succeeded_exercise, fully_succeeded_question = await _seed_library_exercise_with_bareme(
        db_session, module, professor, ["1.1"], "Reussi a fond", Decimal("10.00"),
    )
    await _seed_evaluated_submission(
        db_session, fully_succeeded_exercise, fully_succeeded_question, student, score=Decimal("10.00"),
    )

    partially_succeeded_exercise, partially_succeeded_question = await _seed_library_exercise_with_bareme(
        db_session, module, professor, ["1.1"], "Reussi en partie", Decimal("10.00"),
    )
    await _seed_evaluated_submission(
        db_session, partially_succeeded_exercise, partially_succeeded_question, student, score=Decimal("6.00"),
    )

    line = CompetencyProfileLine(
        competency=DAP, mastery_level=Decimal("20.00"), trend="STABLE",
        evaluations_count=1, confidence_level=Decimal("0.20"), is_persistent_weakness=False,
    )

    service = _service(db_session)
    results = await service.generate_recommendations(student.id, module.id, [line])

    assert len(results) == 1
    assert results[0].exercise_id == partially_succeeded_exercise.id
    assert results[0].exercise_id != fully_succeeded_exercise.id
