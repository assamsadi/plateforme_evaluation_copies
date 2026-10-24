"""
Test d'intégration bout en bout — Competency_Assessment_Agent/
CompetencyAssessmentService (Partie 1/2, chantier C2PCT).

Contre une vraie DB (evaluation_copies_test) : preuve empirique que la
chaîne amont réelle (EvaluationService.record_question_score, tel qu'appelé
par evaluation_node.py) alimente correctement Competency_Assessment_Agent
via CompetencyAssessmentService — StudentCompetencyObservation (Niveau 2,
fait atomique immuable) ET StudentCompetencyProfile (cache Niveau 3) sont
bien persistés, sans aucune connaissance de compétence C2PCT dans
EvaluationService (retirée, cf. docstring evaluation_service.py point 8).
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.agents.Pedagogical_Evaluation_Agent import (
    CompetencyReportLine,
    CompetencyScoreDetail,
    QuestionReport,
    QuestionScoreResult,
    SubquestionScoreDetail,
)
from app.agents.Comparative_Evaluation_Agent import DecisionEntry
from app.core.exceptions import SubmissionPendingArbitrationError
from app.domain.models.academic.group import Group
from app.domain.models.academic.module import Module
from app.domain.models.academic.program import Program
from app.domain.models.assessment.bareme import Bareme, BaremeValidationStatus
from app.domain.models.assessment.exercise import Exercise, ExerciseStatus
from app.domain.models.assessment.question import Question
from app.domain.models.assessment.submission import Submission, SubmissionStatus
from app.domain.models.competency.c2pct_skill_code import C2PCTSkillCode
from app.domain.models.competency.student_competency_observation import (
    StudentCompetencyObservation,
)
from app.domain.models.competency.student_competency_profile import (
    CompetencyTrend,
    StudentCompetencyProfile,
)
from app.domain.repositories.evaluation_repository import SQLAlchemyEvaluationRepository
from app.domain.repositories.exercise_repository import SQLAlchemyExerciseRepository
from app.domain.repositories.student_competency_observation_repository import (
    SQLAlchemyStudentCompetencyObservationRepository,
)
from app.domain.repositories.student_competency_profile_repository import (
    SQLAlchemyStudentCompetencyProfileRepository,
)
from app.domain.repositories.submission_repository import SQLAlchemySubmissionRepository
from app.domain.repositories.user_repository import SQLAlchemyUserRepository
from app.services.competency_assessment_service import CompetencyAssessmentService
from app.services.evaluation_service import EvaluationService

AS = C2PCTSkillCode.ALGORITHMIC_STRUCTURING


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
        first_name="Prof", last_name="Competency", department="Info", title="Dr",
        employee_number=f"EMP_{uuid.uuid4()}"[:20],
    )
    student = await user_repo.create_student(
        email=f"stu_{uuid.uuid4()}@test.com", hashed_password="hash",
        first_name="Alice", last_name="Competency", student_number=f"STU_{uuid.uuid4()}"[:20],
        group_id=group.id, enrollment_year=2024, level="L3",
    )
    return module, professor, student


async def _seed_submission(db_session, module, professor, student, statement="Q1", status=SubmissionStatus.PENDING_EVALUATION):
    exercise = Exercise(
        module_id=module.id, created_by_professor_id=professor.id,
        title="Exercice compétence", status=ExerciseStatus.PUBLISHED_AS_HOMEWORK,
    )
    db_session.add(exercise)
    await db_session.flush()

    question = Question(exercise_id=exercise.id, order=1, statement=statement)
    db_session.add(question)
    await db_session.flush()

    bareme = Bareme(
        question_id=question.id, points=Decimal("4.00"), criteria=[],
        validation_status=BaremeValidationStatus.CONFIRMED,
    )
    db_session.add(bareme)
    await db_session.flush()

    submission = Submission(
        exercise_id=exercise.id, student_id=student.id, attempt_number=1,
        status=status, document_path="x", document_mime_type="application/pdf",
    )
    db_session.add(submission)
    await db_session.flush()

    return exercise, question, bareme, submission


def _services(db_session):
    evaluation_service = EvaluationService(
        evaluation_repo=SQLAlchemyEvaluationRepository(db_session),
        submission_repo=SQLAlchemySubmissionRepository(db_session),
        exercise_repo=SQLAlchemyExerciseRepository(db_session),
        user_repo=SQLAlchemyUserRepository(db_session),
    )
    competency_service = CompetencyAssessmentService(
        evaluation_repo=SQLAlchemyEvaluationRepository(db_session),
        exercise_repo=SQLAlchemyExerciseRepository(db_session),
        submission_repo=SQLAlchemySubmissionRepository(db_session),
        observation_repo=SQLAlchemyStudentCompetencyObservationRepository(db_session),
        profile_repo=SQLAlchemyStudentCompetencyProfileRepository(db_session),
    )
    return evaluation_service, competency_service


@pytest.mark.anyio
async def test_assess_submission_persists_observation_and_profile_end_to_end(db_session):
    module, professor, student = await _seed_module_and_student(db_session)
    exercise, question, bareme, submission = await _seed_submission(db_session, module, professor, student)
    evaluation_service, competency_service = _services(db_session)

    result_score = QuestionScoreResult(
        question_id=question.id, total_score=Decimal("4.00"),
        competency_scores=[
            CompetencyScoreDetail(
                competency_code=AS, covered_count=2, successful_count=2, success_rate=Decimal("1.0"),
                bareme_share=Decimal("4.00"), points_awarded=Decimal("4.00"),
                subquestion_detail=[
                    SubquestionScoreDetail("3.1", True, True, "new_llm_judgment"),
                    SubquestionScoreDetail("3.2", True, True, "new_llm_judgment"),
                ],
            ),
        ],
    )
    question_report = QuestionReport(
        question_id=question.id, note=Decimal("4.00"), bareme_points=Decimal("4.00"),
        competency_lines=[
            CompetencyReportLine(
                competency=AS, subquestions_covered_by_professor=2, subquestions_succeeded_by_student=2,
                bareme_share=Decimal("4.00"), points_awarded=Decimal("4.00"), decisions=[],
            ),
        ],
        consigne_respected=True,
    )

    await evaluation_service.record_question_score(
        submission.id, bareme.id, result_score, question_report=question_report,
    )
    await db_session.flush()

    lines = await competency_service.assess_submission(submission.id)
    await db_session.flush()

    assert len(lines) == 1
    assert lines[0].competency == AS
    assert lines[0].mastery_level == Decimal("100.00")
    assert lines[0].trend == "INSUFFICIENT_DATA"  # première (et unique) observation

    observations = (
        await db_session.execute(
            select(StudentCompetencyObservation).where(
                StudentCompetencyObservation.student_id == student.id,
                StudentCompetencyObservation.competency_code == AS,
            )
        )
    ).scalars().all()
    assert len(observations) == 1
    obs = observations[0]
    assert obs.module_id == module.id
    assert obs.submission_id == submission.id
    assert obs.performance_copie == Decimal("1.00000")
    assert obs.subquestions_covered_count == 2
    assert obs.subquestions_succeeded_count == 2
    assert obs.question_ids == [str(question.id)]

    profile = (
        await db_session.execute(
            select(StudentCompetencyProfile).where(
                StudentCompetencyProfile.student_id == student.id,
                StudentCompetencyProfile.competency_code == AS,
            )
        )
    ).scalar_one()
    assert profile.module_id == module.id
    assert profile.mastery_level == Decimal("100.00")
    assert profile.trend == CompetencyTrend.INSUFFICIENT_DATA
    assert profile.evaluations_count == 1
    assert profile.confidence_level == Decimal("0.20")
    assert profile.is_persistent_weakness is False


@pytest.mark.anyio
async def test_assess_submission_second_submission_applies_exponential_decay_and_trend(db_session):
    """
    Deuxième soumission (même étudiant/module/compétence, succès partiel
    cette fois) -> Niveau 3 recalculé sur les 2 observations réelles,
    jamais un simple remplacement ni une moyenne mobile fixe (mécanisme
    Niveau 1 retiré).
    """
    module, professor, student = await _seed_module_and_student(db_session)
    evaluation_service, competency_service = _services(db_session)

    # Première soumission : succès total.
    _, q1, bareme1, sub1 = await _seed_submission(db_session, module, professor, student, statement="Q1")
    await evaluation_service.record_question_score(
        sub1.id, bareme1.id,
        QuestionScoreResult(
            question_id=q1.id, total_score=Decimal("4.00"),
            competency_scores=[
                CompetencyScoreDetail(
                    competency_code=AS, covered_count=2, successful_count=2, success_rate=Decimal("1.0"),
                    bareme_share=Decimal("4.00"), points_awarded=Decimal("4.00"),
                    subquestion_detail=[
                        SubquestionScoreDetail("3.1", True, True, "new_llm_judgment"),
                        SubquestionScoreDetail("3.2", True, True, "new_llm_judgment"),
                    ],
                ),
            ],
        ),
    )
    await db_session.flush()
    await competency_service.assess_submission(sub1.id)
    await db_session.flush()

    # Postgres now() est figée pour toute la durée d'une transaction — les
    # deux StudentCompetencyObservation de ce test (même db_session, jamais
    # commit avant la fin) recevraient donc un created_at IDENTIQUE
    # (server_default=func.now(), vérifié empiriquement), rendant l'ordre de
    # list_recent() non déterministe (Postgres tranche arbitrairement les
    # égalités). Un artefact du fixture de test (une seule transaction
    # partagée pour 2 soumissions "temporellement" distinctes) — en
    # production, chaque exécution du graph ouvre sa propre session/
    # transaction, donc son propre now(), ce cas ne s'y présente jamais.
    # Antidaté explicitement ici pour rendre le test déterministe.
    await db_session.execute(
        text(
            "UPDATE student_competency_observations SET created_at = created_at - INTERVAL '1 hour' "
            "WHERE submission_id = :sub_id"
        ),
        {"sub_id": sub1.id},
    )
    await db_session.flush()

    # Deuxième soumission : échec total sur la même compétence.
    _, q2, bareme2, sub2 = await _seed_submission(db_session, module, professor, student, statement="Q2")
    await evaluation_service.record_question_score(
        sub2.id, bareme2.id,
        QuestionScoreResult(
            question_id=q2.id, total_score=Decimal("0.00"),
            competency_scores=[
                CompetencyScoreDetail(
                    competency_code=AS, covered_count=2, successful_count=0, success_rate=Decimal("0.0"),
                    bareme_share=Decimal("4.00"), points_awarded=Decimal("0.00"),
                    subquestion_detail=[
                        SubquestionScoreDetail("3.1", True, False, "new_llm_judgment"),
                        SubquestionScoreDetail("3.2", False, None, "missing_judgment"),
                    ],
                ),
            ],
        ),
    )
    await db_session.flush()
    lines = await competency_service.assess_submission(sub2.id)
    await db_session.flush()

    assert len(lines) == 1
    line = lines[0]
    assert line.evaluations_count == 2
    # Décroissance exponentielle (decay=0.9 par défaut) : (1*0 + 0.9*1)/(1+0.9)
    # = 0.9/1.9 = 47.37% -- jamais un simple 50/50 ni un remplacement pur.
    assert line.mastery_level == Decimal("47.37")
    assert line.trend == "DECLINING"
    assert line.confidence_level == Decimal("0.40")

    profile = (
        await db_session.execute(
            select(StudentCompetencyProfile).where(
                StudentCompetencyProfile.student_id == student.id,
                StudentCompetencyProfile.competency_code == AS,
            )
        )
    ).scalar_one()
    assert profile.mastery_level == Decimal("47.37")
    assert profile.trend == CompetencyTrend.DECLINING
    assert profile.evaluations_count == 2


@pytest.mark.anyio
async def test_assess_submission_blocked_when_pending_arbitration_end_to_end(db_session):
    module, professor, student = await _seed_module_and_student(db_session)
    _, _, _, submission = await _seed_submission(
        db_session, module, professor, student, status=SubmissionStatus.PENDING_ARBITRATION,
    )
    _, competency_service = _services(db_session)

    with pytest.raises(SubmissionPendingArbitrationError):
        await competency_service.assess_submission(submission.id)

    observations = (
        await db_session.execute(
            select(StudentCompetencyObservation).where(
                StudentCompetencyObservation.student_id == student.id,
            )
        )
    ).scalars().all()
    assert observations == []
